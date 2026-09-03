from typing import Dict, List, Optional
from datetime import datetime, timedelta
from app.storage.redis import RedisStorage
from app.storage.postgres import PostgresStorage
from app.utils.logger import logger

class OIAnalyzer:
    """Анализ Open Interest"""
    
    def __init__(self, redis: RedisStorage, postgres: PostgresStorage):
        self.redis = redis
        self.postgres = postgres
        
    async def analyze_oi(self, symbol: str) -> Dict:
        """Анализировать OI"""
        try:
            current_oi = await self.redis.get_oi_data(symbol)
            current = current_oi.get('oi', 0)
            
            if current == 0:
                return {'oi': 0, 'change_1m': 0, 'change_5m': 0, 'change_15m': 0}
            
            # Получаем исторические значения
            history = await self._get_oi_history(symbol)
            
            # Рассчитываем изменения
            changes = {}
            for minutes in [1, 5, 15, 60]:
                old_oi = self._get_oi_at_time(history, minutes)
                if old_oi > 0:
                    changes[f'change_{minutes}m'] = ((current - old_oi) / old_oi) * 100
                else:
                    changes[f'change_{minutes}m'] = 0
            
            # Анализируем комбинацию Price + OI
            price_data = await self._get_price_change(symbol)
            
            oi_analysis = {
                'symbol': symbol,
                'oi': current,
                **changes,
                'price_change': price_data.get('change', 0),
                'timestamp': datetime.now()
            }
            
            # Определяем тип движения
            oi_analysis['type'] = self._determine_oi_type(oi_analysis)
            
            # Сохраняем в Redis
            await self.redis.set_oi_analysis(symbol, oi_analysis)
            
            return oi_analysis
            
        except Exception as e:
            logger.error(f"Error analyzing OI for {symbol}: {e}")
            return {'oi': 0, 'change_1m': 0, 'change_5m': 0, 'change_15m': 0}
    
    async def _get_oi_history(self, symbol: str) -> List[Dict]:
        """Получить историю OI"""
        try:
            # Из Redis
            history = await self.redis.get_oi_history(symbol)
            if not history:
                # Из PostgreSQL
                history = await self.postgres.get_oi_history(symbol, limit=100)
            return history
        except Exception as e:
            logger.error(f"Error getting OI history: {e}")
            return []
    
    def _get_oi_at_time(self, history: List[Dict], minutes: int) -> float:
        """Получить OI за указанное время"""
        try:
            cutoff = datetime.now() - timedelta(minutes=minutes)
            
            # Ищем ближайшее значение
            for record in sorted(history, key=lambda x: x['timestamp'], reverse=True):
                if record['timestamp'] <= cutoff:
                    return record['oi']
            
            # Если не нашли, берем первое
            if history:
                return history[0]['oi']
            return 0
            
        except Exception as e:
            logger.error(f"Error getting OI at time: {e}")
            return 0
    
    async def _get_price_change(self, symbol: str) -> Dict:
        """Получить изменение цены"""
        try:
            trades = await self.redis.get_recent_trades(symbol, minutes=15)
            if not trades or len(trades) < 2:
                return {'change': 0}
            
            first_price = trades[0]['price']
            last_price = trades[-1]['price']
            
            change = ((last_price - first_price) / first_price) * 100
            
            return {
                'change': change,
                'first_price': first_price,
                'last_price': last_price
            }
            
        except Exception as e:
            logger.error(f"Error getting price change: {e}")
            return {'change': 0}
    
    def _determine_oi_type(self, oi_data: Dict) -> str:
        """Определить тип движения OI"""
        price_change = oi_data.get('price_change', 0)
        oi_change = oi_data.get('change_15m', 0)
        
        if price_change > 0 and oi_change > 0:
            return 'bullish_confirmation'  # Новые лонги
        elif price_change < 0 and oi_change > 0:
            return 'bearish_confirmation'  # Новые шорты
        elif price_change > 0 and oi_change < 0:
            return 'short_covering'  # Закрытие шортов
        elif price_change < 0 and oi_change < 0:
            return 'long_liquidation'  # Закрытие лонгов
        else:
            return 'neutral'