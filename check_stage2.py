import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config import config
from app.storage.postgres import PostgresStorage
from app.storage.store import Store


async def main():
    print("=== CONFIG ===")
    print("DATABASE_URL set:", bool(config.DATABASE_URL))
    print("use_redis:", config.use_redis)

    print("\n=== POSTGRES ===")
    pg = PostgresStorage()
    try:
        await pg.connect()
        print("PostgreSQL OK")
        rows = await pg.get_oi_history("BTCUSDT", limit=1)
        print("oi_history rows:", len(rows))
    except Exception as e:
        print("PostgreSQL FAILED:", e)
    finally:
        await pg.close()

    print("\n=== STORE (Redis or File) ===")
    store = Store()
    await store.set_active_symbols(["BTCUSDT", "ETHUSDT"])
    print("active:", await store.get_active_symbols())
    await store.add_trade("BTCUSDT", {
        "price": 60000, "size": 0.01, "side": "Buy",
        "notional": 600, "timestamp": __import__("datetime").datetime.now(),
    })
    print("trades:", len(await store.get_recent_trades("BTCUSDT", seconds=60)))


asyncio.run(main())