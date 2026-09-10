"""
Единая точка входа в market data:
REST (история) + WebSocket (realtime).
"""
import asyncio
from typing import List

from app.api.bybit_rest import BybitRestAPI
from app.api.bybit_ws import BybitWebSocket
from app.datasets.orderbook import OrderBookManager
from app.datasets.trades import TradeAnalyzer
from app.storage.postgres import PostgresStorage
from app.storage.store import Store
from app.config import config
from app.utils.logger import logger


class MarketDataCore:
    def __init__(self, rest: BybitRestAPI, store: Store, postgres: PostgresStorage):
        self.rest = rest
        self.store = store
        self.postgres = postgres
        self.ws = BybitWebSocket()
        self.orderbook = OrderBookManager(self.ws, store)
        self.trades = TradeAnalyzer(store)

        # связи
        self.orderbook.set_postgres(postgres)
        self.trades.set_postgres(postgres)

        self._symbols: List[str] = []

    async def start(self):
        await self.ws.start()
        await self.orderbook.start()
        await self.trades.load_state()

        # первичная загрузка
        await self.refresh_symbols()

    async def stop(self):
        await self.ws.stop()
        await self.orderbook.stop()
        await self.rest.stop()

    async def refresh_symbols(self):
        symbols = await self.rest.get_top_symbols(config.TOP_SYMBOLS_COUNT)
        if not symbols:
            logger.warning("Список символов пуст — Top-50 не обновился")
            return

        self._symbols = symbols
        await self.store.set_active_symbols(symbols)
        await self.ws.subscribe(symbols)
        logger.info(f"✅ Активных символов: {len(symbols)}")

    @property
    def symbols(self) -> List[str]:
        return list(self._symbols)