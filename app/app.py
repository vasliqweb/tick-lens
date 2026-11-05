"""
TickLens - browser charting app (FastAPI + TradingView lightweight-charts).

Run:
    pip install -r requirements.txt
    python app.py            # then open http://127.0.0.1:8000

Security: indicator scripts are Python executed on this machine. The server binds to
127.0.0.1 only and the WebSocket rejects connections from other web origins, so other
websites cannot send scripts to it. Do not expose this app on a network.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core.paper import router as paper_router
from core.quotes import QuoteWatcher
from core.scripting import title_of
from core.session import ChartSession

ROOT = Path(__file__).parent
BUILTINS = ROOT / "builtins"
USER = ROOT / "scripts"
USER.mkdir(exist_ok=True)
LAYOUTS = ROOT / "layouts"          # saved chart layouts (JSON, one file each)
LAYOUTS.mkdir(exist_ok=True)
NAME_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
# Extra hosts the live socket accepts (comma-separated), e.g. a private Tailscale IP/name:
#   LTV_ALLOWED_HOSTS=100.71.75.126,laxman.tail7c96d8.ts.net
# Only add hosts on a private network you control: scripts are Python run on this machine.
LOCAL_HOSTS |= {h.strip().lower() for h in os.environ.get("LTV_ALLOWED_HOSTS", "").split(",") if h.strip()}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
app = FastAPI(title="TickLens")
app.include_router(paper_router)            # paper trading (simulated, no broker orders)


@app.on_event("startup")
async def _paper_engine():
    """Server-side paper orders (index triggers, range limits, index SL / target) keep running without a browser."""
    from core.paper_engine import Engine
    Engine.get().start()


@app.middleware("http")
async def no_stale_assets(request, call_next):
    """Make the browser revalidate the page and its scripts, so every chart frame runs the same (latest) code."""
    resp = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(ROOT / "static" / "favicon-32.png", media_type="image/png")


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    """Served from the root so it may control the whole app (installable PWA). Only caches the app shell."""
    return FileResponse(ROOT / "static" / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    return FileResponse(ROOT / "static" / "manifest.webmanifest", media_type="application/manifest+json")


# ---------------------------------------------------------------- scripts
def _list(folder: Path, kind: str):
    out = []
    for p in sorted(folder.glob("*.py")):
        code = p.read_text(encoding="utf-8")
        out.append({"id": f"{kind}:{p.stem}", "name": p.stem, "kind": kind, "title": title_of(code, p.stem)})
    return out


def _path(sid: str) -> Path:
    kind, _, name = sid.partition(":")
    if not NAME_RE.match(name) or kind not in ("builtin", "user"):
        raise HTTPException(400, "bad script id")
    return (BUILTINS if kind == "builtin" else USER) / f"{name}.py"


_NEWS: dict = {}


@app.get("/api/news")
def news(q: str, limit: int = 30):
    """Headlines from Google News RSS (free, no key); cached 5 minutes per query."""
    import email.utils
    import xml.etree.ElementTree as ET
    import requests
    q = q.strip()[:80]
    hit = _NEWS.get(q)
    if hit and time.time() - hit[0] < 300:
        return hit[1][:limit]
    try:
        r = requests.get("https://news.google.com/rss/search", params={"q": f"{q} when:7d", "hl": "en-IN", "gl": "IN", "ceid": "IN:en"},
                         timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        root = ET.fromstring(r.content)
    except Exception as e:
        raise HTTPException(502, f"news unavailable: {type(e).__name__}")
    out = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        src = it.find("source")
        try:
            ts = email.utils.parsedate_to_datetime(it.findtext("pubDate") or "").timestamp()
        except Exception:
            ts = 0
        out.append({"title": title, "link": it.findtext("link") or "", "source": src.text if src is not None else "", "t": ts})
    out.sort(key=lambda x: -x["t"])
    _NEWS[q] = (time.time(), out)
    return out[:limit]


@app.get("/api/expiries")
async def expiries(roots: str = "NIFTY,BANKNIFTY,FINNIFTY,SENSEX"):
    """Upcoming F&O expiries per underlying, from the Breeze contract master."""
    from core.breeze import BreezeHub
    hub = BreezeHub.get()
    if hub.breeze is None:                       # never start a login (OTP) just for the calendar
        raise HTTPException(503, "connect Breeze to see expiries")
    try:
        m = await hub.master()
    except Exception as e:
        raise HTTPException(503, f"Breeze not available: {e}"[:200])
    out = {}
    for root in [r.strip().upper() for r in roots.split(",") if r.strip()][:12]:
        ex = {}
        for c in m["fno"]:
            if c["under"] == root:
                e = ex.setdefault(c["expiry"].isoformat(), {"date": c["expiry"].isoformat(), "fut": False, "opt": False})
                e["fut" if c["kind"] == "FUT" else "opt"] = True
        out[root] = sorted(ex.values(), key=lambda x: x["date"])[:8]
    return out


@app.get("/api/cache")
def cache_summary(source: str, symbol: str):
    """What the local candle cache holds for one symbol: 1m day files and the per-timeframe files."""
    from core.candle_store import FOLDER, ROOT as DATA, TF_NAME, _safe, folder_for
    from core.symbols import to_source
    try:
        folder = DATA / FOLDER.get(source, source) / _safe(folder_for(source, symbol, to_source(symbol, source)))
    except ValueError as e:
        raise HTTPException(400, str(e))
    out = {"path": str(folder.relative_to(DATA.parent)), "files": []}
    days = sorted((folder / "1m").glob("*.csv")) if (folder / "1m").exists() else []
    if days:
        rows = sum(max(0, sum(1 for _ in open(f, encoding="utf-8")) - 1) for f in days[-400:])
        out["files"].append({"tf": "1m", "first": days[0].stem, "last": days[-1].stem, "days": len(days), "rows": rows,
                             "bytes": sum(f.stat().st_size for f in days)})
    for name in TF_NAME.values():
        for f in (folder / f"{name}.csv", folder / f"{name}_ext.csv"):
            if f.exists():
                lines = f.read_text(encoding="utf-8").splitlines()
                if len(lines) > 1:
                    first, last = int(lines[1].split(",")[0]), int(lines[-1].split(",")[0])
                    out["files"].append({"tf": f.stem, "first": first, "last": last, "rows": len(lines) - 1, "bytes": f.stat().st_size})
    return out


@app.post("/api/prefetch")
async def prefetch_start(body: dict = Body(...)):
    from core import prefetch
    try:
        return prefetch.start(str(body.get("index", "NIFTY")), max(1, min(int(body.get("days", 30)), 1500)))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/prefetch")
def prefetch_status():
    from core import prefetch
    return prefetch.status()


@app.get("/api/breeze/status")
def breeze_status():
    from core.breeze import BreezeHub
    return BreezeHub.get().status()


@app.post("/api/breeze/connect")
async def breeze_connect():
    from core.breeze import BreezeHub
    hub = BreezeHub.get()
    try:
        await hub.reconnect()
    except Exception as e:
        raise HTTPException(400, str(e)[:300])
    return hub.status()


@app.get("/api/config")
def config():
    from core.breeze import load_env
    import os
    load_env()
    return {"breeze": all(os.environ.get(k) for k in ("BREEZE_API_KEY", "BREEZE_API_SECRET"))}


@app.get("/api/scripts")
def list_scripts():
    return _list(BUILTINS, "builtin") + _list(USER, "user")


@app.get("/api/scripts/{sid}")
def get_script(sid: str):
    p = _path(sid)
    if not p.exists():
        raise HTTPException(404, "not found")
    return {"id": sid, "code": p.read_text(encoding="utf-8")}


@app.put("/api/scripts/{sid}")
def save_script(sid: str, body: dict = Body(...)):
    if not sid.startswith("user:"):
        raise HTTPException(403, "built-in scripts are read-only; save under a new name")
    p = _path(sid)
    p.write_text(body.get("code", ""), encoding="utf-8")
    return {"id": sid, "title": title_of(body.get("code", ""), p.stem)}


@app.delete("/api/scripts/{sid}")
def delete_script(sid: str):
    if not sid.startswith("user:"):
        raise HTTPException(403, "built-in scripts are read-only")
    _path(sid).unlink(missing_ok=True)
    return {"ok": True}


# ---------------------------------------------------------------- symbols
# ---------------------------------------------------------------- TradingView account (session cached locally)
@app.get("/api/tv/account")
def tv_account():
    from core.tradingview import AUTH
    return {"user": AUTH.user}


@app.post("/api/tv/login")
async def tv_login(body: dict = Body(...)):
    from core.tradingview import AUTH, TVHub
    try:
        if body.get("code"):
            res = await asyncio.to_thread(AUTH.login_2fa, str(body["code"]))
        elif body.get("auto"):
            res = await asyncio.to_thread(AUTH.from_browser)
        elif body.get("har"):
            res = await asyncio.to_thread(AUTH.from_har, str(body["har"]))
        elif body.get("sessionid"):
            res = await asyncio.to_thread(AUTH.use_session, str(body["sessionid"]), str(body.get("sessionid_sign", "")))
        else:
            res = await asyncio.to_thread(AUTH.login, str(body.get("username", "")), str(body.get("password", "")))
    except Exception as e:
        raise HTTPException(400, str(e)[:300])
    await TVHub.get().restart()
    return res


@app.post("/api/tv/logout")
async def tv_logout():
    from core.tradingview import AUTH, TVHub
    AUTH.logout()
    await TVHub.get().restart()
    return {"user": None}


# ---------------------------------------------------------------- saved layouts
def _layout_path(lid: str) -> Path:
    if not re.fullmatch(r"[a-z0-9]{6,40}", lid or ""):
        raise HTTPException(400, "bad layout id")
    return LAYOUTS / f"{lid}.json"


@app.get("/api/layouts")
def list_layouts():
    out = []
    for f in LAYOUTS.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            out.append({"id": f.stem, "name": d.get("name", f.stem), "summary": d.get("summary", ""), "updated": d.get("updated", 0)})
        except Exception:
            continue
    return sorted(out, key=lambda x: -x["updated"])


@app.get("/api/layouts/{lid}")
def get_layout(lid: str):
    p = _layout_path(lid)
    if not p.exists():
        raise HTTPException(404, "layout not found")
    return json.loads(p.read_text(encoding="utf-8"))


@app.put("/api/layouts/{lid}")
def save_layout(lid: str, body: dict = Body(...)):
    name = str(body.get("name") or "").strip()[:60]
    if not name:
        raise HTTPException(400, "layout name required")
    doc = {"name": name, "summary": str(body.get("summary", ""))[:80], "updated": int(time.time() * 1000), "data": body.get("data") or {}}
    _layout_path(lid).write_text(json.dumps(doc), encoding="utf-8")
    return {"id": lid, "updated": doc["updated"]}


@app.delete("/api/layouts/{lid}")
def delete_layout(lid: str):
    _layout_path(lid).unlink(missing_ok=True)
    return {"ok": True}


@app.get("/api/search")
async def search(q: str, source: str = "yf", kind: str = ""):
    """Symbol search. Results use app names (RELIANCE, NIFTY, NIFTY 27NOV26 24000 CE, SENSEX 13NOV26 80000 CE).
    kind: "" | index | stock | fut | opt (Breeze filters server-side; the page also filters every source).
    Each result carries "exchange" (NSE / BSE / MCX / "")."""
    from core.symbols import canonical, exchange_of

    def tag(rows):
        for r in rows:
            r.setdefault("exchange", exchange_of(r.get("symbol", "")) if r.get("symbol") else "")
        return rows
    if source == "tv":
        from core.tradingview import search as tv_search
        try:
            return tag(await tv_search(q))
        except Exception as e:
            return [{"symbol": canonical(q), "name": f"(TradingView search unavailable: {type(e).__name__})", "type": ""}]
    if source == "breeze":
        from core.breeze import BreezeHub
        try:
            return await BreezeHub.get().search(q, kind=kind)
        except Exception as e:
            return [{"symbol": canonical(q), "name": f"(search unavailable: {e})"[:120], "type": ""}]
    try:
        import yfinance as yf
        res = await asyncio.to_thread(lambda: yf.Search(q, max_results=12, news_count=0).quotes)
        out, seen = [], set()
        for r in res:
            sym = canonical(r.get("symbol") or "")
            if sym and sym not in seen:
                seen.add(sym)
                out.append({"symbol": sym, "name": r.get("shortname") or r.get("longname") or "",
                            "type": f"{r.get('exchange', '')} {r.get('quoteType', '')}".strip(),
                            "exchange": {"NSI": "NSE", "BSE": "BSE"}.get(r.get("exchange", ""), exchange_of(sym) if r.get("exchange") in ("NSI", "BSE", "") else "")})
        return out
    except Exception as e:
        return [{"symbol": canonical(q), "name": f"(search unavailable: {type(e).__name__})", "type": ""}]


# ---------------------------------------------------------------- live chart socket
def _same_origin(ws: WebSocket) -> bool:
    origin = ws.headers.get("origin")
    if not origin:
        return False
    return urlparse(origin).netloc == ws.headers.get("host") and urlparse(origin).hostname in LOCAL_HOSTS


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    if not _same_origin(ws):
        await ws.close(code=1008)
        return
    await ws.accept()
    lock = asyncio.Lock()

    async def send(msg):
        async with lock:
            await ws.send_text(json.dumps(msg, allow_nan=False, default=float))

    sess = ChartSession(send)
    quotes = QuoteWatcher(send)
    try:
        while True:
            m = json.loads(await ws.receive_text())
            op = m.get("op")
            try:
                if op == "load":
                    await send({"type": "status", "msg": f"loading {m['symbol']}..."})
                    asyncio.create_task(_safe(send, sess.load(m["source"], m["symbol"], int(m["tf"]), m.get("lookback"), bool(m.get("extended")), m.get("replay"))))
                elif op == "replay_start":
                    asyncio.create_task(_safe(send, sess.replay_start(int(m["t"]), m.get("step"))))
                elif op == "replay_step":
                    asyncio.create_task(_safe(send, sess.replay_step(int(m.get("n", 1)))))
                elif op == "more":
                    asyncio.create_task(_safe(send, sess.more()))
                elif op == "set_indicator":
                    asyncio.create_task(_safe(send, sess.set_indicator(m["id"], m["code"], m.get("inputs", {}))))
                elif op == "vprofile":
                    asyncio.create_task(_safe(send, sess.range_profile(m["key"], int(m["t1"]), int(m["t2"]), m.get("layout", "Number of Rows"),
                                                                       float(m.get("rows", 24)), float(m.get("va", 70)), bool(m.get("use_ib", True)),
                                                                       str(m.get("kind", "frvp")))))
                elif op == "remove_indicator":
                    await sess.remove_indicator(m["id"])
                elif op == "watch":
                    asyncio.create_task(_safe(send, quotes.set(m.get("items", []))))
                    from core.candle_sync import SYNC
                    SYNC.watch(id(ws), m.get("items", []))
            except KeyError as e:
                await send({"type": "error", "msg": f"missing field {e}"})
    except WebSocketDisconnect:
        pass
    finally:
        await sess.close()
        await quotes.close()
        from core.candle_sync import SYNC
        SYNC.watch(id(ws), [])


async def _safe(send, coro):
    try:
        await coro
    except Exception as e:
        logging.exception("op failed")
        try:
            await send({"type": "error", "msg": f"{type(e).__name__}: {e}"})
        except Exception:
            pass


if __name__ == "__main__":
    import argparse

    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    uvicorn.run(app, host="127.0.0.1", port=ap.parse_args().port)
