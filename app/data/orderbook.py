import asyncio
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from collections import deque
from app.models import OrderBook, OrderBookEntry
from app.api.bybit_ws import BybitWebSocket
from app.storage.redis import RedisStorage
from app.config import config
from app.utils.logger import logger

class OrderBookManager:
    def __init__(self, websocket: BybitWebSocket, redis: RedisStorage):
        self.ws = websocket
        self.redis = redis
        self.orderbooks: Dict[str, OrderBook] = {}
        self.orderbook_history: Dict[str, deque] = {}
        self.tracking: Dict[str, Dict] = {}
        self.running = False
        self._lock = asyncio.Lock()
        
        # Register handlers
        self.ws.add_handler('orderbook', self._handle_orderbook_update)
        self.ws.add_handler('trade', self._handle_trade)
    
    async def _handle_orderbook_update(self, symbol: str, data: Dict):
        """Process orderbook update from WebSocket"""
        try:
            if 'data' in data and data['data']:
                orderbook_data = data['data']
                
                # Parse bids and asks
                bids = [
                    OrderBookEntry(
                        price=float(entry[0]),
                        size=float(entry[1]),
                        is_bid=True
                    )
                    for entry in orderbook_data.get('b', [])[:50]  # Top 50 levels
                ]
                
                asks = [
                    OrderBookEntry(
                        price=float(entry[0]),
                        size=float(entry[1]),
                        is_bid=False
                    )
                    for entry in orderbook_data.get('a', [])[:50]
                ]
                
                # Create orderbook
                orderbook = OrderBook(
                    symbol=symbol,
                    bids=bids,
                    asks=asks,
                    timestamp=datetime.now()
                )
                
                # Store in memory
                async with self._lock:
                    self.orderbooks[symbol] = orderbook
                
                # Store in Redis
                await self.redis.set_orderbook(symbol, orderbook)
                
                # Track large orders
                await self._track_large_orders(symbol, orderbook)
                
                # Analyze orderbook
                await self._analyze_orderbook(symbol, orderbook)
                
        except Exception as e:
            logger.error(f"Error processing orderbook update for {symbol}: {e}")
    
    async def _track_large_orders(self, symbol: str, orderbook: OrderBook):
        """Track large orders in the orderbook"""
        try:
            # Get median order size from history
            median_size = await self.redis.get_median_order_size(symbol)
            if median_size == 0:
                median_size = 1000  # Default if not set
            
            # Check both sides
            for side, entries in [('bid', orderbook.bids), ('ask', orderbook.asks)]:
                for entry in entries[:10]:  # Check top 10 levels
                    size_ratio = entry.size / median_size if median_size > 0 else 0
                    
                    if size_ratio >= config.ORDER_SIZE_THRESHOLDS['large']:
                        key = f"{symbol}:{side}:{entry.price}"
                        current_time = datetime.now()
                        
                        # Check if we're already tracking this order
                        if key not in self.tracking:
                            self.tracking[key] = {
                                'symbol': symbol,
                                'side': side,
                                'price': entry.price,
                                'first_seen': current_time,
                                'last_seen': current_time,
                                'initial_size': entry.size,
                                'current_size': entry.size,
                                'max_size': entry.size,
                                'history': deque(maxlen=100),
                                'notifications_sent': False
                            }
                            # Save to Redis
                            await self.redis.save_large_order(key, self.tracking[key])
                        else:
                            # Update existing tracking
                            track = self.tracking[key]
                            track['last_seen'] = current_time
                            track['current_size'] = entry.size
                            track['max_size'] = max(track['max_size'], entry.size)
                            
                            # Check for size reduction (possible execution)
                            if track['current_size'] < track['max_size'] * 0.8:
                                # Significant reduction
                                await self._check_order_reduction(track)
                            
                            # Update Redis
                            await self.redis.save_large_order(key, track)
        
        except Exception as e:
            logger.error(f"Error tracking large orders: {e}")
    
    async def _check_order_reduction(self, track: Dict):
        """Check if order reduction is due to execution or cancellation"""
        try:
            # Get recent trades for this symbol
            trades = await self.redis.get_recent_trades(track['symbol'], minutes=5)
            
            # Calculate executed volume at this price level
            executed = sum(
                t['size'] for t in trades
                if abs(t['price'] - track['price']) < track['price'] * 0.001
            )
            
            reduction = track['max_size'] - track['current_size']
            
            if reduction > executed * 1.2:  # More reduction than executed
                # Possible cancellation/spoofing
                await self._handle_spoofing_signal(track)
            
        except Exception as e:
            logger.error(f"Error checking order reduction: {e}")
    
    async def _handle_spoofing_signal(self, track: Dict):
        """Handle possible spoofing detection"""
        signal_data = {
            'type': 'SPOOFING',
            'symbol': track['symbol'],
            'side': 'SELL' if track['side'] == 'ask' else 'BUY',
            'price': track['price'],
            'initial_size': track['max_size'],
            'remaining_size': track['current_size'],
            'reduction': track['max_size'] - track['current_size'],
            'timestamp': datetime.now()
        }
        
        # Save to Redis
        await self.redis.save_signal(track['symbol'], signal_data)
        logger.warning(f"Possible spoofing detected: {track['symbol']} at {track['price']}")
    
    async def _analyze_orderbook(self, symbol: str, orderbook: OrderBook):
        """Analyze orderbook for imbalances and liquidity zones"""
        try:
            # Calculate imbalance
            bid_volume = sum(b.size for b in orderbook.bids[:20])
            ask_volume = sum(a.size for a in orderbook.asks[:20])
            
            if bid_volume + ask_volume > 0:
                imbalance = (bid_volume - ask_volume) / (bid_volume + ask_volume)
            else:
                imbalance = 0
            
            # Store imbalance
            await self.redis.set_imbalance(symbol, imbalance)
            
            # Find liquidity zones
            zones = await self._find_liquidity_zones(symbol, orderbook)
            
            # Check if any significant zone exists
            median_size = await self.redis.get_median_order_size(symbol)
            if median_size == 0:
                median_size = 1000
                
            for zone in zones:
                if zone['total_volume'] > median_size * 10:
                    await self._handle_liquidity_zone(symbol, zone)
            
        except Exception as e:
            logger.error(f"Error analyzing orderbook: {e}")
    
    async def _find_liquidity_zones(self, symbol: str, orderbook: OrderBook) -> List[Dict]:
        """Find liquidity zones in orderbook"""
        zones = []
        price_threshold = orderbook.mid_price * 0.001  # 0.1% grouping
        
        for side, entries in [('bid', orderbook.bids), ('ask', orderbook.asks)]:
            if not entries:
                continue
            
            current_zone = {
                'side': side,
                'min_price': entries[0].price,
                'max_price': entries[0].price,
                'total_volume': 0,
                'entries': []
            }
            
            for entry in entries[:20]:
                if entry.price - current_zone['max_price'] <= price_threshold:
                    current_zone['min_price'] = min(current_zone['min_price'], entry.price)
                    current_zone['max_price'] = max(current_zone['max_price'], entry.price)
                    current_zone['total_volume'] += entry.size
                    current_zone['entries'].append(entry)
                else:
                    if current_zone['total_volume'] > 0:
                        zones.append(current_zone)
                    current_zone = {
                        'side': side,
                        'min_price': entry.price,
                        'max_price': entry.price,
                        'total_volume': entry.size,
                        'entries': [entry]
                    }
            
            if current_zone['total_volume'] > 0:
                zones.append(current_zone)
        
        return zones
    
    async def _handle_liquidity_zone(self, symbol: str, zone: Dict):
        """Handle significant liquidity zone"""
        signal_data = {
            'type': 'LIQUIDITY_ZONE',
            'symbol': symbol,
            'side': 'SELL' if zone['side'] == 'ask' else 'BUY',
            'price_min': zone['min_price'],
            'price_max': zone['max_price'],
            'total_volume': zone['total_volume'],
            'timestamp': datetime.now()
        }
        
        await self.redis.save_signal(symbol, signal_data)
        
        # Check if this zone matches any levels
        if zone['side'] == 'ask':
            await self._check_sell_wall(symbol, zone)
        else:
            await self._check_buy_wall(symbol, zone)
    
    async def _check_sell_wall(self, symbol: str, zone: Dict):
        """Check if liquidity zone is a sell wall"""
        # Check if price is near recent highs
        levels = await self.redis.get_levels(symbol)
        for level in levels:
            if abs(level['price'] - zone['min_price']) < level['price'] * 0.005:
                # Level matched
                signal_data = {
                    'type': 'SELL_WALL',
                    'symbol': symbol,
                    'level': level['price'],
                    'strength': level['strength'],
                    'volume': zone['total_volume'],
                    'timestamp': datetime.now()
                }
                await self.redis.save_signal(symbol, signal_data)
    
    async def _check_buy_wall(self, symbol: str, zone: Dict):
        """Check if liquidity zone is a buy wall"""
        levels = await self.redis.get_levels(symbol)
        for level in levels:
            if abs(level['price'] - zone['max_price']) < level['price'] * 0.005:
                signal_data = {
                    'type': 'BUY_WALL',
                    'symbol': symbol,
                    'level': level['price'],
                    'strength': level['strength'],
                    'volume': zone['total_volume'],
                    'timestamp': datetime.now()
                }
                await self.redis.save_signal(symbol, signal_data)
    
    async def _handle_trade(self, symbol: str, data: Dict):
        """Process trade data"""
        try:
            if 'data' in data and data['data']:
                for trade_data in data['data']:
                    trade = {
                        'symbol': symbol,
                        'price': float(trade_data['p']),
                        'size': float(trade_data['v']),
                        'side': trade_data['S'],  # 'Buy' or 'Sell'
                        'timestamp': datetime.fromtimestamp(int(trade_data['T']) / 1000),
                        'notional': float(trade_data['p']) * float(trade_data['v'])
                    }
                    await self.redis.add_trade(symbol, trade)
                
                # Update volume stats
                await self._update_volume_stats(symbol, data['data'])
                
        except Exception as e:
            logger.error(f"Error handling trade for {symbol}: {e}")
    
    async def _update_volume_stats(self, symbol: str, trades: List[Dict]):
        """Update volume statistics"""
        try:
            # Calculate buy/sell volume
            buy_volume = sum(
                float(t['p']) * float(t['v']) 
                for t in trades if t['S'] == 'Buy'
            )
            sell_volume = sum(
                float(t['p']) * float(t['v']) 
                for t in trades if t['S'] == 'Sell'
            )
            
            # Update Redis
            await self.redis.update_volume_stats(symbol, buy_volume, sell_volume)
            
        except Exception as e:
            logger.error(f"Error updating volume stats: {e}")
    
    async def get_orderbook(self, symbol: str) -> Optional[OrderBook]:
        """Get current orderbook for symbol"""
        return self.orderbooks.get(symbol)
    
    async def start(self):
        """Start orderbook manager"""
        self.running = True
        logger.info("Orderbook manager started")
        
        # Start cleanup task
        asyncio.create_task(self._cleanup_task())
    
    async def stop(self):
        """Stop orderbook manager"""
        self.running = False
        logger.info("Orderbook manager stopped")
    
    async def _cleanup_task(self):
        """Clean up old tracking data"""
        while self.running:
            await asyncio.sleep(60)  # Run every minute
            
            try:
                current_time = datetime.now()
                to_delete = []
                
                for key, track in self.tracking.items():
                    # Remove orders older than 1 hour
                    if (current_time - track['last_seen']).total_seconds() > 3600:
                        to_delete.append(key)
                
                for key in to_delete:
                    del self.tracking[key]
                    await self.redis.delete_key(key)
                
            except Exception as e:
                logger.error(f"Cleanup task error: {e}")