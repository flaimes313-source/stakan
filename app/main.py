#!/usr/bin/env python3
import asyncio
import sys
import os
import signal
from datetime import datetime

# Добавляем путь для импортов
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Используем абсолютные импорты (с app.)
from app.config import config
from app.utils.logger import logger
from app.api.bybit_rest import BybitRestAPI
from app.api.bybit_ws import BybitWebSocket
from app.datasets.orderbook import OrderBookManager
from app.datasets.trades import TradeAnalyzer
from app.analysis.levels import LevelAnalyzer
from app.analysis.absorption import AbsorptionDetector
from app.analysis.rating import RatingCalculator
from app.signals.engine import SignalEngine
from app.notifications.telegram import TelegramNotifier
from app.storage.redis import RedisStorage
from app.storage.postgres import PostgresStorage
from app.scheduler.tasks import Scheduler

# Global app reference
app = None

class MarketBot:
    """Main bot class"""
    
    def __init__(self):
        global app
        app = self
        
        logger.info("Initializing MarketBot...")
        
        self.redis = RedisStorage()
        self.postgres = PostgresStorage()
        self.rest_api = BybitRestAPI()
        self.ws = BybitWebSocket()
        
        self.orderbook_manager = None
        self.trade_analyzer = None
        self.level_analyzer = None
        self.absorption_detector = None
        self.rating_calculator = None
        self.signal_engine = None
        self.telegram = None
        self.scheduler = None
        
        self.active_symbols = []
        self.running = False
        
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False
    
    async def initialize(self):
        logger.info("Initializing components...")
        
        try:
            await self.postgres.connect()
            logger.info("✅ PostgreSQL connected")
            
            self.orderbook_manager = OrderBookManager(self.ws, self.redis)
            self.trade_analyzer = TradeAnalyzer(self.redis)
            self.level_analyzer = LevelAnalyzer(self.rest_api, self.redis)
            self.absorption_detector = AbsorptionDetector(self.redis)
            self.rating_calculator = RatingCalculator()
            self.signal_engine = SignalEngine(self.redis, self.postgres)
            self.telegram = TelegramNotifier()
            self.telegram.set_app(self)
            self.scheduler = Scheduler(self)
            
            logger.info("✅ All components initialized")
            
        except Exception as e:
            logger.error(f"❌ Initialization error: {e}")
            raise
    
    async def start(self):
        self.running = True
        logger.info("🚀 Starting Market Bot...")
        
        try:
            await self.update_symbols()
            await self.ws.start()
            await self.orderbook_manager.start()
            await self.signal_engine.start()
            await self.scheduler.start()
            asyncio.create_task(self.telegram.start())
            
            logger.info(f"🎯 Market Bot started with {len(self.active_symbols)} symbols")
            
        except Exception as e:
            logger.error(f"❌ Start error: {e}")
            raise
    
    async def update_symbols(self):
        try:
            logger.info("Updating symbols...")
            symbols = await self.rest_api.get_top_symbols(config.TOP_SYMBOLS_COUNT)
            
            if symbols:
                for symbol in symbols:
                    if symbol not in self.active_symbols:
                        await self.ws.connect(symbol, ['orderbook', 'publicTrade'])
                    await self.level_analyzer.update_levels_for_symbol(symbol)
                
                self.active_symbols = symbols
                await self.redis.set_active_symbols(symbols)
                logger.info(f"✅ Updated symbols: {len(symbols)} active")
                
        except Exception as e:
            logger.error(f"❌ Error updating symbols: {e}")
    
    async def run(self):
        try:
            await self.initialize()
            await self.start()
            
            logger.info("🔄 Bot is running. Press Ctrl+C to stop.")
            while self.running:
                await asyncio.sleep(1)
                
        except asyncio.CancelledError:
            logger.info("Cancelled")
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt")
        except Exception as e:
            logger.error(f"❌ Run error: {e}")
            raise
        finally:
            await self.shutdown()
    
    async def shutdown(self):
        logger.info("🛑 Shutting down...")
        self.running = False
        
        try:
            if self.scheduler:
                await self.scheduler.stop()
            if self.signal_engine:
                await self.signal_engine.stop()
            if self.orderbook_manager:
                await self.orderbook_manager.stop()
            if self.ws:
                await self.ws.stop()
            if self.postgres:
                await self.postgres.close()
            logger.info("✅ Shutdown complete")
        except Exception as e:
            logger.error(f"❌ Shutdown error: {e}")

async def main():
    bot = MarketBot()
    await bot.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)