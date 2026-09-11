"""
PostgreSQL storage. Обязателен для старта бота.
Если подключение не удалось — бот НЕ запускается.
"""
import asyncpg
from typing import List, Dict, Optional
from datetime import datetime

from app.config import config
from app.utils.logger import logger


class PostgresStorage:
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None
        self._connected = False

    async def connect(self):
        """Подключение. Бросает исключение, если не удалось."""
        self.pool = await asyncpg.create_pool(
            config.DATABASE_URL,
            min_size=1,
            max_size=5,
            timeout=15,
            command_timeout=30,
        )
        await self._create_tables()
        self._connected = True
        logger.info("✅ PostgreSQL connected")

    async def _create_tables(self):
        if not self.pool:
            raise RuntimeError("Postgres pool is None")

        async with self.pool.acquire() as c:
            await c.execute("""
                CREATE TABLE IF NOT EXISTS oi_history (
                    id BIGSERIAL PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    oi DOUBLE PRECISION NOT NULL,
                    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            await c.execute("""
                CREATE INDEX IF NOT EXISTS idx_oi_symbol_ts
                ON oi_history(symbol, timestamp DESC)
            """)

            await c.execute("""
                CREATE TABLE IF NOT EXISTS funding_history (
                    id BIGSERIAL PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    funding_rate DOUBLE PRECISION NOT NULL,
                    next_funding_time TIMESTAMPTZ,
                    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            await c.execute("""
                CREATE INDEX IF NOT EXISTS idx_fund_symbol_ts
                ON funding_history(symbol, timestamp DESC)
            """)

            await c.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    id BIGSERIAL PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    level DOUBLE PRECISION,
                    score INTEGER NOT NULL,
                    state TEXT,
                    signal_type TEXT,
                    factors JSONB,
                    message TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            await c.execute("""
                CREATE INDEX IF NOT EXISTS idx_signals_symbol_ts
                ON signals(symbol, created_at DESC)
            """)

            await c.execute("""
                CREATE TABLE IF NOT EXISTS large_orders (
                    id BIGSERIAL PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    price DOUBLE PRECISION NOT NULL,
                    initial_size DOUBLE PRECISION NOT NULL,
                    max_size DOUBLE PRECISION NOT NULL,
                    current_size DOUBLE PRECISION NOT NULL,
                    executed_estimate DOUBLE PRECISION DEFAULT 0,
                    cancelled_estimate DOUBLE PRECISION DEFAULT 0,
                    first_seen TIMESTAMPTZ NOT NULL,
                    last_seen TIMESTAMPTZ NOT NULL,
                    status TEXT DEFAULT 'active',
                    session_id BIGINT NOT NULL,
                    UNIQUE(symbol, side, price, session_id)
                )
            """)

            await c.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id BIGSERIAL PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    price DOUBLE PRECISION NOT NULL,
                    size DOUBLE PRECISION NOT NULL,
                    side TEXT NOT NULL,
                    notional DOUBLE PRECISION NOT NULL,
                    timestamp TIMESTAMPTZ NOT NULL
                )
            """)
            await c.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_symbol_ts
                ON trades(symbol, timestamp DESC)
            """)

            await c.execute("""
                CREATE TABLE IF NOT EXISTS candles (
                    id BIGSERIAL PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    ts TIMESTAMPTZ NOT NULL,
                    open DOUBLE PRECISION,
                    high DOUBLE PRECISION,
                    low DOUBLE PRECISION,
                    close DOUBLE PRECISION,
                    volume DOUBLE PRECISION,
                    turnover DOUBLE PRECISION,
                    UNIQUE(symbol, timeframe, ts)
                )
            """)

            await c.execute("""
                CREATE TABLE IF NOT EXISTS levels (
                    id BIGSERIAL PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    price DOUBLE PRECISION NOT NULL,
                    strength INTEGER,
                    timeframe TEXT,
                    touches INTEGER,
                    volume DOUBLE PRECISION,
                    is_support BOOLEAN,
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(symbol, price)
                )
            """)

    # ========== SAVE ==========

    async def save_oi(self, symbol: str, oi: float):
        if not self.pool:
            return
        async with self.pool.acquire() as c:
            await c.execute(
                """
                INSERT INTO oi_history(symbol, oi, timestamp)
                VALUES ($1, $2, $3)
                """,
                symbol, float(oi), datetime.now(),
            )

    async def save_funding(self, symbol: str, funding_rate: float, next_funding_time: Optional[datetime] = None):
        if not self.pool:
            return
        async with self.pool.acquire() as c:
            await c.execute(
                """
                INSERT INTO funding_history(symbol, funding_rate, next_funding_time, timestamp)
                VALUES ($1, $2, $3, $4)
                """,
                symbol, float(funding_rate), next_funding_time, datetime.now(),
            )

    async def save_signal(self, signal) -> int:
        if not self.pool:
            return 0
        import json
        async with self.pool.acquire() as c:
            row = await c.fetchrow(
                """
                INSERT INTO signals(symbol, direction, level, score, state, signal_type, factors, message)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id
                """,
                signal.symbol, signal.direction, signal.level, signal.score,
                signal.state.value if hasattr(signal.state, "value") else str(signal.state),
                signal.signal_type.value if hasattr(signal.signal_type, "value") else str(signal.signal_type),
                json.dumps(signal.factors, default=str),
                signal.message,
            )
            return row["id"] if row else 0

    async def save_large_order(self, order_data: Dict):
        if not self.pool:
            return
        async with self.pool.acquire() as c:
            await c.execute(
                """
                INSERT INTO large_orders(
                    symbol, side, price, initial_size, max_size, current_size,
                    executed_estimate, cancelled_estimate, first_seen, last_seen, status, session_id
                )
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                ON CONFLICT(symbol, side, price, session_id)
                DO UPDATE SET
                    max_size = EXCLUDED.max_size,
                    current_size = EXCLUDED.current_size,
                    executed_estimate = EXCLUDED.executed_estimate,
                    cancelled_estimate = EXCLUDED.cancelled_estimate,
                    last_seen = EXCLUDED.last_seen,
                    status = EXCLUDED.status
                """,
                order_data["symbol"], order_data["side"], order_data["price"],
                order_data["initial_size"], order_data["max_size"], order_data["current_size"],
                order_data.get("executed_estimate", 0), order_data.get("cancelled_estimate", 0),
                order_data["first_seen"], order_data["last_seen"],
                order_data.get("status", "active"),
                int(order_data.get("session_id", 0)),
            )

    async def save_trade(self, symbol: str, trade: Dict):
        if not self.pool:
            return
        async with self.pool.acquire() as c:
            await c.execute(
                """
                INSERT INTO trades(symbol, price, size, side, notional, timestamp)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                symbol, float(trade["price"]), float(trade["size"]),
                trade["side"], float(trade["notional"]), trade["timestamp"],
            )

    async def save_candle(self, symbol: str, timeframe: str, candle: Dict):
        if not self.pool:
            return
        async with self.pool.acquire() as c:
            await c.execute(
                """
                INSERT INTO candles(symbol, timeframe, ts, open, high, low, close, volume, turnover)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                ON CONFLICT(symbol, timeframe, ts) DO UPDATE SET
                    open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                    close=EXCLUDED.close, volume=EXCLUDED.volume, turnover=EXCLUDED.turnover
                """,
                symbol, timeframe, candle["timestamp"],
                candle["open"], candle["high"], candle["low"], candle["close"],
                candle["volume"], candle["turnover"],
            )

    async def save_level(self, symbol: str, level: Dict):
        if not self.pool:
            return
        async with self.pool.acquire() as c:
            await c.execute(
                """
                INSERT INTO levels(symbol, price, strength, timeframe, touches, volume, is_support)
                VALUES ($1,$2,$3,$4,$5,$6,$7)
                ON CONFLICT(symbol, price) DO UPDATE SET
                    strength=EXCLUDED.strength,
                    touches=EXCLUDED.touches,
                    volume=EXCLUDED.volume,
                    updated_at=NOW()
                """,
                symbol, level["price"], int(level["strength"]),
                level["timeframe"], int(level["touches"]),
                float(level["volume"]), level["type"] == "support",
            )

    # ========== GET ==========

    async def get_oi_history(self, symbol: str, limit: int = 200) -> List[Dict]:
        if not self.pool:
            return []
        async with self.pool.acquire() as c:
            rows = await c.fetch(
                """
                SELECT oi, timestamp FROM oi_history
                WHERE symbol = $1
                ORDER BY timestamp DESC
                LIMIT $2
                """,
                symbol, limit,
            )
            return [dict(r) for r in rows]

    async def get_funding_history(self, symbol: str, limit: int = 200) -> List[Dict]:
        if not self.pool:
            return []
        async with self.pool.acquire() as c:
            rows = await c.fetch(
                """
                SELECT funding_rate, timestamp FROM funding_history
                WHERE symbol = $1
                ORDER BY timestamp DESC
                LIMIT $2
                """,
                symbol, limit,
            )
            return [dict(r) for r in rows]

    async def get_recent_signals(self, limit: int = 20) -> List[Dict]:
        if not self.pool:
            return []
        async with self.pool.acquire() as c:
            rows = await c.fetch(
                """
                SELECT symbol, direction, score, created_at
                FROM signals
                ORDER BY created_at DESC
                LIMIT $1
                """,
                limit,
            )
            return [dict(r) for r in rows]

    async def close(self):
        if self.pool:
            await self.pool.close()
            self._connected = False
            logger.info("PostgreSQL closed")