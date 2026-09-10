"""
Трейд-аналитика.
CVD считается по НОВЫМ сделкам (дельта один раз), а не по скользящему окну.
"""
from typing import Dict, List, Optional
from datetime import datetime, timedelta

from app.storage.store import Store
from app.utils.logger import logger


class TradeAnalyzer:
    def __init__(self, store: Store):
        self.store = store
        self.postgres = None

        # symbol -> timestamp последней обработанной сделки (ISO)
        self._last_seen_ts: Dict[str, str] = {}
        self._cvd: Dict[str, float] = {}

    def set_postgres(self, postgres):
        self.postgres = postgres

    async def load_state(self):
        """При старте — подтянуть CVD из хранилища, чтобы не потерять."""
        try:
            symbols = await self.store.get_active_symbols()
            for s in symbols:
                self._cvd[s] = await self.store.get_cvd(s)
        except Exception as e:
            logger.debug(f"load_state trades: {e}")

    async def update_cvd_from_trades(self, symbol: str):
        """
        Идём по сделкам окна, фильтруем только НОВЫЕ (по timestamp > last_seen),
        добавляем их дельту к CVD один раз.
        """
        try:
            trades = await self.store.get_recent_trades(symbol, seconds=600)
            if not trades:
                return

            last_ts = self._last_seen_ts.get(symbol)

            new_trades = []
            for t in trades:
                ts = t["timestamp"]
                if last_ts is None or ts > last_ts:
                    new_trades.append(t)

            if not new_trades:
                return

            delta = 0.0
            for t in new_trades:
                if t["side"] == "Buy":
                    delta += t["notional"]
                else:
                    delta -= t["notional"]

            cvd = self._cvd.get(symbol, 0.0) + delta
            self._cvd[symbol] = cvd

            # обновляем "последнюю обработанную"
            new_trades.sort(key=lambda x: x["timestamp"])
            self._last_seen_ts[symbol] = new_trades[-1]["timestamp"]

            await self.store.set_cvd(symbol, cvd)
            await self.store.set_delta(symbol, delta)

        except Exception as e:
            logger.error(f"update_cvd_from_trades {symbol}: {e}")

    async def delta_window(self, symbol: str, seconds: int = 900) -> Dict:
        """Delta за окно (buy - sell) — для сообщений."""
        trades = await self.store.get_recent_trades(symbol, seconds=seconds)
        buy = sum(t["notional"] for t in trades if t["side"] == "Buy")
        sell = sum(t["notional"] for t in trades if t["side"] == "Sell")
        return {"buy": buy, "sell": sell, "delta": buy - sell}

    async def get_cvd(self, symbol: str) -> float:
        return self._cvd.get(symbol, 0.0)

    async def median_trade_size(self, symbol: str) -> float:
        trades = await self.store.get_recent_trades(symbol, seconds=1800)
        if not trades:
            return 0.0
        sizes = sorted(t["size"] for t in trades)
        median = sizes[len(sizes) // 2]
        await self.store.set_median_trade_size(symbol, median)
        return median