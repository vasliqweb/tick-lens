"""
Breeze session renewal: Playwright fills the ICICI login page, the OTP comes back as a Telegram reply.

  .env  BREEZE_API_KEY, BREEZE_USER_ID, BREEZE_PASSWORD, TELEGRAM_BOT_TOKEN, TELEGRAM_HOME_CHANNEL (or TELEGRAM_CHAT_ID)
  needs pip install playwright && python -m playwright install chromium

renew() writes the new BREEZE_SESSION_TOKEN to .env and returns it. Tokens and OTPs are never logged.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import parse_qs, quote, urlparse

log = logging.getLogger("ltv.breeze.login")
IST = timezone(timedelta(hours=5, minutes=30))
OTP_WAIT = int(os.environ.get("BREEZE_OTP_WAIT", "90"))       # seconds to wait for the Telegram reply
SESSION_STAMP = "# BREEZE_SESSION_TOKEN last updated: "
TOKEN_KEYS = ("apisession", "apisessiontoken", "API_Session", "API_SessionToken", "APISESSION", "APISESSIONTOKEN")
REQUIRED = ("BREEZE_API_KEY", "BREEZE_USER_ID", "BREEZE_PASSWORD", "TELEGRAM_BOT_TOKEN")


def _read_env(path: Path) -> Dict[str, str]:
    env = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return {**env, **{k: v for k, v in os.environ.items() if k.startswith(("BREEZE_", "TELEGRAM_"))}}


def missing_config(path: Path):
    env = _read_env(path)
    miss = [k for k in REQUIRED if not env.get(k)]
    if not (env.get("TELEGRAM_HOME_CHANNEL") or env.get("TELEGRAM_CHAT_ID")):
        miss.append("TELEGRAM_HOME_CHANNEL")
    return miss


class _Telegram:
    def __init__(self, token: str, chat: str):
        self.url = f"https://api.telegram.org/bot{token}"
        self.chat = str(chat)
        self.offset = 0

    def send(self, text: str):
        import requests
        try:
            requests.post(f"{self.url}/sendMessage", json={"chat_id": self.chat, "text": text}, timeout=10)
        except Exception as e:
            log.warning("Telegram send failed: %s", type(e).__name__)

    def baseline(self):
        """Skip replies sent before the OTP request."""
        import requests
        try:
            res = requests.get(f"{self.url}/getUpdates", params={"timeout": 0}, timeout=10).json().get("result", [])
            if res:
                self.offset = res[-1]["update_id"]
        except Exception:
            pass

    def wait_otp(self, timeout: int) -> Optional[str]:
        import requests
        end = time.time() + timeout
        while time.time() < end:
            wait = max(1, min(20, int(end - time.time())))
            try:
                d = requests.get(f"{self.url}/getUpdates", params={"offset": self.offset + 1, "timeout": wait}, timeout=wait + 10).json()
            except Exception:
                time.sleep(2)
                continue
            for u in d.get("result", []):
                self.offset = max(self.offset, u["update_id"])
                m = u.get("message") or {}
                if str((m.get("chat") or {}).get("id", "")) == self.chat:
                    hit = re.search(r"\b(\d{4,8})\b", m.get("text") or "")
                    if hit:
                        return hit.group(1)
        return None


def _token_from_url(url: str) -> Optional[str]:
    q = parse_qs(urlparse(url).query)
    for k in TOKEN_KEYS:
        if q.get(k):
            return q[k][0]
    return None


async def _browser_login(env: Dict[str, str], tg: _Telegram, shots: Path) -> str:
    from playwright.async_api import async_playwright
    shots.mkdir(parents=True, exist_ok=True)
    url = f"https://api.icicidirect.com/apiuser/login?api_key={quote(env['BREEZE_API_KEY'])}"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        page = await (await browser.new_context(viewport={"width": 1280, "height": 800})).new_page()
        posted = {}

        def on_request(req):
            if req.method == "POST" and req.post_data:
                for k in TOKEN_KEYS:
                    m = re.search(rf"{k}=([^&\s]+)", req.post_data)
                    if m:
                        posted["token"] = m.group(1)
        page.on("request", on_request)
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.fill("#txtuid", env["BREEZE_USER_ID"])
            await page.fill("#txtPass", env["BREEZE_PASSWORD"])
            chk = await page.query_selector("#chkssTnc")
            if chk and not await chk.is_checked():
                await chk.check()
            tg.baseline()
            await page.click("#btnSubmit")
            await asyncio.sleep(4)
            tok = _token_from_url(page.url) or posted.get("token")
            if tok:
                return tok
            tg.send("🔐 TickLens: Breeze session expired. Reply with the OTP ICICI just sent you "
                    f"(waiting {OTP_WAIT}s).")
            log.info("Breeze login: waiting up to %ss for the OTP on Telegram", OTP_WAIT)
            otp = await asyncio.to_thread(tg.wait_otp, OTP_WAIT)
            if not otp:
                raise RuntimeError(f"no OTP reply on Telegram within {OTP_WAIT}s")
            boxes = await page.query_selector_all('input[tg-nm="otp"]')
            if len(boxes) >= len(otp):
                for box, digit in zip(boxes, otp):
                    await box.fill(digit)
            else:
                await page.evaluate("(v) => { const h = document.getElementById('hiotp'); if (h) h.value = v; }", otp)
            await asyncio.sleep(1)
            for sel in ("#btnSubmit", "#btnValidate", "#btnVerify", 'input[value*="Submit" i]', 'input[value*="Verify" i]',
                        'button[type="submit"]'):
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.click()
                    break
            else:
                await page.keyboard.press("Enter")
            for _ in range(20):                                   # redirect carries ?apisession=
                await asyncio.sleep(0.5)
                tok = _token_from_url(page.url) or posted.get("token")
                if tok:
                    return tok
            m = re.search(r"apisession[=:]\s*([A-Za-z0-9]+)", await page.inner_text("body"), re.I)
            if m:
                return m.group(1)
            raise RuntimeError("login finished without a session token (wrong OTP?)")
        except Exception:
            try:
                await page.screenshot(path=str(shots / "breeze_login_error.png"))
            except Exception:
                pass
            raise
        finally:
            await browser.close()


def _write_env(path: Path, token: str):
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True) if path.exists() else []
    lines = [l for l in lines if not l.startswith(SESSION_STAMP)]
    stamp = f"{SESSION_STAMP}{datetime.now(IST):%Y-%m-%d %H:%M:%S} IST\n"
    for i, l in enumerate(lines):
        if l.strip().startswith("BREEZE_SESSION_TOKEN="):
            lines[i:i + 1] = [stamp, f"BREEZE_SESSION_TOKEN={token}\n"]
            break
    else:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines += [stamp, f"BREEZE_SESSION_TOKEN={token}\n"]
    path.write_text("".join(lines), encoding="utf-8")


async def renew(env_path: Path, shots: Path) -> str:
    """Log in again, store the new token in .env and os.environ, return it."""
    miss = missing_config(env_path)
    if miss:
        raise RuntimeError("Breeze auto-login needs " + ", ".join(miss) + " in .env")
    env = _read_env(env_path)
    tg = _Telegram(env["TELEGRAM_BOT_TOKEN"], env.get("TELEGRAM_HOME_CHANNEL") or env.get("TELEGRAM_CHAT_ID"))
    try:
        token = await _browser_login(env, tg, shots)
    except Exception as e:
        tg.send(f"❌ TickLens: Breeze auto-login failed: {e}"[:300])
        raise
    _write_env(env_path, token)
    os.environ["BREEZE_SESSION_TOKEN"] = token
    tg.send("✅ TickLens: Breeze session renewed.")
    log.info("Breeze session token renewed")
    return token
