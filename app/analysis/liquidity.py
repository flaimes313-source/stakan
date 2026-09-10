"""
Ликвидность: концентрация в топ-5, крупные заявки, зоны.
"""
from typing import Dict, List

from app.storage.store import Store
from app.config import config
from app.utils.logger import logger


class LiquidityAnalyzer:
    def __init__(self, store: Store):
        self.store = store

    async def analyze(self, symbol: str) -> Dict:
        try:
            ob = await self.store.get_orderbook(symbol)
            if not ob or not ob.get("bids") or not ob.get("asks"):
                return {"total_bid": 0, "total_ask": 0, "concentration": 0, "large_orders": []}

            bids = ob["bids"]
            asks = ob["asks"]

            total_bid = sum(float(s) for _, s in bids)
            total_ask = sum(float(s) for _, s in asks)
            total = total_bid + total_ask
            if total <= 0:
                return {"total_bid": 0, "total_ask": 0, "concentration": 0, "large_orders": []}

            top5_bid = sum(float(s) for _, s in bids[:5])
            top5_ask = sum(float(s) for _, s in asks[:5])
            concentration = (top5_bid + top5_ask) / total

            median = await self.store.get_median_order_size(symbol)
            large_orders = []
            if median > 0:
                for side, rows in (("bid", bids), ("ask", asks)):
                    for price, size in rows[:20]:
                        size = float(size)
                        ratio = size / median
                        if ratio >= config.ORDER_SIZE_THRESHOLDS["large"]:
                            large_orders.append({
                                "side": side,
                                "price": float(price),
                                "size": size,
                                "ratio": ratio,
                                "category": (
                                    "extreme" if ratio >= config.ORDER_SIZE_THRESHOLDS["extreme"]
                                    else "very_large" if ratio >= config.ORDER_SIZE_THRESHOLDS["very_large"]
                                    else "large"
                                ),
                            })

            return {
                "total_bid": total_bid,
                "total_ask": total_ask,
                "concentration": concentration,
                "large_orders": large_orders,
            }
        except Exception as e:
            logger.debug(f"liquidity {symbol}: {e}")
            return {"total_bid": 0, "total_ask": 0, "concentration": 0, "large_orders": []}