from typing import Dict, List, Optional
from datetime import datetime, timedelta
from app.api.bybit_rest import BybitRestAPI
from app.storage.redis import RedisStorage
from app.storage.postgres import PostgresStorage
from app.utils.logger import logger

class CandleManager:
    """Управление данными свечей"""
    
    def __init__(self, rest_api: BybitRestAPI, redis: RedisStorage, postgres: PostgresStorage):
        self.rest = rest_api
        self.redis = redis
        self.postgres = postgres
        self.candle_cache: Dict[str, Dict] = {}
        
    async def update_candles(self, symbol: str, timeframe: str = '1h', limit: int = 100):
        """Обновить свечи для символа"""
        try:
            candles = await self.rest.get_klines(symbol, timeframe, limit)
            
            if candles:
                # Сохраняем в PostgreSQL
                for candle in candles:
                    await self.postgres.save_candle(symbol, timeframe, candle)
                
                # Сохраняем в Redis (последние свечи)
                key = f"candles:{symbol}:{timeframe}"
                await self.redis.setex(key, 3600, candles)
                
                # Обновляем кэш
                if symbol not in self.candle_cache:
                    self.candle_cache[symbol] = {}
                self.candle_cache[symbol][timeframe] = candles
                
                logger.debug(f"Updated candles for {symbol} ({timeframe})")
                
        except Exception as e:
            logger.error(f"Error updating candles for {symbol}: {e}")
    
    async def get_candles(self, symbol: str, timeframe: str = '1h', limit: int = 100) -> List[Dict]:
        """Получить свечи"""
        try:
            # Сначала из кэша
            if symbol in self.candle_cache and timeframe in self.candle_cache[symbol]:
                return self.candle_cache[symbol][timeframe][:limit]
            
            # Потом из Redis
            key = f"candles:{symbol}:{timeframe}"
            candles = await self.redis.get(key)
            if candles:
                return candles[:limit]
            
            # И наконец из PostgreSQL
            candles = await self.postgres.get_candles(symbol, timeframe, limit)
            if candles:
                await self.redis.setex(key, 3600, candles)
                return candles
            
            return []
            
        except Exception as e:
            logger.error(f"Error getting candles: {e}")
            return []