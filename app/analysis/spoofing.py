from typing import Dict, List, Optional
from datetime import datetime, timedelta
from collections import deque
from app.storage.redis import RedisStorage
from app.utils.logger import logger

class SpoofingDetector:
    """Детектор спуфинга и резкого снятия ликвидности"""
    
    def __init__(self, redis: RedisStorage):
        self.redis = redis
        self.order_history: Dict[str, Dict] = {}
        self.spoofing_threshold = 0.7  # 70% объема снято без исполнения
        
    async def detect_spoofing(self, symbol: str, orderbook: Dict) -> Dict:
        """Обнаружить возможный спуфинг"""
        try:
            bids = orderbook.get('bids', [])
            asks = orderbook.get('asks', [])
            
            spoofing_signals = []
            
            # Проверяем Bid сторону
            for bid in bids[:10]:
                signal = await self._check_order_anomaly(
                    symbol, 'bid', bid[0], bid[1]
                )
                if signal:
                    spoofing_signals.append(signal)
            
            # Проверяем Ask сторону
            for ask in asks[:10]:
                signal = await self._check_order_anomaly(
                    symbol, 'ask', ask[0], ask[1]
                )
                if signal:
                    spoofing_signals.append(signal)
            
            if spoofing_signals:
                return {
                    'detected': True,
                    'signals': spoofing_signals,
                    'timestamp': datetime.now()
                }
            
            return {'detected': False}
            
        except Exception as e:
            logger.error(f"Error detecting spoofing for {symbol}: {e}")
            return {'detected': False}
    
    async def _check_order_anomaly(self, symbol: str, side: str, price: float, size: float) -> Optional[Dict]:
        """Проверить аномалию в заявке"""
        key = f"{symbol}:{side}:{price}"
        
        # Если заявка новая
        if key not in self.order_history:
            self.order_history[key] = {
                'first_seen': datetime.now(),
                'last_seen': datetime.now(),
                'max_size': size,
                'current_size': size,
                'history': deque(maxlen=100)
            }
            return None
        
        # Обновляем историю
        history = self.order_history[key]
        history['last_seen'] = datetime.now()
        history['current_size'] = size
        history['history'].append({
            'size': size,
            'timestamp': datetime.now()
        })
        
        # Проверяем на аномалию
        if history['max_size'] > size * 1.5:
            # Заметное уменьшение размера
            reduction = history['max_size'] - size
            reduction_ratio = reduction / history['max_size']
            
            # Проверяем, были ли сделки по этой цене
            trades = await self.redis.get_recent_trades(symbol, minutes=1)
            executed_at_price = sum(
                t['size'] for t in trades 
                if abs(t['price'] - price) / price < 0.001
            )
            
            # Если снято больше, чем исполнено
            if reduction > executed_at_price * 2 and reduction_ratio > self.spoofing_threshold:
                return {
                    'side': side,
                    'price': price,
                    'max_size': history['max_size'],
                    'current_size': size,
                    'reduction': reduction,
                    'reduction_ratio': reduction_ratio,
                    'executed': executed_at_price,
                    'type': 'possible_spoofing'
                }
        
        # Очищаем старые записи
        if (datetime.now() - history['first_seen']).total_seconds() > 3600:
            del self.order_history[key]
        
        return None
    
    async def detect_liquidity_withdrawal(self, symbol: str, orderbook: Dict) -> Dict:
        """Обнаружить резкое снятие ликвидности"""
        try:
            # Получаем предыдущий стакан
            previous = await self.redis.get_orderbook(symbol)
            if not previous:
                return {'detected': False}
            
            withdrawals = []
            
            # Проверяем Ask сторону
            current_asks = {a[0]: a[1] for a in orderbook.get('asks', [])}
            prev_asks = {a[0]: a[1] for a in previous.get('asks', [])}
            
            for price, size in prev_asks.items():
                if price not in current_asks:
                    # Заявка полностью исчезла
                    withdrawals.append({
                        'side': 'ask',
                        'price': price,
                        'removed_size': size,
                        'type': 'complete_withdrawal'
                    })
                elif current_asks[price] < size * 0.5:
                    # Заявка значительно уменьшилась
                    withdrawals.append({
                        'side': 'ask',
                        'price': price,
                        'removed_size': size - current_asks[price],
                        'type': 'partial_withdrawal'
                    })
            
            # Проверяем Bid сторону
            current_bids = {b[0]: b[1] for b in orderbook.get('bids', [])}
            prev_bids = {b[0]: b[1] for b in previous.get('bids', [])}
            
            for price, size in prev_bids.items():
                if price not in current_bids:
                    withdrawals.append({
                        'side': 'bid',
                        'price': price,
                        'removed_size': size,
                        'type': 'complete_withdrawal'
                    })
                elif current_bids[price] < size * 0.5:
                    withdrawals.append({
                        'side': 'bid',
                        'price': price,
                        'removed_size': size - current_bids[price],
                        'type': 'partial_withdrawal'
                    })
            
            if withdrawals and len(withdrawals) > 0:
                # Проверяем объем снятой ликвидности
                total_removed = sum(w['removed_size'] for w in withdrawals)
                
                # Проверяем, были ли сделки
                trades = await self.redis.get_recent_trades(symbol, seconds=10)
                trade_volume = sum(t['notional'] for t in trades)
                
                if total_removed > trade_volume * 2:
                    return {
                        'detected': True,
                        'withdrawals': withdrawals,
                        'total_removed': total_removed,
                        'trade_volume': trade_volume,
                        'timestamp': datetime.now()
                    }
            
            return {'detected': False}
            
        except Exception as e:
            logger.error(f"Error detecting liquidity withdrawal: {e}")
            return {'detected': False}