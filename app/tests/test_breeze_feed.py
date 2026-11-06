"""Live feed refused while REST works: report it in the status and repair it (new client, then fresh login)."""
import asyncio

from core import breeze

BAD = "Exception while subscribing to feeds Could not authenticate credentials. Please check token and keys"


class FakeClient:
    def __init__(self, ok):
        self.ok, self.subs, self.on_ticks = ok, [], None

    def ws_connect(self):
        pass

    def ws_disconnect(self):
        pass

    def subscribe_feeds(self, stock_token):
        self.subs.append(stock_token)
        return {"message": f"Stock {stock_token} subscribed successfully"} if self.ok else BAD


def test_feed_failed_detection():
    assert breeze._feed_failed(BAD)
    assert not breeze._feed_failed({"message": "Stock 4.1!1594 subscribed successfully"})


def test_refused_feed_is_reported_and_repaired(monkeypatch):
    clients = [FakeClient(False), FakeClient(True)]
    made = []

    def login():
        c = clients[len(made)]
        made.append(c)
        return c

    monkeypatch.setattr(breeze.BreezeHub, "_login", staticmethod(login))
    monkeypatch.setattr(breeze, "FEED_HEAL_GAP", 0.0)
    monkeypatch.setattr(breeze, "_token_stamp", lambda: "")
    import core.breeze_login as bl
    monkeypatch.setattr(bl, "missing_config", lambda env: [], raising=False)

    async def go():
        h = breeze.BreezeHub()
        h._master_task = object()                       # skip the F&O master download
        h._heal_at = 1e18                               # hold the repair until the status was checked
        for tok in ("4.1!1594", "4.1!2885"):
            await h.subscribe(tok, lambda t: None)
        st = h.status()
        assert st["feed"]["failed"] == 2 and "Could not authenticate" in st["error"]
        h._heal_at = 0.0
        h._schedule_heal()
        for _ in range(50):                             # let the scheduled repair run
            await asyncio.sleep(0.01)
            if not h._healing:
                break
        st = h.status()
        assert len(made) == 2 and sorted(clients[1].subs) == ["4.1!1594", "4.1!2885"]
        assert st["feed"] == {"ok": 2, "failed": 0, "error": ""} and st["error"] == ""

    asyncio.run(go())
