from typing import Dict, List, Optional
from datetime import datetime, timedelta
from app.storage.redis import RedisStorage
from app.storage.postgres import PostgresStorage
from app.api.bybit_rest import BybitRestAPI
from app.utils.logger import logger

class FundingManager:
    """Управление данными Funding Rate"""
    
    def __init__(self, rest_api: BybitRestAPI, redis: RedisStorage, postgres: PostgresStorage):
        self.rest = rest_api
        self.redis = redis
        self.postgres = postgres
        self.funding_history: Dict[str, List[Dict]] = {}
        
    async def update_funding(self, symbol: str):
        """Обновить funding rate для символа"""
        try:
            funding_data = await self.rest.get_funding_rate(symbol)
            
            if funding_data:
                # Сохраняем в Redis
                await self.redis.set_funding_data(symbol, funding_data)
                
                # Сохраняем в PostgreSQL
                await self.postgres.save_funding(symbol, funding_data['funding_rate'])
                
                # Обновляем историю
                if symbol not in self.funding_history:
                    self.funding_history[symbol] = []
                
                self.funding_history[symbol].append({
                    'funding_rate': funding_data['funding_rate'],
                    'next_funding_time': funding_data['next_funding_time'],
                    'timestamp': datetime.now()
                })
                
                # Оставляем только последние 50 записей
                if len(self.funding_history[symbol]) > 50:
                    self.funding_history[symbol] = self.funding_history[symbol][-50:]
                
                logger.debug(f"Updated funding for {symbol}: {funding_data['funding_rate']}")
                
        except Exception as e:
            logger.error(f"Error updating funding for {symbol}: {e}")
    
    async def get_funding_change(self, symbol: str) -> float:
        """Получить изменение funding rate"""
        try:
            history = self.funding_history.get(symbol, [])
            if len(history) < 2:
                return 0
            
            current = history[-1]['funding_rate']
            previous = history[0]['funding_rate']
            
            if previous == 0:
                return 0
            
            return ((current - previous) / abs(previous)) * 100
            
        except Exception as e:
            logger.error(f"Error getting funding change: {e}")
            return 0