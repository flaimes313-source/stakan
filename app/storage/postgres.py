import asyncpg
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta
from app.config import config
from app.utils.logger import logger

class PostgresStorage:
    def __init__(self):
        self.pool = None
        self._connected = False
        
    async def connect(self):
        """Connect to PostgreSQL"""
        try:
            self.pool = await asyncpg.create_pool(
                config.DATABASE_URL,
                min_size=1,
                max_size=5,
                timeout=10
            )
            await self._create_tables()
            self._connected = True
            logger.info("✅ PostgreSQL connected")
        except Exception as e:
            logger.warning(f"⚠️ PostgreSQL unavailable: {e}. Working without DB.")
            self.pool = None
            self._connected = False
    
    async def _create_tables(self):
        """Create all necessary tables"""
        if not self.pool:
            return
        async with self.pool.acquire() as conn:
            # 1. Symbols table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS symbols (
                    id SERIAL PRIMARY KEY,
                    symbol VARCHAR(20) UNIQUE NOT NULL,
                    name VARCHAR(50),
                    active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 2. Candles table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS candles (
                    id SERIAL PRIMARY KEY,
                    symbol VARCHAR(20) NOT NULL,
                    timeframe VARCHAR(10) NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    open DECIMAL(20,8),
                    high DECIMAL(20,8),
                    low DECIMAL(20,8),
                    close DECIMAL(20,8),
                    volume DECIMAL(20,8),
                    turnover DECIMAL(20,2),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, timeframe, timestamp)
                )
            """)
            
            # 3. Levels table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS levels (
                    id SERIAL PRIMARY KEY,
                    symbol VARCHAR(20) NOT NULL,
                    price DECIMAL(20,8) NOT NULL,
                    strength INTEGER,
                    timeframe VARCHAR(10),
                    touches INTEGER,
                    volume DECIMAL(20,8),
                    is_support BOOLEAN,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, price)
                )
            """)
            
            # 4. Orderbook events table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS orderbook_events (
                    id SERIAL PRIMARY KEY,
                    symbol VARCHAR(20) NOT NULL,
                    side VARCHAR(10) NOT NULL,
                    price DECIMAL(20,8) NOT NULL,
                    size DECIMAL(20,8) NOT NULL,
                    event_type VARCHAR(20) NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 5. Trades table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id SERIAL PRIMARY KEY,
                    symbol VARCHAR(20) NOT NULL,
                    price DECIMAL(20,8) NOT NULL,
                    size DECIMAL(20,8) NOT NULL,
                    side VARCHAR(10) NOT NULL,
                    notional DECIMAL(20,2) NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 6. OI History table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS oi_history (
                    id SERIAL PRIMARY KEY,
                    symbol VARCHAR(20) NOT NULL,
                    oi DECIMAL(20,2) NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 7. Funding History table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS funding_history (
                    id SERIAL PRIMARY KEY,
                    symbol VARCHAR(20) NOT NULL,
                    funding_rate DECIMAL(20,8) NOT NULL,
                    next_funding_time TIMESTAMP,
                    timestamp TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 8. Signals table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    id SERIAL PRIMARY KEY,
                    symbol VARCHAR(20) NOT NULL,
                    direction VARCHAR(10) NOT NULL,
                    level DECIMAL(20,8),
                    score INTEGER NOT NULL,
                    state VARCHAR(20),
                    signal_type VARCHAR(20),
                    factors JSONB,
                    message TEXT,
                    first_seen TIMESTAMP,
                    last_alert TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 9. Signal Events table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS signal_events (
                    id SERIAL PRIMARY KEY,
                    signal_id INTEGER REFERENCES signals(id),
                    event_type VARCHAR(20),
                    old_state VARCHAR(20),
                    new_state VARCHAR(20),
                    score_change INTEGER,
                    details JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 10. CVD History table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS cvd_history (
                    id SERIAL PRIMARY KEY,
                    symbol VARCHAR(20) NOT NULL,
                    cvd DECIMAL(20,2) NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 11. Large Orders table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS large_orders (
                    id SERIAL PRIMARY KEY,
                    symbol VARCHAR(20) NOT NULL,
                    side VARCHAR(10) NOT NULL,
                    price DECIMAL(20,8) NOT NULL,
                    initial_size DECIMAL(20,8) NOT NULL,
                    max_size DECIMAL(20,8) NOT NULL,
                    current_size DECIMAL(20,8) NOT NULL,
                    executed_estimate DECIMAL(20,8),
                    cancelled_estimate DECIMAL(20,8),
                    first_seen TIMESTAMP NOT NULL,
                    last_seen TIMESTAMP NOT NULL,
                    status VARCHAR(20),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Indexes
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_candles_symbol_timeframe 
                ON candles(symbol, timeframe, timestamp DESC)
            """)
            
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_signals_symbol 
                ON signals(symbol, created_at DESC)
            """)
            
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_oi_history_symbol 
                ON oi_history(symbol, timestamp DESC)
            """)
            
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_symbol 
                ON trades(symbol, timestamp DESC)
            """)
            
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_large_orders_symbol 
                ON large_orders(symbol, last_seen DESC)
            """)
    
    # ============ SAVE METHODS ============
    
    async def save_candle(self, symbol: str, timeframe: str, candle: Dict):
        if not self.pool:
            return
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO candles (symbol, timeframe, timestamp, open, high, low, close, volume, turnover)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    ON CONFLICT (symbol, timeframe, timestamp) 
                    DO UPDATE SET 
                        open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume,
                        turnover = EXCLUDED.turnover
                """, symbol, timeframe, candle['timestamp'], candle['open'],
                    candle['high'], candle['low'], candle['close'],
                    candle['volume'], candle['turnover'])
        except Exception as e:
            logger.debug(f"Error saving candle: {e}")
    
    async def save_level(self, symbol: str, level: Dict):
        if not self.pool:
            return
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO levels (symbol, price, strength, timeframe, touches, volume, is_support)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (symbol, price) 
                    DO UPDATE SET 
                        strength = EXCLUDED.strength,
                        touches = EXCLUDED.touches,
                        volume = EXCLUDED.volume,
                        updated_at = CURRENT_TIMESTAMP
                """, symbol, level['price'], level['strength'],
                    level['timeframe'], level['touches'],
                    level['volume'], level['type'] == 'support')
        except Exception as e:
            logger.debug(f"Error saving level: {e}")
    
    async def save_trade(self, symbol: str, trade: Dict):
        if not self.pool:
            return
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO trades (symbol, price, size, side, notional, timestamp)
                    VALUES ($1, $2, $3, $4, $5, $6)
                """, symbol, trade['price'], trade['size'], 
                    trade['side'], trade['notional'], trade['timestamp'])
        except Exception as e:
            logger.debug(f"Error saving trade: {e}")
    
    async def save_oi(self, symbol: str, oi: float):
        if not self.pool:
            return
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO oi_history (symbol, oi, timestamp)
                    VALUES ($1, $2, $3)
                """, symbol, oi, datetime.now())
        except Exception as e:
            logger.debug(f"Error saving OI: {e}")
    
    async def save_funding(self, symbol: str, funding_rate: float, next_funding_time: datetime = None):
        if not self.pool:
            return
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO funding_history (symbol, funding_rate, next_funding_time, timestamp)
                    VALUES ($1, $2, $3, $4)
                """, symbol, funding_rate, next_funding_time, datetime.now())
        except Exception as e:
            logger.debug(f"Error saving funding: {e}")
    
    async def save_signal(self, signal) -> int:
        if not self.pool:
            return 0
        try:
            async with self.pool.acquire() as conn:
                result = await conn.fetchrow("""
                    INSERT INTO signals (symbol, direction, level, score, state, signal_type, factors, message, first_seen, last_alert)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    RETURNING id
                """, signal.symbol, signal.direction, signal.level, signal.score,
                    signal.state.value, 'SETUP',
                    signal.factors, signal.message, signal.timestamp, signal.timestamp)
                return result['id'] if result else 0
        except Exception as e:
            logger.debug(f"Error saving signal: {e}")
            return 0
    
    async def update_signal(self, signal_id: int, data: Dict):
        if not self.pool:
            return
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    UPDATE signals 
                    SET score = $1, state = $2, message = $3, factors = $4, last_alert = $5, updated_at = CURRENT_TIMESTAMP
                    WHERE id = $6
                """, data.get('score'), data.get('state'), data.get('message'),
                    data.get('factors'), data.get('last_alert'), signal_id)
        except Exception as e:
            logger.debug(f"Error updating signal: {e}")
    
    async def save_signal_event(self, signal_id: int, event_type: str, old_state: str, new_state: str, score_change: int = 0, details: Dict = None):
        if not self.pool:
            return
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO signal_events (signal_id, event_type, old_state, new_state, score_change, details)
                    VALUES ($1, $2, $3, $4, $5, $6)
                """, signal_id, event_type, old_state, new_state, score_change, details)
        except Exception as e:
            logger.debug(f"Error saving signal event: {e}")
    
    async def save_large_order(self, order_data: Dict):
        if not self.pool:
            return
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO large_orders (symbol, side, price, initial_size, max_size, current_size, 
                                            executed_estimate, cancelled_estimate, first_seen, last_seen, status)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    ON CONFLICT (symbol, side, price) 
                    DO UPDATE SET 
                        max_size = EXCLUDED.max_size,
                        current_size = EXCLUDED.current_size,
                        executed_estimate = EXCLUDED.executed_estimate,
                        cancelled_estimate = EXCLUDED.cancelled_estimate,
                        last_seen = EXCLUDED.last_seen,
                        status = EXCLUDED.status,
                        updated_at = CURRENT_TIMESTAMP
                """, order_data['symbol'], order_data['side'], order_data['price'],
                    order_data['initial_size'], order_data['max_size'], order_data['current_size'],
                    order_data.get('executed_estimate'), order_data.get('cancelled_estimate'),
                    order_data['first_seen'], order_data['last_seen'], order_data.get('status', 'active'))
        except Exception as e:
            logger.debug(f"Error saving large order: {e}")
    
    async def save_cvd(self, symbol: str, cvd: float):
        if not self.pool:
            return
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO cvd_history (symbol, cvd, timestamp)
                    VALUES ($1, $2, $3)
                """, symbol, cvd, datetime.now())
        except Exception as e:
            logger.debug(f"Error saving CVD: {e}")
    
    # ============ GET METHODS ============
    
    async def get_recent_signals(self, symbol: str = None, limit: int = 50) -> List[Dict]:
        if not self.pool:
            return []
        try:
            async with self.pool.acquire() as conn:
                if symbol:
                    rows = await conn.fetch("""
                        SELECT * FROM signals
                        WHERE symbol = $1
                        ORDER BY created_at DESC
                        LIMIT $2
                    """, symbol, limit)
                else:
                    rows = await conn.fetch("""
                        SELECT * FROM signals
                        ORDER BY created_at DESC
                        LIMIT $1
                    """, limit)
                return [dict(row) for row in rows]
        except Exception as e:
            logger.debug(f"Error getting signals: {e}")
            return []
    
    async def get_cvd_history(self, symbol: str, limit: int = 100) -> List[Dict]:
        if not self.pool:
            return []
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT * FROM cvd_history
                    WHERE symbol = $1
                    ORDER BY timestamp DESC
                    LIMIT $2
                """, symbol, limit)
                return [dict(row) for row in rows]
        except Exception as e:
            logger.debug(f"Error getting CVD history: {e}")
            return []
    
    async def get_large_orders(self, symbol: str = None, status: str = 'active') -> List[Dict]:
        if not self.pool:
            return []
        try:
            async with self.pool.acquire() as conn:
                if symbol:
                    rows = await conn.fetch("""
                        SELECT * FROM large_orders
                        WHERE symbol = $1 AND status = $2
                        ORDER BY last_seen DESC
                    """, symbol, status)
                else:
                    rows = await conn.fetch("""
                        SELECT * FROM large_orders
                        WHERE status = $1
                        ORDER BY last_seen DESC
                        LIMIT 100
                    """, status)
                return [dict(row) for row in rows]
        except Exception as e:
            logger.debug(f"Error getting large orders: {e}")
            return []
    
    async def get_oi_history(self, symbol: str, limit: int = 100) -> List[Dict]:
        if not self.pool:
            return []
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT * FROM oi_history
                    WHERE symbol = $1
                    ORDER BY timestamp DESC
                    LIMIT $2
                """, symbol, limit)
                return [dict(row) for row in rows]
        except Exception as e:
            logger.debug(f"Error getting OI history: {e}")
            return []
    
    async def get_funding_history(self, symbol: str, limit: int = 50) -> List[Dict]:
        if not self.pool:
            return []
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT * FROM funding_history
                    WHERE symbol = $1
                    ORDER BY timestamp DESC
                    LIMIT $2
                """, symbol, limit)
                return [dict(row) for row in rows]
        except Exception as e:
            logger.debug(f"Error getting funding history: {e}")
            return []
    
    async def get_candles(self, symbol: str, timeframe: str, limit: int = 200) -> List[Dict]:
        if not self.pool:
            return []
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT * FROM candles
                    WHERE symbol = $1 AND timeframe = $2
                    ORDER BY timestamp DESC
                    LIMIT $3
                """, symbol, timeframe, limit)
                return [dict(row) for row in rows]
        except Exception as e:
            logger.debug(f"Error getting candles: {e}")
            return []
    
    async def close(self):
        """Close connection pool"""
        if self.pool:
            await self.pool.close()
            self._connected = False
            logger.info("PostgreSQL connection closed")