"""
Bulk download of an index's constituents (1m candles with volume) into the candle store, then index volume
for every finished day = sum of the constituents' 1m volume, written into the index's own 1m files.

  POST /api/prefetch {"index": "NIFTY", "days": 90}      (or: python scripts/prefetch_index.py NIFTY 90)
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Dict

import pandas as pd

log = logging.getLogger("ltv.prefetch")
INDEXES = {"NIFTY": "NIFTY", "BANKNIFTY": "CNXBAN", "SENSEX": "BSESEN", "BANKEX": "BANKEX"}     # app name -> Breeze code with a constituent list
CONCURRENCY = 3
JOBS: Dict[str, dict] = {}
_tasks: Dict[str, asyncio.Task] = {}


def status() -> Dict[str, dict]:
    return {k: {x: v for x, v in st.items() if x != "errors"} | {"errors": st["errors"][-5:]} for k, st in JOBS.items()}


def start(index: str, days: int) -> dict:
    index = index.upper()
    if index not in INDEXES:
        raise ValueError(f"no constituent list for {index} (have: {', '.join(INDEXES)})")
    t = _tasks.get(index)
    if t and not t.done():
        return JOBS[index]
    JOBS[index] = {"index": index, "days": int(days), "stage": "starting", "total": 0, "done": 0, "current": "",
                   "errors": [], "started": time.time(), "finished": None, "summed": 0}
    _tasks[index] = asyncio.create_task(run(index, int(days)))
    return JOBS[index]


async def run(index: str, days: int):
    from .breeze import BreezeHub
    from .candle_store import store_for
    st = JOBS.setdefault(index, {"index": index, "days": days, "total": 0, "done": 0, "current": "", "errors": [],
                                 "started": time.time(), "finished": None, "summed": 0})
    hub, code = BreezeHub.get(), INDEXES[index]
    begin = datetime.now(timezone.utc).date() - timedelta(days=days)
    try:
        st["stage"] = "index"
        idx = store_for("breeze", index, code)
        await idx.ensure(begin)
        names = await hub.constituents(code)
        st.update(stage="stocks", total=len(names))
        sem = asyncio.Semaphore(CONCURRENCY)

        async def one(name):
            async with sem:
                st["current"] = name
                try:
                    await store_for("breeze", name, name).ensure(begin)
                except Exception as e:
                    st["errors"].append(f"{name}: {e}"[:160])
                    log.warning("prefetch %s: %s", name, e)
                st["done"] += 1
        await asyncio.gather(*(one(n) for n in names))
        st.update(stage="volume", current="")
        st["summed"] = sum_volume(index, code, names)
        st["stage"] = "done"
    except Exception as e:
        st.update(stage="failed", current="")
        st["errors"].append(str(e)[:200])
        log.warning("prefetch %s failed: %s", index, e)
    finally:
        st["finished"] = time.time()


def sum_volume(index: str, code: str, names) -> int:
    """Index volume for every finished day not done yet; returns the number of days written."""
    from .candle_store import store_for
    idx = store_for("breeze", index, code)
    done = set(idx.meta.get("ivol", []))
    todo = [d for d in idx.meta.get("done", []) if d not in done]
    stores = [store_for("breeze", n, n) for n in names]
    n = 0
    for key in todo:
        d = datetime.fromisoformat(key).date()
        day = idx._read_day(d)
        if not len(day):
            continue
        vols = [s._read_day(d)["volume"] for s in stores]
        vols = [v for v in vols if len(v)]
        if len(vols) < max(1, len(stores) // 2):          # too few constituents on disk for that day yet
            continue
        tot = pd.concat(vols, axis=1).sum(axis=1, min_count=1)
        day["volume"] = tot.reindex(day.index).fillna(0.0).to_numpy()
        idx._write_day(d, day)
        done.add(key)
        n += 1
    idx.meta["ivol"] = sorted(done)
    idx._save_meta()
    return n
