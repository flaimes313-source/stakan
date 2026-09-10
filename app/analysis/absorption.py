"""
Поглощение — временное событие в окне N секунд, а не сравнение объёмов.
"""
import asyncio
from typing import Dict, Optional
from datetime import datetime, timedelta

from app.storage.store import Store
from app.config import config
from app.utils.logger import logger


class AbsorptionDetector:
    def __init__(self, store: Store):
        self.store = store

    async def detect(self, symbol: str) -> Dict:
        try:
            ob = await self.store.get_orderbook(symbol)
            if not ob or not ob.get("bids") or not ob.get("asks"):
                return {"detected": False}

            window = config.ABSORPTION_WINDOW_SEC
            trades = await self.store.get_recent_trades(symbol, seconds=window)
            if not trades:
                return {"detected": False}

            best_bid = float(ob["bids"][0][0])
            best_ask = float(ob["asks"][0][0])
            mid = (best_bid + best_ask) / 2
            if mid <= 0:
                return {"detected": False}

            # Цена в окне
            prices = [t["price"] for t in trades]
            price_change = (prices[-1] - prices[0]) / prices[0] if prices[0] else 0.0

            buy_vol = sum(t["notional"] for t in trades if t["side"] == "Buy")
            sell_vol = sum(t["notional"] for t in trades if t["side"] == "Sell")

            median_trade = await self.store.get_median_trade_size(symbol)
            # Динамический порог: не меньше 5 * медианного notional и не меньше $50k
            dyn_threshold = max(median_trade * 5, 50_000)

            # Поглощение продавцом: агрессивные покупки, цена у ask, стоит
            if buy_vol >= dyn_threshold and abs(price_change) < 0.0008:
                ask_top_vol = sum(float(s) for _, s in ob["asks"][:5])
                if ask_top_vol > 0 and buy_vol / ask_top_vol > 0.5:
                    confidence = min(100, int((buy_vol / dyn_threshold) * 40))
                    return {
                        "detected": True,
                        "type": "SELLER_ABSORPTION",
                        "buy_volume": buy_vol,
                        "sell_volume": sell_vol,
                        "price_change": price_change,
                        "threshold": dyn_threshold,
                        "confidence": confidence,
                    }

            # Поглощение покупателем: агрессивные продажи, цена у bid, стоит
            if sell_vol >= dyn_threshold and abs(price_change) < 0.0008:
                bid_top_vol = sum(float(s) for _, s in ob["bids"][:5])
                if bid_top_vol > 0 and sell_vol / bid_top_vol > 0.5:
                    confidence = min(100, int((sell_vol / dyn_threshold) * 40))
                    return {
                        "detected": True,
                        "type": "BUYER_ABSORPTION",
                        "buy_volume": buy_vol,
                        "sell_volume": sell_vol,
                        "price_change": price_change,
                        "threshold": dyn_threshold,
                        "confidence": confidence,
                    }

            return {"detected": False}

        except Exception as e:
            logger.error(f"absorption {symbol}: {e}")
            return {"detected": False}