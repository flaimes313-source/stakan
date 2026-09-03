from typing import Dict, List, Optional
from datetime import datetime, timedelta
from app.storage.redis import RedisStorage
from app.storage.postgres import PostgresStorage
from app.utils.logger import logger

class FundingAnalyzer:
    """Анализ Funding Rate"""
    
    def __init__(self, redis: RedisStorage, postgres: PostgresStorage):
        self.redis = redis
        self.postgres = postgres
        
    async def analyze_funding(self, symbol: str) -> Dict:
        """Анализировать funding rate"""
        try:
            current_data = await self.redis.get_funding_data(symbol)
            current = current_data.get('funding_rate', 0)
            
            # Получаем исторические данные
            history = await self._get_funding_history(symbol)
            
            if not history:
                return {
                    'funding_rate': current,
                    'change': 0,
                    'is_extreme': False,
                    'percentile': 50
                }
            
            # Рассчитываем статистику
            rates = [h['funding_rate'] for h in history]
            
            if not rates:
                return {'funding_rate': current, 'change': 0, 'is_extreme': False, 'percentile': 50}
            
            mean = sum(rates) / len(rates)
            percentile = self._calculate_percentile(rates, current)
            
            # Определяем экстремальность
            is_extreme = abs(current) > abs(mean) * 5
            
            # Рассчитываем изменение
            if len(history) >= 2:
                change = ((current - history[0]['funding_rate']) / abs(history[0]['funding_rate'])) * 100 if history[0]['funding_rate'] != 0 else 0
            else:
                change = 0
            
            result = {
                'funding_rate': current,
                'change': change,
                'is_extreme': is_extreme,
                'percentile': percentile,
                'mean': mean,
                'max': max(rates) if rates else 0,
                'min': min(rates) if rates else 0,
                'timestamp': datetime.now()
            }
            
            # Сохраняем анализ
            await self.redis.set_funding_analysis(symbol, result)
            
            return result
            
        except Exception as e:
            logger.error(f"Error analyzing funding for {symbol}: {e}")
            return {'funding_rate': 0, 'change': 0, 'is_extreme': False, 'percentile': 50}
    
    async def _get_funding_history(self, symbol: str) -> List[Dict]:
        """Получить историю funding"""
        try:
            # Из Redis
            history = await self.redis.get_funding_history(symbol)
            if not history:
                # Из PostgreSQL
                history = await self.postgres.get_funding_history(symbol, limit=50)
            return history
        except Exception as e:
            logger.error(f"Error getting funding history: {e}")
            return []
    
    def _calculate_percentile(self, values: List[float], current: float) -> float:
        """Рассчитать перцентиль"""
        if not values:
            return 50
        
        sorted_values = sorted(values)
        count = len(sorted_values)
        
        if current <= sorted_values[0]:
            return 0
        if current >= sorted_values[-1]:
            return 100
        
        for i, value in enumerate(sorted_values):
            if value >= current:
                return (i / count) * 100
        
        return 50
    
    async def detect_funding_anomaly(self, symbol: str) -> Dict:
        """Обнаружить аномалию в funding rate"""
        try:
            analysis = await self.analyze_funding(symbol)
            
            if analysis['is_extreme']:
                direction = 'positive' if analysis['funding_rate'] > 0 else 'negative'
                
                return {
                    'detected': True,
                    'direction': direction,
                    'funding_rate': analysis['funding_rate'],
                    'percentile': analysis['percentile'],
                    'mean': analysis['mean'],
                    'timestamp': datetime.now()
                }
            
            return {'detected': False}
            
        except Exception as e:
            logger.error(f"Error detecting funding anomaly: {e}")
            return {'detected': False}