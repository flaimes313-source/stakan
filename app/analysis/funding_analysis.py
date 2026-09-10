"""
Funding: нормализованный персентиль по истории монеты.
"""
from typing import Dict, List

from app.storage.postgres import PostgresStorage
from app.utils.logger import logger


class FundingAnalyzer:
    def __init__(self, postgres: PostgresStorage):
        self.postgres = postgres

    async def analyze(self, symbol: str, current_rate: float) -> Dict:
        try:
            history = await self.postgres.get_funding_history(symbol, limit=200)
            rates = [h["funding_rate"] for h in history if h["funding_rate"] is not None]

            if len(rates) < 20:
                return {
                    "funding_rate": current_rate,
                    "percentile": 50.0,
                    "is_extreme": False,
                    "mean": current_rate,
                }

            sorted_r = sorted(rates)
            n = len(sorted_r)
            below = sum(1 for x in sorted_r if x <= current_rate)
            percentile = (below / n) * 100

            mean = sum(rates) / n
            is_extreme = percentile >= 95 or percentile <= 5

            return {
                "funding_rate": current_rate,
                "percentile": percentile,
                "is_extreme": is_extreme,
                "mean": mean,
            }
        except Exception as e:
            logger.debug(f"funding analyze {symbol}: {e}")
            return {"funding_rate": current_rate, "percentile": 50.0, "is_extreme": False, "mean": current_rate}