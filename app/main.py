#!/usr/bin/env python3
"""
MarketBot — единая точка сборки.
"""
import asyncio
import os
import signal
import sys

# путь проекта
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import config
from app.utils.logger import logger
from app.api.bybit_rest import BybitRestAPI
from app.storage.store import Store
from app.storage.postgres import PostgresStorage
from app.datasets.market_data import MarketDataCore
from app.datasets.trades import TradeAnalyzer
from app.analysis.levels import LevelAnalyzer
from app.signals.engine import SignalEngine
from app.notifications.telegram import TelegramNotifier
from app.scheduler.tasks import Scheduler


app = None  # глобальный доступ из Telegram


class MarketBot:
    def __init__(self):
        global app
        app = self

        self.store = Store()
        self.postgres = PostgresStorage()
        self.rest = BybitRestAPI()

        self.market_data = None
        self.trades = None
        self.levels = None
        self.engine = None
        self.telegram = None
        self.scheduler = None

        self.running = False

        signal.signal(signal.SIGINT, self._on_sig)
        signal.signal(signal.SIGTERM, self._on_sig)

    def _on_sig(self, *_):
        logger.info("Получен сигнал остановки")
        self.running = False

    # ========== START ==========

    async def initialize(self):
        logger.info("Инициализация...")
        config.validate()

        await self.postgres.connect()  # обязательный

        # Market data core
        self.market_data = MarketDataCore(self.rest, self.store, self.postgres)

        # Анализ
        self.trades = TradeAnalyzer(self.store)
        self.trades.set_postgres(self.postgres)
        await self.trades.load_state()

        self.levels = LevelAnalyzer(self.rest, self.store, self.postgres)

        # Движок сигналов
        self.engine = SignalEngine(self.store, self.postgres, self.trades)

        # Telegram
        self.telegram = TelegramNotifier()
        self.telegram.set_app(self)
        self.engine.set_notifier(self.telegram)

        # Планировщик
        self.scheduler = Scheduler(self)

        logger.info("Все компоненты готовы")

    async def start(self):
        self.running = True
        logger.info("🚀 Старт")

        await self.market_data.start()      # REST + WS + первичный Top-50
        await self.engine.start()
        await self.scheduler.start()

        asyncio.create_task(self.telegram.start())

        logger.info(f"🎯 Активных монет: {len(self.active_symbols)}")

    async def shutdown(self):
        logger.info("🛑 Остановка...")
        self.running = False

        for comp in (self.scheduler, self.engine):
            if comp:
                try:
                    await comp.stop()
                except Exception:
                    pass

        if self.market_data:
            await self.market_data.stop()

        if self.telegram:
            await self.telegram.stop()

        if self.postgres:
            await self.postgres.close()

        logger.info("Готово")

    async def run(self):
        try:
            await self.initialize()
            await self.start()
            while self.running:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            await self.shutdown()

    # ========== ПРОКСИ К MARKET DATA ==========

    @property
    def active_symbols(self):
        return self.market_data.symbols if self.market_data else []


async def main():
    bot = MarketBot()
    await bot.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Остановлено пользователем")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"Fatal: {e}")
        sys.exit(1)