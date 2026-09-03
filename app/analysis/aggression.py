from typing import Dict, List, Optional
from datetime import datetime, timedelta
from app.storage.redis import RedisStorage
from app.utils.logger import logger

class AggressionAnalyzer:
    """Анализ агрессивности торгов"""
    
    def __init__(self, redis: RedisStorage):
        self.redis = redis
        
    async def analyze_aggression(self, symbol: str, trades: List[Dict]) -> Dict:
        """Анализировать агрессивность торгов"""
        try:
            if not trades:
                return {
                    'aggression_score': 0,
                    'buy_aggression': 0,
                    'sell_aggression': 0,
                    'type': 'neutral'
                }
            
            # Получаем медианный размер сделки
            median_size = await self.redis.get_median_trade_size(symbol)
            if median_size == 0:
                median_size = 1
            
            # Определяем агрессивные сделки (больше 3x медианы)
            aggressive_trades = [
                t for t in trades 
                if t['size'] > median_size * 3
            ]
            
            if not aggressive_trades:
                return {
                    'aggression_score': 0,
                    'buy_aggression': 0,
                    'sell_aggression': 0,
                    'type': 'neutral'
                }
            
            # Считаем объем агрессивных покупок и продаж
            buy_aggression = sum(
                t['notional'] for t in aggressive_trades 
                if t['side'] == 'Buy'
            )
            sell_aggression = sum(
                t['notional'] for t in aggressive_trades 
                if t['side'] == 'Sell'
            )
            
            total_aggression = buy_aggression + sell_aggression
            if total_aggression == 0:
                return {
                    'aggression_score': 0,
                    'buy_aggression': 0,
                    'sell_aggression': 0,
                    'type': 'neutral'
                }
            
            # Определяем тип агрессии
            if buy_aggression > sell_aggression * 2:
                aggression_type = 'buy'
                aggression_score = (buy_aggression / total_aggression) * 100
            elif sell_aggression > buy_aggression * 2:
                aggression_type = 'sell'
                aggression_score = (sell_aggression / total_aggression) * 100
            else:
                aggression_type = 'neutral'
                aggression_score = 0
            
            # Сохраняем в Redis
            await self.redis.set_aggression(symbol, {
                'score': aggression_score,
                'type': aggression_type,
                'buy': buy_aggression,
                'sell': sell_aggression,
                'timestamp': datetime.now()
            })
            
            return {
                'aggression_score': aggression_score,
                'buy_aggression': buy_aggression,
                'sell_aggression': sell_aggression,
                'type': aggression_type,
                'count': len(aggressive_trades),
                'total_volume': total_aggression
            }
            
        except Exception as e:
            logger.error(f"Error analyzing aggression for {symbol}: {e}")
            return {
                'aggression_score': 0,
                'buy_aggression': 0,
                'sell_aggression': 0,
                'type': 'neutral'
            }
    
    async def detect_aggression_shift(self, symbol: str, trades: List[Dict]) -> Dict:
        """Обнаружить изменение агрессивности"""
        try:
            current = await self.analyze_aggression(symbol, trades)
            
            # Получаем предыдущее состояние
            previous = await self.redis.get_aggression(symbol)
            if not previous:
                return {'shift': 0, 'detected': False}
            
            shift = current['aggression_score'] - previous.get('score', 0)
            
            return {
                'shift': shift,
                'detected': abs(shift) > 20,
                'current': current,
                'previous': previous
            }
            
        except Exception as e:
            logger.error(f"Error detecting aggression shift: {e}")
            return {'shift': 0, 'detected': False}