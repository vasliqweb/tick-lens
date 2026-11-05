"""Breeze auto-login policy: no OTP spam after hours, back off and give up after failures, detect a second login."""
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from core import breeze, breeze_login

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def hub(monkeypatch):
    calls = {"renew": 0, "notify": []}

    async def fake_renew(env, shots):
        calls["renew"] += 1
        if calls.get("fail"):
            raise RuntimeError("no OTP reply on Telegram within 90s")
        return "tok"

    monkeypatch.setattr(breeze_login, "renew", fake_renew)
    monkeypatch.setattr(breeze_login, "notify", lambda env, text: calls["notify"].append(text))
    monkeypatch.setattr(breeze, "_file_token", lambda *a: "")
    monkeypatch.delenv("BREEZE_AUTO_LOGIN", raising=False)
    h = breeze.BreezeHub()
    h.calls = calls
    return h


def at(monkeypatch, y, m, d, hh, mm):
    now = datetime(y, m, d, hh, mm, tzinfo=IST)
    monkeypatch.setattr(breeze, "_ist_now", lambda: now)
    monkeypatch.setattr(breeze.time, "time", lambda: now.timestamp())
    return now


def run(c):
    return asyncio.run(c)


def test_no_otp_after_hours_or_weekend(hub, monkeypatch):
    for when in ((2026, 11, 5, 23, 0), (2026, 11, 7, 11, 0)):   # Thu night, Saturday
        at(monkeypatch, *when)
        with pytest.raises(RuntimeError, match="outside market hours"):
            run(hub._renew())
    assert hub.calls["renew"] == 0


def test_backoff_then_give_up_once(hub, monkeypatch):
    hub.calls["fail"] = True
    t = at(monkeypatch, 2026, 11, 5, 9, 0).timestamp()
    tries = 0
    for minute in range(0, 120):
        monkeypatch.setattr(breeze.time, "time", lambda m=minute: t + m * 60)
        monkeypatch.setattr(breeze, "_ist_now", lambda m=minute: datetime.fromtimestamp(t + m * 60, IST))
        with pytest.raises(RuntimeError):
            run(hub._renew())
    assert hub.calls["renew"] == breeze.RENEW_MAX_FAILS
    assert len(hub.calls["notify"]) == 1 and "No more OTP" in hub.calls["notify"][0]


def test_manual_connect_ignores_pause(hub, monkeypatch):
    at(monkeypatch, 2026, 11, 5, 23, 0)
    run(hub._renew(manual=True))
    assert hub.calls["renew"] == 1


def test_takeover_detected(hub, monkeypatch):
    t = at(monkeypatch, 2026, 11, 5, 9, 0).timestamp()
    run(hub._renew())                                   # renewed at 09:00
    monkeypatch.setattr(breeze.time, "time", lambda: t + 600)
    with pytest.raises(RuntimeError, match="taken over"):
        run(hub._renew())                               # dead again 10 min later
    assert hub.calls["renew"] == 1 and "another machine" in hub.calls["notify"][0]
    with pytest.raises(RuntimeError, match="paused"):
        run(hub._renew())


def test_auto_login_off(hub, monkeypatch):
    at(monkeypatch, 2026, 11, 5, 10, 0)
    monkeypatch.setenv("BREEZE_AUTO_LOGIN", "0")
    with pytest.raises(RuntimeError, match="off on this machine"):
        run(hub._renew())
    assert hub.calls["renew"] == 0
