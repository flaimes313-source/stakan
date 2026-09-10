"""
In-memory storage для работы без Redis на хостинге
"""
import json
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from collections import deque
from app.utils.logger import logger

class MemoryStorage:
    """In-memory замена Redis"""
    
    def __init__(self):
        # Хранилища
        self._data: Dict[str, Any] = {}
        self._trades: Dict[str, deque] = {}
        self._orderbooks: Dict[str, Dict] = {}
        self._expiry: Dict[str, datetime] = {}
        
        # Лимиты
        self.max_trades_per_symbol = 1000
        self.default_ttl = 3600
        
        logger.info("✅ MemoryStorage initialized (Redis replacement)")
    
    def _cleanup_expired(self):
        """Очистка истёкших ключей"""
        now = datetime.now()
        expired = [k for k, exp in self._expiry.items() if exp < now]
        for k in expired:
            self._data.pop(k, None)
            self._expiry.pop(k, None)
    
    def _set_with_ttl(self, key: str, value: Any, ttl: int = None):
        """Установить значение с TTL"""
        self._data[key] = value
        if ttl:
            self._expiry[key] = datetime.now() + timedelta(seconds=ttl)
    
    def _get(self, key: str) -> Optional[Any]:
        """Получить значение"""
        self._cleanup_expired()
        if key in self._expiry and self._expiry[key] < datetime.now():
            self._data.pop(key, None)
            self._expiry.pop(key, None)
            return None
        return self._data.get(key)
    
    # === СИМВОЛЫ ===
    async def get_active_symbols(self) -> List[str]:
        return list(self._data.get('active_symbols', set()))
    
    async def set_active_symbols(self, symbols: List[str]):
        self._data['active_symbols'] = set(symbols)
    
    # === ORDERBOOK ===
    async def set_orderbook(self, symbol: str, orderbook):
        try:
            data = {
                'symbol': symbol,
                'bids': [(b.price, b.size) for b in orderbook.bids[:20]],
                'asks': [(a.price, a.size) for a in orderbook.asks[:20]],
                'timestamp': orderbook.timestamp.isoformat()
            }
            self._set_with_ttl(f"orderbook:{symbol}", data, 60)
        except Exception as e:
            logger.error(f"Error setting orderbook: {e}")
    
    async def get_orderbook(self, symbol: str) -> Optional[Dict]:
        return self._get(f"orderbook:{symbol}")
    
    # === СДЕЛКИ ===
    async def add_trade(self, symbol: str, trade: Dict):
        try:
            if symbol not in self._trades:
                self._trades[symbol] = deque(maxlen=self.max_trades_per_symbol)
            
            self._trades[symbol].append({
                'price': trade['price'],
                'size': trade['size'],
                'side': trade['side'],
                'timestamp': trade['timestamp'].isoformat() if isinstance(trade['timestamp'], datetime) else trade['timestamp'],
                'notional': trade['notional']
            })
        except Exception as e:
            logger.error(f"Error adding trade: {e}")
    
    async def get_recent_trades(self, symbol: str, minutes: int = 5) -> List[Dict]:
        try:
            if symbol not in self._trades:
                return []
            
            cutoff = datetime.now() - timedelta(minutes=minutes)
            result = []
            
            for item in self._trades[symbol]:
                try:
                    trade_time = datetime.fromisoformat(item['timestamp']) if isinstance(item['timestamp'], str) else item['timestamp']
                    if trade_time >= cutoff:
                        result.append(item)
                except:
                    continue
            
            return result
        except Exception as e:
            logger.error(f"Error getting trades: {e}")
            return []
    
    # === MEDIAN SIZES ===
    async def set_median_trade_size(self, symbol: str, size: float):
        self._set_with_ttl(f"median_size:{symbol}", size, 600)
    
    async def get_median_trade_size(self, symbol: str) -> float:
        return self._get(f"median_size:{symbol}") or 0
    
    async def set_median_order_size(self, symbol: str, size: float):
        self._set_with_ttl(f"median_order_size:{symbol}", size, 600)
    
    async def get_median_order_size(self, symbol: str) -> float:
        return self._get(f"median_order_size:{symbol}") or 0
    
    # === CVD ===
    async def set_cvd(self, symbol: str, cvd: float):
        self._set_with_ttl(f"cvd:{symbol}", cvd, 3600)
    
    async def get_cvd(self, symbol: str) -> float:
        return self._get(f"cvd:{symbol}") or 0
    
    async def add_cvd_history(self, symbol: str, cvd: float):
        key = f"cvd_history:{symbol}"
        if key not in self._data:
            self._data[key] = deque(maxlen=100)
        self._data[key].append({'cvd': cvd, 'timestamp': datetime.now().isoformat()})
    
    async def get_cvd_history(self, symbol: str, limit: int = 20) -> List[Dict]:
        key = f"cvd_history:{symbol}"
        data = self._data.get(key, deque())
        return list(data)[-limit:]
    
    # === DELTA ===
    async def set_delta(self, symbol: str, delta: float):
        self._set_with_ttl(f"delta:{symbol}", delta, 300)
    
    async def get_delta(self, symbol: str) -> float:
        return self._get(f"delta:{symbol}") or 0
    
    # === IMBALANCE ===
    async def set_imbalance(self, symbol: str, imbalance: float):
        self._set_with_ttl(f"imbalance:{symbol}", imbalance, 60)
    
    async def get_imbalance(self, symbol: str) -> float:
        return self._get(f"imbalance:{symbol}") or 0
    
    async def save_imbalance_history(self, symbol: str, data: Dict):
        key = f"imbalance_history:{symbol}"
        if key not in self._data:
            self._data[key] = deque(maxlen=100)
        self._data[key].append(data)
    
    # === LEVELS ===
    async def set_levels(self, symbol: str, levels: List[Dict]):
        try:
            self._set_with_ttl(f"levels:{symbol}", levels, 3600)
        except Exception as e:
            logger.error(f"Error setting levels: {e}")
    
    async def get_levels(self, symbol: str) -> List[Dict]:
        return self._get(f"levels:{symbol}") or []
    
    # === OI ===
    async def set_oi_data(self, symbol: str, data: Dict):
        self._set_with_ttl(f"oi:{symbol}", data, 300)
    
    async def get_oi_data(self, symbol: str) -> Dict:
        return self._get(f"oi:{symbol}") or {'oi': 0, 'change': 0}
    
    async def get_oi_change(self, symbol: str, minutes: int = 5) -> float:
        return 0
    
    async def get_oi_history(self, symbol: str) -> List[Dict]:
        return []
    
    async def set_oi_analysis(self, symbol: str, data: Dict):
        self._set_with_ttl(f"oi_analysis:{symbol}", data, 300)
    
    # === FUNDING ===
    async def set_funding_data(self, symbol: str, data: Dict):
        self._set_with_ttl(f"funding:{symbol}", data, 600)
    
    async def get_funding_data(self, symbol: str) -> Dict:
        return self._get(f"funding:{symbol}") or {'funding_rate': 0}
    
    async def get_funding_history(self, symbol: str) -> List[Dict]:
        return []
    
    async def set_funding_analysis(self, symbol: str, data: Dict):
        self._set_with_ttl(f"funding_analysis:{symbol}", data, 600)
    
    # === VOLUME ===
    async def update_volume_stats(self, symbol: str, buy_volume: float, sell_volume: float):
        try:
            data = {
                'buy': buy_volume,
                'sell': sell_volume,
                'timestamp': datetime.now().isoformat()
            }
            self._set_with_ttl(f"volume:{symbol}", data, 60)
        except Exception as e:
            logger.error(f"Error updating volume stats: {e}")
    
    async def get_volume_stats(self, symbol: str) -> Dict:
        return self._get(f"volume:{symbol}") or {'buy': 0, 'sell': 0}
    
    async def set_volume_analysis(self, symbol: str, data: Dict):
        self._set_with_ttl(f"volume_analysis:{symbol}", data, 300)
    
    async def get_average_volume(self, symbol: str) -> float:
        return 0
    
    async def set_average_volume(self, symbol: str, volume: float):
        self._set_with_ttl(f"avg_volume:{symbol}", volume, 3600)
    
    # === SIGNALS ===
    async def save_signal(self, symbol: str, signal: Dict):
        try:
            self._set_with_ttl(f"signal:{symbol}", signal, 3600)
        except Exception as e:
            logger.error(f"Error saving signal: {e}")
    
    async def get_active_signals(self) -> Dict:
        try:
            self._cleanup_expired()
            signals = {}
            for key, value in self._data.items():
                if key.startswith('signal:'):
                    symbol = key.split(':', 1)[1]
                    signals[symbol] = value
            return signals
        except:
            return {}
    
    async def get_signal_memory(self, key: str) -> Optional[Dict]:
        return self._get(f"signal_memory:{key}")
    
    async def set_signal_memory(self, key: str, data: Dict):
        self._set_with_ttl(f"signal_memory:{key}", data, 3600)
    
    # === PRICE ===
    async def get_current_price(self, symbol: str) -> Optional[float]:
        try:
            trades = await self.get_recent_trades(symbol, minutes=1)
            if trades:
                return trades[-1]['price']
            return None
        except:
            return None
    
    async def set_current_score(self, symbol: str, score: int):
        self._set_with_ttl(f"score:{symbol}", score, 60)
    
    async def get_current_score(self, symbol: str) -> Optional[int]:
        return self._get(f"score:{symbol}")
    
    # === LIQUIDITY ===
    async def set_liquidity_analysis(self, symbol: str, data: Dict):
        self._set_with_ttl(f"liquidity:{symbol}", data, 60)
    
    # === AGGRESSION ===
    async def set_aggression(self, symbol: str, data: Dict):
        self._set_with_ttl(f"aggression:{symbol}", data, 60)
    
    async def get_aggression(self, symbol: str) -> Optional[Dict]:
        return self._get(f"aggression:{symbol}")
    
    # === LARGE ORDERS ===
    async def save_large_order(self, key: str, data: Dict):
        try:
            # Убираем deque для сериализации
            serializable_data = {k: v for k, v in data.items() if k != 'history'}
            self._set_with_ttl(f"order_track:{key}", serializable_data, 3600)
        except Exception as e:
            logger.error(f"Error saving large order: {e}")
    
    async def delete_key(self, key: str):
        try:
            self._data.pop(key, None)
            self._expiry.pop(key, None)
        except Exception as e:
            logger.error(f"Error deleting key: {e}")