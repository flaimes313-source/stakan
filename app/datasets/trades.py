import asyncio
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from collections import deque
from app.storage.redis import RedisStorage
from app.utils.logger import logger

class TradeAnalyzer:
    def __init__(self, redis: RedisStorage):
        self.redis = redis
        self.deltas: Dict[str, float] = {}
        self.cvd: Dict[str, float] = {}
        self.trade_history: Dict[str, deque] = {}
        
    async def calculate_delta(self, symbol: str, minutes: int = 15) -> Dict:
        """Calculate cumulative delta for a symbol"""
        try:
            trades = await self.redis.get_recent_trades(symbol, minutes=minutes)
            
            buy_volume = sum(t['notional'] for t in trades if t['side'] == 'Buy')
            sell_volume = sum(t['notional'] for t in trades if t['side'] == 'Sell')
            
            delta = buy_volume - sell_volume
            self.deltas[symbol] = delta
            
            # Update CVD
            if symbol not in self.cvd:
                self.cvd[symbol] = 0
            self.cvd[symbol] += delta
            
            # Store in Redis
            await self.redis.set_delta(symbol, delta)
            await self.redis.set_cvd(symbol, self.cvd[symbol])
            
            return {
                'buy_volume': buy_volume,
                'sell_volume': sell_volume,
                'delta': delta,
                'cvd': self.cvd[symbol]
            }
            
        except Exception as e:
            logger.error(f"Error calculating delta for {symbol}: {e}")
            return {'buy_volume': 0, 'sell_volume': 0, 'delta': 0, 'cvd': 0}
    
    async def detect_aggression(self, symbol: str) -> Dict:
        """Detect aggressive trading"""
        try:
            trades = await self.redis.get_recent_trades(symbol, minutes=5)
            
            if not trades:
                return {'aggression': 0, 'type': 'neutral'}
            
            # Calculate volume-weighted price
            total_notional = sum(t['notional'] for t in trades)
            if total_notional == 0:
                return {'aggression': 0, 'type': 'neutral'}
            
            # Check for large trades (> 3x median)
            median_size = await self.redis.get_median_trade_size(symbol)
            large_trades = [t for t in trades if t['size'] > median_size * 3]
            
            if large_trades:
                # Determine if buying or selling aggression
                buy_aggression = sum(t['notional'] for t in large_trades if t['side'] == 'Buy')
                sell_aggression = sum(t['notional'] for t in large_trades if t['side'] == 'Sell')
                
                if buy_aggression > sell_aggression * 2:
                    return {'aggression': 1, 'type': 'buy', 'volume': buy_aggression}
                elif sell_aggression > buy_aggression * 2:
                    return {'aggression': -1, 'type': 'sell', 'volume': sell_aggression}
                else:
                    return {'aggression': 0, 'type': 'neutral'}
            
            return {'aggression': 0, 'type': 'neutral'}
            
        except Exception as e:
            logger.error(f"Error detecting aggression for {symbol}: {e}")
            return {'aggression': 0, 'type': 'neutral'}
    
    async def calculate_cvd(self, symbol: str) -> float:
        """Get current CVD for symbol"""
        return self.cvd.get(symbol, 0)
    
    async def update_median_trade_size(self, symbol: str):
        """Update median trade size for symbol"""
        try:
            trades = await self.redis.get_recent_trades(symbol, minutes=30)
            if trades:
                sizes = sorted([t['size'] for t in trades])
                median = sizes[len(sizes) // 2] if sizes else 0
                await self.redis.set_median_trade_size(symbol, median)
        except Exception as e:
            logger.error(f"Error updating median trade size for {symbol}: {e}")