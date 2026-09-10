"""
OI: current vs 1м/5м/15м/1ч. Все значения берутся из Postgres.
"""
from typing import Dict, List
from datetime import datetime, timedelta

from app.storage.postgres import PostgresStorage
from app.storage.store import Store
from app.utils.logger import logger


class OIAnalyzer:
    def __init__(self, store: Store, postgres: PostgresStorage):
        self.store = store
        self.postgres = postgres

    async def analyze(self, symbol: str) -> Dict:
        try:
            history = await self.postgres.get_oi_history(symbol, limit=200)
            if not history:
                return {"oi": 0, "change_1m": 0, "change_5m": 0, "change_15m": 0, "change_1h": 0}

            # history[0] — самый новый
            current = history[0]["oi"]
            now = history[0]["timestamp"]

            def get_at(minutes: int) -> float:
                target = now - timedelta(minutes=minutes)
                for row in history:
                    if row["timestamp"] <= target:
                        return row["oi"]
                return 0.0

            def pct(old: float) -> float:
                if old <= 0:
                    return 0.0
                return (current - old) / old * 100

            oi_1m = get_at(1)
            oi_5m = get_at(5)
            oi_15m = get_at(15)
            oi_1h = get_at(60)

            result = {
                "oi": current,
                "change_1m": pct(oi_1m),
                "change_5m": pct(oi_5m),
                "change_15m": pct(oi_15m),
                "change_1h": pct(oi_1h),
            }
            return result
        except Exception as e:
            logger.debug(f"OI analyze {symbol}: {e}")
            return {"oi": 0, "change_1m": 0, "change_5m": 0, "change_15m": 0, "change_1h": 0}