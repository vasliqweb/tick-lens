"""Download an index's constituents (1m, with volume) into data/Breeze and fill the index volume.

    python scripts/prefetch_index.py NIFTY 90
    python scripts/prefetch_index.py BANKNIFTY 180
"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import prefetch  # noqa: E402


async def main(index: str, days: int):
    task = asyncio.create_task(prefetch.run(index.upper(), days))
    while not task.done():
        st = prefetch.JOBS.get(index.upper(), {})
        print(f"\r{st.get('stage', '')}: {st.get('done', 0)}/{st.get('total', 0)} stocks {st.get('current', ''):<14}", end="", flush=True)
        await asyncio.sleep(1)
    st = prefetch.JOBS[index.upper()]
    print(f"\n{st['stage']}: {st['done']}/{st['total']} stocks, index volume written for {st['summed']} days")
    for e in st["errors"]:
        print("  !", e)


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "NIFTY", int(sys.argv[2]) if len(sys.argv) > 2 else 30))
