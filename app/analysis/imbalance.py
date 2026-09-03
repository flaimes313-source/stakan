import asyncio
from typing import Dict, List, Optional
from datetime import datetime
from app.storage.redis import RedisStorage
from app.utils.logger import logger

class ImbalanceAnalyzer:
    """Анализ дисбаланса Bid/Ask"""
    
    def __init__(self, redis: RedisStorage):
        self.redis = redis
        
    async def calculate_imbalance(self, symbol: str, orderbook: Dict) -> Dict:
        """Рассчитать дисбаланс между Bid и Ask"""
        try:
            bids = orderbook.get('bids', [])
            asks = orderbook.get('asks', [])
            
            if not bids or not asks:
                return {'imbalance': 0, 'level': 'neutral'}
            
            # Рассчитываем объем на первых 20 уровнях
            bid_volume = sum(b[1] for b in bids[:20])
            ask_volume = sum(a[1] for a in asks[:20])
            
            total_volume = bid_volume + ask_volume
            if total_volume == 0:
                return {'imbalance': 0, 'level': 'neutral'}
            
            # Дисбаланс в процентах
            imbalance = ((bid_volume - ask_volume) / total_volume) * 100
            
            # Определяем уровень дисбаланса
            if imbalance > 30:
                level = 'strong_buy'
            elif imbalance > 15:
                level = 'moderate_buy'
            elif imbalance < -30:
                level = 'strong_sell'
            elif imbalance < -15:
                level = 'moderate_sell'
            else:
                level = 'neutral'
            
            # Сохраняем в Redis
            await self.redis.set_imbalance(symbol, imbalance)
            
            return {
                'imbalance': imbalance,
                'level': level,
                'bid_volume': bid_volume,
                'ask_volume': ask_volume,
                'timestamp': datetime.now()
            }
            
        except Exception as e:
            logger.error(f"Error calculating imbalance for {symbol}: {e}")
            return {'imbalance': 0, 'level': 'neutral'}
    
    async def calculate_weighted_imbalance(self, symbol: str, orderbook: Dict) -> float:
        """Рассчитать взвешенный дисбаланс с учетом расстояния от цены"""
        try:
            bids = orderbook.get('bids', [])
            asks = orderbook.get('asks', [])
            
            if not bids or not asks:
                return 0
            
            mid_price = (bids[0][0] + asks[0][0]) / 2
            
            weighted_bid = 0
            weighted_ask = 0
            
            # Взвешиваем объемы по расстоянию от mid price
            for price, size in bids[:20]:
                distance = abs(price - mid_price) / mid_price
                weight = 1 / (1 + distance * 100)  # Чем ближе, тем больше вес
                weighted_bid += size * weight
            
            for price, size in asks[:20]:
                distance = abs(price - mid_price) / mid_price
                weight = 1 / (1 + distance * 100)
                weighted_ask += size * weight
            
            total = weighted_bid + weighted_ask
            if total == 0:
                return 0
            
            return ((weighted_bid - weighted_ask) / total) * 100
            
        except Exception as e:
            logger.error(f"Error calculating weighted imbalance: {e}")
            return 0
    
    async def detect_imbalance_shift(self, symbol: str, orderbook: Dict) -> Dict:
        """Обнаружить резкое изменение дисбаланса"""
        try:
            current = await self.calculate_imbalance(symbol, orderbook)
            
            # Получаем предыдущее значение
            previous = await self.redis.get_imbalance(symbol)
            if previous == 0:
                return {'shift': 0, 'detected': False}
            
            shift = current['imbalance'] - previous
            
            # Сохраняем историю
            await self.redis.save_imbalance_history(symbol, {
                'imbalance': current['imbalance'],
                'shift': shift,
                'timestamp': datetime.now()
            })
            
            return {
                'shift': shift,
                'detected': abs(shift) > 20,  # Значительное изменение
                'current': current['imbalance'],
                'previous': previous
            }
            
        except Exception as e:
            logger.error(f"Error detecting imbalance shift: {e}")
            return {'shift': 0, 'detected': False}