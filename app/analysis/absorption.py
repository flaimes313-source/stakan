import asyncio
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from collections import deque
from app.storage.redis import RedisStorage
from app.utils.logger import logger

class AbsorptionDetector:
    def __init__(self, redis: RedisStorage):
        self.redis = redis
        self.absorption_data: Dict[str, Dict] = {}
        self.window = 10  # seconds
        
    async def detect_absorption(self, symbol: str) -> Dict:
        """Detect absorption patterns"""
        try:
            # Get recent trades
            trades = await self.redis.get_recent_trades(symbol, minutes=1)
            if not trades:
                return {'detected': False}
            
            # Get current orderbook
            orderbook = await self.redis.get_orderbook(symbol)
            if not orderbook:
                return {'detected': False}
            
            # Check for absorption patterns
            seller_absorption = await self._check_seller_absorption(symbol, trades, orderbook)
            buyer_absorption = await self._check_buyer_absorption(symbol, trades, orderbook)
            
            if seller_absorption:
                return {
                    'detected': True,
                    'type': 'SELLER_ABSORPTION',
                    'details': seller_absorption,
                    'timestamp': datetime.now()
                }
            elif buyer_absorption:
                return {
                    'detected': True,
                    'type': 'BUYER_ABSORPTION',
                    'details': buyer_absorption,
                    'timestamp': datetime.now()
                }
            
            return {'detected': False}
            
        except Exception as e:
            logger.error(f"Error detecting absorption for {symbol}: {e}")
            return {'detected': False}
    
    async def _check_seller_absorption(self, symbol: str, trades: List[Dict], orderbook: Dict) -> Optional[Dict]:
        """Check for seller absorption pattern"""
        try:
            # Get recent price movement
            price_change = await self._get_price_change(symbol, window=15)
            
            # Calculate aggressive buy volume
            buy_volume = sum(
                t['notional'] for t in trades 
                if t['side'] == 'Buy' and t['notional'] > await self._get_median_volume(symbol) * 2
            )
            
            # Check if price is near ask side
            best_ask = orderbook['asks'][0]['price'] if orderbook['asks'] else 0
            current_price = await self.redis.get_current_price(symbol)
            
            if not current_price:
                return None
            
            price_distance = (best_ask - current_price) / current_price if best_ask else 0
            
            if price_distance < 0.001:  # Within 0.1% of ask
                # Check if price didn't move much despite buys
                if abs(price_change) < 0.001:  # Less than 0.1% move
                    # Check if ask liquidity is being replenished
                    ask_volume = sum(a['size'] for a in orderbook['asks'][:5])
                    
                    # Check OI change
                    oi_change = await self.redis.get_oi_change(symbol, minutes=5)
                    
                    if buy_volume > 100000 and ask_volume > 100000:
                        return {
                            'buy_volume': buy_volume,
                            'ask_volume': ask_volume,
                            'price_change': price_change,
                            'oi_change': oi_change,
                            'confidence': min((buy_volume / ask_volume) * 100, 100)
                        }
            
            return None
            
        except Exception as e:
            logger.error(f"Error checking seller absorption: {e}")
            return None
    
    async def _check_buyer_absorption(self, symbol: str, trades: List[Dict], orderbook: Dict) -> Optional[Dict]:
        """Check for buyer absorption pattern"""
        try:
            # Get recent price movement
            price_change = await self._get_price_change(symbol, window=15)
            
            # Calculate aggressive sell volume
            sell_volume = sum(
                t['notional'] for t in trades 
                if t['side'] == 'Sell' and t['notional'] > await self._get_median_volume(symbol) * 2
            )
            
            # Check if price is near bid side
            best_bid = orderbook['bids'][0]['price'] if orderbook['bids'] else 0
            current_price = await self.redis.get_current_price(symbol)
            
            if not current_price:
                return None
            
            price_distance = (current_price - best_bid) / current_price if best_bid else 0
            
            if price_distance < 0.001:  # Within 0.1% of bid
                if abs(price_change) < 0.001:  # Price not falling
                    bid_volume = sum(b['size'] for b in orderbook['bids'][:5])
                    oi_change = await self.redis.get_oi_change(symbol, minutes=5)
                    
                    if sell_volume > 100000 and bid_volume > 100000:
                        return {
                            'sell_volume': sell_volume,
                            'bid_volume': bid_volume,
                            'price_change': price_change,
                            'oi_change': oi_change,
                            'confidence': min((sell_volume / bid_volume) * 100, 100)
                        }
            
            return None
            
        except Exception as e:
            logger.error(f"Error checking buyer absorption: {e}")
            return None
    
    async def _get_price_change(self, symbol: str, window: int = 15) -> float:
        """Get price change over specified window"""
        try:
            trades = await self.redis.get_recent_trades(symbol, minutes=1)
            if not trades or len(trades) < 2:
                return 0
            
            # Get prices at start and end of window
            start_time = datetime.now() - timedelta(seconds=window)
            valid_trades = [t for t in trades if t['timestamp'] >= start_time]
            
            if len(valid_trades) < 2:
                return 0
            
            first_price = valid_trades[0]['price']
            last_price = valid_trades[-1]['price']
            
            return (last_price - first_price) / first_price if first_price else 0
            
        except Exception as e:
            logger.error(f"Error getting price change: {e}")
            return 0
    
    async def _get_median_volume(self, symbol: str) -> float:
        """Get median trade volume"""
        try:
            return await self.redis.get_median_trade_size(symbol) or 0
        except:
            return 0