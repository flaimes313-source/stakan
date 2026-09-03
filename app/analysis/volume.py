from typing import Dict, List, Optional
from datetime import datetime, timedelta
from app.storage.redis import RedisStorage
from app.utils.logger import logger

class VolumeAnalyzer:
    """Анализ объема"""
    
    def __init__(self, redis: RedisStorage):
        self.redis = redis
        
    async def analyze_volume(self, symbol: str, trades: List[Dict]) -> Dict:
        """Анализировать объем торгов"""
        try:
            if not trades:
                return {
                    'buy_volume': 0,
                    'sell_volume': 0,
                    'total_volume': 0,
                    'volume_ratio': 0,
                    'is_high': False
                }
            
            # Рассчитываем объемы
            buy_volume = sum(t['notional'] for t in trades if t['side'] == 'Buy')
            sell_volume = sum(t['notional'] for t in trades if t['side'] == 'Sell')
            total_volume = buy_volume + sell_volume
            
            # Получаем средний объем
            avg_volume = await self._get_average_volume(symbol)
            
            # Рассчитываем соотношение
            volume_ratio = total_volume / avg_volume if avg_volume > 0 else 1
            
            # Определяем, высокий ли объем
            is_high = volume_ratio > 2.0
            
            result = {
                'buy_volume': buy_volume,
                'sell_volume': sell_volume,
                'total_volume': total_volume,
                'volume_ratio': volume_ratio,
                'is_high': is_high,
                'avg_volume': avg_volume,
                'timestamp': datetime.now()
            }
            
            # Сохраняем в Redis
            await self.redis.set_volume_analysis(symbol, result)
            
            return result
            
        except Exception as e:
            logger.error(f"Error analyzing volume for {symbol}: {e}")
            return {
                'buy_volume': 0,
                'sell_volume': 0,
                'total_volume': 0,
                'volume_ratio': 0,
                'is_high': False
            }
    
    async def _get_average_volume(self, symbol: str) -> float:
        """Получить средний объем за 24 часа"""
        try:
            # Из Redis
            avg = await self.redis.get_average_volume(symbol)
            if avg:
                return avg
            
            # Из PostgreSQL
            avg = await self.postgres.get_average_volume(symbol)
            if avg:
                await self.redis.set_average_volume(symbol, avg)
                return avg
            
            return 0
            
        except Exception as e:
            logger.error(f"Error getting average volume: {e}")
            return 0
    
    async def detect_volume_spike(self, symbol: str, trades: List[Dict]) -> Dict:
        """Обнаружить всплеск объема"""
        try:
            analysis = await self.analyze_volume(symbol, trades)
            
            if analysis['is_high']:
                # Определяем направление всплеска
                if analysis['buy_volume'] > analysis['sell_volume'] * 2:
                    direction = 'buy'
                elif analysis['sell_volume'] > analysis['buy_volume'] * 2:
                    direction = 'sell'
                else:
                    direction = 'neutral'
                
                return {
                    'detected': True,
                    'direction': direction,
                    'volume_ratio': analysis['volume_ratio'],
                    'total_volume': analysis['total_volume'],
                    'timestamp': datetime.now()
                }
            
            return {'detected': False}
            
        except Exception as e:
            logger.error(f"Error detecting volume spike: {e}")
            return {'detected': False}
    
    async def calculate_vwap(self, trades: List[Dict]) -> float:
        """Рассчитать VWAP (Volume Weighted Average Price)"""
        try:
            if not trades:
                return 0
            
            total_value = sum(t['price'] * t['size'] for t in trades)
            total_volume = sum(t['size'] for t in trades)
            
            return total_value / total_volume if total_volume > 0 else 0
            
        except Exception as e:
            logger.error(f"Error calculating VWAP: {e}")
            return 0