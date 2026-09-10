from typing import Dict, List, Optional
from datetime import datetime, timedelta
from app.storage.redis import RedisStorage
from app.storage.postgres import PostgresStorage
from app.api.bybit_rest import BybitRestAPI
from app.utils.logger import logger

class OIManager:
    """Управление данными Open Interest"""
    
    def __init__(self, rest_api: BybitRestAPI, redis: RedisStorage, postgres: PostgresStorage):
        self.rest = rest_api
        self.redis = redis
        self.postgres = postgres
        self.oi_history: Dict[str, List[Dict]] = {}
        
    async def update_oi(self, symbol: str):
        """Обновить OI для символа"""
        try:
            oi_data = await self.rest.get_oi(symbol)
            
            if oi_data:
                # Сохраняем в Redis
                await self.redis.set_oi_data(symbol, oi_data)
                
                # Сохраняем в PostgreSQL
                await self.postgres.save_oi(symbol, oi_data['oi'])
                
                # Обновляем историю
                if symbol not in self.oi_history:
                    self.oi_history[symbol] = []
                
                self.oi_history[symbol].append({
                    'oi': oi_data['oi'],
                    'timestamp': datetime.now()
                })
                
                # Оставляем только последние 100 записей
                if len(self.oi_history[symbol]) > 100:
                    self.oi_history[symbol] = self.oi_history[symbol][-100:]
                
                logger.debug(f"Updated OI for {symbol}: {oi_data['oi']}")
                
        except Exception as e:
            logger.error(f"Error updating OI for {symbol}: {e}")
    
    async def get_oi_change(self, symbol: str, minutes: int = 5) -> float:
        """Получить изменение OI за указанный период"""
        try:
            history = self.oi_history.get(symbol, [])
            if len(history) < 2:
                return 0
            
            cutoff = datetime.now() - timedelta(minutes=minutes)
            current = history[-1]['oi']
            
            # Находим ближайшее значение к cutoff
            old = None
            for record in reversed(history):
                if record['timestamp'] <= cutoff:
                    old = record['oi']
                    break
            
            if old is None:
                old = history[0]['oi']
            
            if old == 0:
                return 0
            
            return ((current - old) / old) * 100
            
        except Exception as e:
            logger.error(f"Error getting OI change: {e}")
            return 0