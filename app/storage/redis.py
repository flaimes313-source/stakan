import json
import redis.asyncio as redis
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from app.config import config
from app.utils.logger import logger

class RedisStorage:
    def __init__(self):
        self.redis = None
        self._connect()
    
    def _connect(self):
        """Connect to Redis"""
        try:
            self.redis = redis.Redis(
                host=config.REDIS_HOST,
                port=config.REDIS_PORT,
                db=config.REDIS_DB,
                password=config.REDIS_PASSWORD,
                decode_responses=True
            )
            logger.info("Connected to Redis")
        except Exception as e:
            logger.error(f"Redis connection error: {e}")
    
    # ============ EXISTING METHODS (kept) ============
    
    async def get_active_symbols(self) -> List[str]:
        """Get list of active symbols"""
        try:
            symbols = await self.redis.smembers('active_symbols')
            return list(symbols)
        except Exception as e:
            logger.error(f"Error getting active symbols: {e}")
            return []
    
    async def set_active_symbols(self, symbols: List[str]):
        """Set active symbols"""
        try:
            await self.redis.delete('active_symbols')
            if symbols:
                await self.redis.sadd('active_symbols', *symbols)
        except Exception as e:
            logger.error(f"Error setting active symbols: {e}")
    
    async def set_orderbook(self, symbol: str, orderbook):
        """Store orderbook in Redis"""
        try:
            key = f"orderbook:{symbol}"
            data = {
                'symbol': symbol,
                'bids': [(b.price, b.size) for b in orderbook.bids[:20]],
                'asks': [(a.price, a.size) for a in orderbook.asks[:20]],
                'timestamp': orderbook.timestamp.isoformat()
            }
            await self.redis.setex(key, 60, json.dumps(data))
        except Exception as e:
            logger.error(f"Error storing orderbook: {e}")
    
    async def get_orderbook(self, symbol: str) -> Optional[Dict]:
        """Get orderbook from Redis"""
        try:
            key = f"orderbook:{symbol}"
            data = await self.redis.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.error(f"Error getting orderbook: {e}")
            return None
    
    async def add_trade(self, symbol: str, trade: Dict):
        """Add trade to history"""
        try:
            key = f"trades:{symbol}"
            data = {
                'price': trade['price'],
                'size': trade['size'],
                'side': trade['side'],
                'timestamp': trade['timestamp'].isoformat() if isinstance(trade['timestamp'], datetime) else trade['timestamp'],
                'notional': trade['notional']
            }
            await self.redis.lpush(key, json.dumps(data))
            await self.redis.ltrim(key, 0, 999)
            await self.redis.expire(key, 1800)
        except Exception as e:
            logger.error(f"Error adding trade: {e}")
    
    async def get_recent_trades(self, symbol: str, minutes: int = 5) -> List[Dict]:
        """Get recent trades"""
        try:
            key = f"trades:{symbol}"
            trades_data = await self.redis.lrange(key, 0, -1)
            trades = []
            cutoff = datetime.now() - timedelta(minutes=minutes)
            
            for item in trades_data:
                try:
                    trade = json.loads(item)
                    trade_time = datetime.fromisoformat(trade['timestamp']) if isinstance(trade['timestamp'], str) else trade['timestamp']
                    if trade_time >= cutoff:
                        trades.append(trade)
                except:
                    continue
            
            return trades
        except Exception as e:
            logger.error(f"Error getting trades: {e}")
            return []
    
    async def set_median_trade_size(self, symbol: str, size: float):
        """Set median trade size"""
        try:
            key = f"median_size:{symbol}"
            await self.redis.setex(key, 600, str(size))
        except Exception as e:
            logger.error(f"Error setting median size: {e}")
    
    async def get_median_trade_size(self, symbol: str) -> float:
        """Get median trade size"""
        try:
            key = f"median_size:{symbol}"
            value = await self.redis.get(key)
            return float(value) if value else 0
        except:
            return 0
    
    async def set_median_order_size(self, symbol: str, size: float):
        """Set median order size"""
        try:
            key = f"median_order_size:{symbol}"
            await self.redis.setex(key, 600, str(size))
        except Exception as e:
            logger.error(f"Error setting median order size: {e}")
    
    async def get_median_order_size(self, symbol: str) -> float:
        """Get median order size"""
        try:
            key = f"median_order_size:{symbol}"
            value = await self.redis.get(key)
            return float(value) if value else 0
        except:
            return 0
    
    # ============ NEW CVD METHODS ============
    
    async def set_cvd(self, symbol: str, cvd: float):
        """Set Cumulative Volume Delta"""
        try:
            key = f"cvd:{symbol}"
            await self.redis.setex(key, 3600, str(cvd))
        except Exception as e:
            logger.error(f"Error setting CVD: {e}")
    
    async def get_cvd(self, symbol: str) -> float:
        """Get Cumulative Volume Delta"""
        try:
            key = f"cvd:{symbol}"
            value = await self.redis.get(key)
            return float(value) if value else 0
        except:
            return 0
    
    async def add_cvd_history(self, symbol: str, cvd: float):
        """Add CVD to history"""
        try:
            key = f"cvd_history:{symbol}"
            data = {'cvd': cvd, 'timestamp': datetime.now().isoformat()}
            await self.redis.lpush(key, json.dumps(data))
            await self.redis.ltrim(key, 0, 99)
            await self.redis.expire(key, 86400)  # 24 hours
        except Exception as e:
            logger.error(f"Error adding CVD history: {e}")
    
    async def get_cvd_history(self, symbol: str, limit: int = 20) -> List[Dict]:
        """Get CVD history"""
        try:
            key = f"cvd_history:{symbol}"
            data = await self.redis.lrange(key, 0, limit - 1)
            return [json.loads(item) for item in data]
        except Exception as e:
            logger.error(f"Error getting CVD history: {e}")
            return []
    
    # ============ NEW SIGNAL METHODS ============
    
    async def get_signal_memory(self, key: str) -> Optional[Dict]:
        """Get signal from memory"""
        try:
            data = await self.redis.get(f"signal_memory:{key}")
            return json.loads(data) if data else None
        except:
            return None
    
    async def set_signal_memory(self, key: str, data: Dict):
        """Set signal in memory"""
        try:
            await self.redis.setex(f"signal_memory:{key}", 3600, json.dumps(data))
        except Exception as e:
            logger.error(f"Error setting signal memory: {e}")
    
    async def get_delta(self, symbol: str) -> float:
        """Get delta"""
        try:
            key = f"delta:{symbol}"
            value = await self.redis.get(key)
            return float(value) if value else 0
        except:
            return 0
    
    async def set_delta(self, symbol: str, delta: float):
        """Set delta"""
        try:
            await self.redis.setex(f"delta:{symbol}", 300, str(delta))
        except Exception as e:
            logger.error(f"Error setting delta: {e}")
    
    async def set_imbalance(self, symbol: str, imbalance: float):
        """Set imbalance"""
        try:
            await self.redis.setex(f"imbalance:{symbol}", 60, str(imbalance))
        except Exception as e:
            logger.error(f"Error setting imbalance: {e}")
    
    async def get_imbalance(self, symbol: str) -> float:
        """Get imbalance"""
        try:
            value = await self.redis.get(f"imbalance:{symbol}")
            return float(value) if value else 0
        except:
            return 0
    
    async def set_levels(self, symbol: str, levels: List[Dict]):
        """Set levels"""
        try:
            await self.redis.setex(f"levels:{symbol}", 3600, json.dumps(levels))
        except Exception as e:
            logger.error(f"Error setting levels: {e}")
    
    async def get_levels(self, symbol: str) -> List[Dict]:
        """Get levels"""
        try:
            data = await self.redis.get(f"levels:{symbol}")
            return json.loads(data) if data else []
        except:
            return []
    
    async def set_oi_data(self, symbol: str, data: Dict):
        """Set OI data"""
        try:
            await self.redis.setex(f"oi:{symbol}", 300, json.dumps(data))
        except Exception as e:
            logger.error(f"Error setting OI data: {e}")
    
    async def get_oi_data(self, symbol: str) -> Dict:
        """Get OI data"""
        try:
            data = await self.redis.get(f"oi:{symbol}")
            return json.loads(data) if data else {'oi': 0, 'change': 0}
        except:
            return {'oi': 0, 'change': 0}
    
    async def set_funding_data(self, symbol: str, data: Dict):
        """Set funding data"""
        try:
            await self.redis.setex(f"funding:{symbol}", 600, json.dumps(data))
        except Exception as e:
            logger.error(f"Error setting funding data: {e}")
    
    async def get_funding_data(self, symbol: str) -> Dict:
        """Get funding data"""
        try:
            data = await self.redis.get(f"funding:{symbol}")
            return json.loads(data) if data else {'funding_rate': 0}
        except:
            return {'funding_rate': 0}
    
    async def update_volume_stats(self, symbol: str, buy_volume: float, sell_volume: float):
        """Update volume stats"""
        try:
            data = {'buy': buy_volume, 'sell': sell_volume, 'timestamp': datetime.now().isoformat()}
            await self.redis.setex(f"volume:{symbol}", 60, json.dumps(data))
        except Exception as e:
            logger.error(f"Error updating volume stats: {e}")
    
    async def get_volume_stats(self, symbol: str) -> Dict:
        """Get volume stats"""
        try:
            data = await self.redis.get(f"volume:{symbol}")
            return json.loads(data) if data else {'buy': 0, 'sell': 0}
        except:
            return {'buy': 0, 'sell': 0}
    
    async def save_signal(self, symbol: str, signal: Dict):
        """Save signal"""
        try:
            await self.redis.setex(f"signal:{symbol}", 3600, json.dumps(signal))
        except Exception as e:
            logger.error(f"Error saving signal: {e}")
    
    async def get_active_signals(self) -> Dict:
        """Get active signals"""
        try:
            keys = await self.redis.keys('signal:*')
            signals = {}
            for key in keys:
                data = await self.redis.get(key)
                if data:
                    signal = json.loads(data)
                    symbol = key.split(':')[1]
                    signals[symbol] = signal
            return signals
        except:
            return {}
    
    async def get_current_price(self, symbol: str) -> Optional[float]:
        """Get current price"""
        try:
            trades = await self.get_recent_trades(symbol, minutes=1)
            if trades:
                return trades[-1]['price']
            return None
        except:
            return None
    
    async def set_current_score(self, symbol: str, score: int):
        """Set current score"""
        try:
            await self.redis.setex(f"score:{symbol}", 60, str(score))
        except Exception as e:
            logger.error(f"Error setting score: {e}")
    
    async def get_current_score(self, symbol: str) -> Optional[int]:
        """Get current score"""
        try:
            value = await self.redis.get(f"score:{symbol}")
            return int(value) if value else None
        except:
            return None
    
    async def get_oi_change(self, symbol: str, minutes: int = 5) -> float:
        """Get OI change"""
        try:
            key = f"oi_change:{symbol}:{minutes}"
            value = await self.redis.get(key)
            return float(value) if value else 0
        except:
            return 0
    
    async def save_large_order(self, key: str, data: Dict):
        """Save large order"""
        try:
            await self.redis.setex(f"order_track:{key}", 3600, json.dumps(data))
        except Exception as e:
            logger.error(f"Error saving large order: {e}")
    
    async def delete_key(self, key: str):
        """Delete key"""
        try:
            await self.redis.delete(key)
        except Exception as e:
            logger.error(f"Error deleting key: {e}")