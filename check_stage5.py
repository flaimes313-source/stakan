import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.storage.store import Store
from app.storage.postgres import PostgresStorage
from app.datasets.trades import TradeAnalyzer
from app.signals.engine import SignalEngine
from app.signals.memory import SignalMemory


async def main():
    store = Store()
    pg = PostgresStorage()
    await pg.connect()

    trades = TradeAnalyzer(store)
    engine = SignalEngine(store, pg, trades)

    print("signal engine OK")
    print("memory:")
    mem = SignalMemory(store)
    await mem.load()
    ok = await mem.should_send("BTCUSDT", "SHORT", 85, 77000)
    print("  first should_send:", ok)
    await mem.remember("BTCUSDT", "SHORT", 85, 77000, "test")
    ok2 = await mem.should_send("BTCUSDT", "SHORT", 86, 77000)
    print("  second should_send (should be False):", ok2)
    ok3 = await mem.should_send("BTCUSDT", "SHORT", 95, 77000)
    print("  third should_send +10 (should be True):", ok3)

    await pg.close()


asyncio.run(main())