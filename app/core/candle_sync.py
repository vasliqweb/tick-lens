"""
Keeps the 1m candle store current for every watchlist symbol (all open browser tabs), not only charted ones.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Set, Tuple

log = logging.getLogger("ltv.sync")
EVERY = 600            # seconds between passes
FIRST = 20             # delay before the first pass (let charts load first)
DAYS = 3               # recent days kept current per symbol


class CandleSync:
    def __init__(self):
        self.clients: Dict[int, Set[Tuple[str, str]]] = {}
        self.task: Optional[asyncio.Task] = None

    def watch(self, client: int, items):
        if items:
            self.clients[client] = {(i["source"], i["symbol"]) for i in items if i.get("source") and i.get("symbol")}
        else:
            self.clients.pop(client, None)
        if self.clients and (self.task is None or self.task.done()):
            self.task = asyncio.create_task(self._run())
        self._keep_index_volume(items or [])

    @staticmethod
    def _keep_index_volume(items):
        """Breeze indices on a watchlist: keep their volume current in the 1m cache all day (core/index_volume.py)."""
        try:
            from .breeze import INDEX_LISTS, BreezeHub
            from .index_volume import keep
            from .symbols import is_fno, to_source
            if BreezeHub.get().breeze is None:          # never start a Breeze login (OTP) from a watchlist
                return
            for i in items:
                sym = i.get("symbol") or ""
                if i.get("source") != "breeze" or is_fno(sym):
                    continue
                code = to_source(sym, "breeze")
                if code.upper() in INDEX_LISTS:
                    keep(sym, code)
        except Exception as e:
            log.info("index volume keeper: %s", e)

    async def _run(self):
        await asyncio.sleep(FIRST)
        while self.clients:
            for source, symbol in sorted(set().union(*self.clients.values())):
                try:
                    await self.sync_one(source, symbol)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    log.info("1m sync %s:%s skipped: %s", source, symbol, e)
                await asyncio.sleep(1)
            await asyncio.sleep(EVERY)

    @staticmethod
    async def sync_one(source: str, symbol: str):
        from .candle_store import store_for
        from .symbols import to_source
        store = store_for(source, symbol, to_source(symbol, source))
        if store:
            await store.ensure(datetime.now(timezone.utc).date() - timedelta(days=DAYS))


SYNC = CandleSync()
