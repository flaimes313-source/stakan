import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.api.bybit_rest import BybitRestAPI
from app.storage.store import Store
from app.storage.postgres import PostgresStorage
from app.analysis.levels import LevelAnalyzer
from app.analysis.liquidity import LiquidityAnalyzer
from app.analysis.rating import RatingCalculator


async def main():
    rest = BybitRestAPI()
    store = Store()
    pg = PostgresStorage()
    await pg.connect()

    levels = LevelAnalyzer(rest, store, pg)
    liq = LiquidityAnalyzer(store)
    rating = RatingCalculator()

    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        print(f"\n===== {sym} =====")
        lv = await levels.calculate_levels(sym)
        print("levels:", len(lv))
        for l in lv[:3]:
            print(f"  {l['price']:.4f} {l['type']} strength={l['strength']} tf={l['timeframe']} touches={l['touches']}")

        r = await rating.calculate(
            symbol=sym,
            orderbook=None,
            delta={"delta": 0},
            cvd=0,
            absorption={"detected": False},
            levels=lv,
            oi={"change_15m": 0},
            funding={"percentile": 50, "is_extreme": False},
            liquidity={"total_bid": 0, "total_ask": 0, "concentration": 0, "large_orders": []},
            volume_ratio=1.0,
        )
        print("rating baseline:", r["total"], r["components"])

    await pg.close()
    await rest.stop()


asyncio.run(main())