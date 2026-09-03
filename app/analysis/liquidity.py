from typing import Dict, List, Optional
from datetime import datetime, timedelta
from app.storage.redis import RedisStorage
from app.utils.logger import logger

class LiquidityAnalyzer:
    """Анализ ликвидности"""
    
    def __init__(self, redis: RedisStorage):
        self.redis = redis
        
    async def analyze_liquidity(self, symbol: str, orderbook: Dict) -> Dict:
        """Анализировать ликвидность в стакане"""
        try:
            bids = orderbook.get('bids', [])
            asks = orderbook.get('asks', [])
            
            if not bids or not asks:
                return {
                    'total_bid_liquidity': 0,
                    'total_ask_liquidity': 0,
                    'total_liquidity': 0,
                    'liquidity_concentration': 0
                }
            
            # Общая ликвидность
            total_bid = sum(b[1] for b in bids[:20])
            total_ask = sum(a[1] for a in asks[:20])
            total_liquidity = total_bid + total_ask
            
            # Концентрация ликвидности (сколько в первых 5 уровнях)
            top_5_bid = sum(b[1] for b in bids[:5])
            top_5_ask = sum(a[1] for a in asks[:5])
            top_5_total = top_5_bid + top_5_ask
            
            concentration = top_5_total / total_liquidity if total_liquidity > 0 else 0
            
            # Находим зоны ликвидности
            zones = await self._find_liquidity_zones(bids, asks)
            
            # Находим крупные заявки
            large_orders = await self._find_large_orders(symbol, bids, asks)
            
            result = {
                'total_bid_liquidity': total_bid,
                'total_ask_liquidity': total_ask,
                'total_liquidity': total_liquidity,
                'liquidity_concentration': concentration,
                'zones': zones,
                'large_orders': large_orders,
                'timestamp': datetime.now()
            }
            
            # Сохраняем в Redis
            await self.redis.set_liquidity_analysis(symbol, result)
            
            return result
            
        except Exception as e:
            logger.error(f"Error analyzing liquidity for {symbol}: {e}")
            return {
                'total_bid_liquidity': 0,
                'total_ask_liquidity': 0,
                'total_liquidity': 0,
                'liquidity_concentration': 0
            }
    
    async def _find_liquidity_zones(self, bids: List, asks: List) -> List[Dict]:
        """Найти зоны ликвидности"""
        zones = []
        
        # Группируем заявки по цене
        def group_orders(orders, side):
            if not orders:
                return []
            
            grouped = []
            current_group = {
                'side': side,
                'min_price': orders[0][0],
                'max_price': orders[0][0],
                'total_size': 0,
                'orders': []
            }
            
            for price, size in orders[:20]:
                if price - current_group['max_price'] <= 2:  # Группируем близкие цены
                    current_group['max_price'] = price
                    current_group['total_size'] += size
                    current_group['orders'].append({'price': price, 'size': size})
                else:
                    if current_group['total_size'] > 0:
                        grouped.append(current_group)
                    current_group = {
                        'side': side,
                        'min_price': price,
                        'max_price': price,
                        'total_size': size,
                        'orders': [{'price': price, 'size': size}]
                    }
            
            if current_group['total_size'] > 0:
                grouped.append(current_group)
            
            return grouped
        
        zones.extend(group_orders(bids, 'bid'))
        zones.extend(group_orders(asks, 'ask'))
        
        # Сортируем по размеру
        zones.sort(key=lambda x: x['total_size'], reverse=True)
        
        return zones[:5]  # Топ 5 зон
    
    async def _find_large_orders(self, symbol: str, bids: List, asks: List) -> List[Dict]:
        """Найти крупные заявки"""
        large_orders = []
        
        # Получаем медианный размер
        median_size = await self.redis.get_median_order_size(symbol)
        if median_size == 0:
            return large_orders
        
        # Проверяем заявки
        for side, orders in [('bid', bids), ('ask', asks)]:
            for price, size in orders[:20]:
                ratio = size / median_size if median_size > 0 else 0
                
                if ratio >= 3:  # Крупная заявка
                    large_orders.append({
                        'side': side,
                        'price': price,
                        'size': size,
                        'ratio': ratio,
                        'category': self._get_category(ratio)
                    })
        
        return large_orders
    
    def _get_category(self, ratio: float) -> str:
        """Определить категорию заявки по размеру"""
        if ratio >= 10:
            return 'extreme'
        elif ratio >= 5:
            return 'very_large'
        elif ratio >= 3:
            return 'large'
        return 'normal'