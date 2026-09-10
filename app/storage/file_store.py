"""
Файловый аналог Redis на SQLite.
API совместим с методами RedisStorage, используемыми в проекте.
Хранит данные на диске → переживает рестарт контейнера.
"""
import os
import json
import time
import sqlite3
import asyncio
from typing import Any, Optional, List, Dict
from datetime import datetime, timedelta
from collections import deque

from app.config import config
from app.utils.logger import logger


class FileStore:
    """SQLite-based key-value store с TTL, списками, множествами и тредами."""

    def __init__(self, path: str = "data/store.db"):
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        full = os.path.join(base, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)

        self._db_path = full
        self._lock = asyncio.Lock()
        self._init_db()

        # Локальный кэш горячих значений (сделки держим в памяти — они не нужны после рестарта)
        self._trades: Dict[str, deque] = {}
        self._trades_max = 2000

        logger.info(f"✅ FileStore initialized: {self._db_path}")

    # ========== SQL ==========

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self):
        with self._conn() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS kv (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    expires_at REAL
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_kv_expires ON kv(expires_at)")

            c.execute("""
                CREATE TABLE IF NOT EXISTS sets (
                    key TEXT NOT NULL,
                    member TEXT NOT NULL,
                    PRIMARY KEY (key, member)
                )
            """)

    def _cleanup(self, c: sqlite3.Connection):
        c.execute("DELETE FROM kv WHERE expires_at IS NOT NULL AND expires_at < ?", (time.time(),))

    # ========== БАЗОВЫЕ KV ==========

    async def _set(self, key: str, value: Any, ttl: Optional[int] = None):
        async with self._lock:
            payload = json.dumps(value, default=str)
            expires = (time.time() + ttl) if ttl else None
            with self._conn() as c:
                c.execute(
                    "INSERT OR REPLACE INTO kv(key, value, expires_at) VALUES (?, ?, ?)",
                    (key, payload, expires),
                )

    async def _get(self, key: str) -> Optional[Any]:
        with self._conn() as c:
            row = c.execute("SELECT value, expires_at FROM kv WHERE key = ?", (key,)).fetchone()
        if not row:
            return None
        value, expires_at = row
        if expires_at is not None and expires_at < time.time():
            async with self._lock:
                with self._conn() as c:
                    c.execute("DELETE FROM kv WHERE key = ?", (key,))
            return None
        try:
            return json.loads(value)
        except Exception:
            return None

    async def _delete(self, key: str):
        async with self._lock:
            with self._conn() as c:
                c.execute("DELETE FROM kv WHERE key = ?", (key,))

    async def _keys(self, prefix: str) -> List[str]:
        with self._conn() as c:
            self._cleanup(c)
            rows = c.execute("SELECT key FROM kv WHERE key LIKE ?", (prefix + "%",)).fetchall()
        return [r[0] for r in rows]

    # ========== СИМВОЛЫ ==========

    async def get_active_symbols(self) -> List[str]:
        return await self._get("active_symbols") or []

    async def set_active_symbols(self, symbols: List[str]):
        await self._set("active_symbols", symbols)

    # ========== ORDERBOOK ==========

    async def set_orderbook(self, symbol: str, orderbook):
        data = {
            "symbol": symbol,
            "bids": [[b.price, b.size] for b in orderbook.bids[:20]],
            "asks": [[a.price, a.size] for a in orderbook.asks[:20]],
            "timestamp": orderbook.timestamp.isoformat(),
        }
        await self._set(f"orderbook:{symbol}", data, ttl=60)

    async def get_orderbook(self, symbol: str) -> Optional[Dict]:
        return await self._get(f"orderbook:{symbol}")

    # ========== СДЕЛКИ (горячий кэш в RAM) ==========

    async def add_trade(self, symbol: str, trade: Dict):
        if symbol not in self._trades:
            self._trades[symbol] = deque(maxlen=self._trades_max)
        ts = trade["timestamp"]
        self._trades[symbol].append({
            "price": float(trade["price"]),
            "size": float(trade["size"]),
            "side": trade["side"],
            "timestamp": ts.isoformat() if isinstance(ts, datetime) else str(ts),
            "notional": float(trade["notional"]),
        })

    async def get_recent_trades(self, symbol: str, seconds: int = 300) -> List[Dict]:
        if symbol not in self._trades:
            return []
        cutoff = datetime.now() - timedelta(seconds=seconds)
        out = []
        for t in self._trades[symbol]:
            try:
                ts = datetime.fromisoformat(t["timestamp"])
                if ts >= cutoff:
                    out.append(t)
            except Exception:
                continue
        return out

    # ========== MEDIAN ==========

    async def set_median_trade_size(self, symbol: str, size: float):
        await self._set(f"median_size:{symbol}", float(size), ttl=600)

    async def get_median_trade_size(self, symbol: str) -> float:
        return await self._get(f"median_size:{symbol}") or 0.0

    async def set_median_order_size(self, symbol: str, size: float):
        await self._set(f"median_order_size:{symbol}", float(size), ttl=600)

    async def get_median_order_size(self, symbol: str) -> float:
        return await self._get(f"median_order_size:{symbol}") or 0.0

    # ========== CVD / DELTA ==========

    async def set_cvd(self, symbol: str, cvd: float):
        await self._set(f"cvd:{symbol}", float(cvd), ttl=86400)

    async def get_cvd(self, symbol: str) -> float:
        return await self._get(f"cvd:{symbol}") or 0.0

    async def set_delta(self, symbol: str, delta: float):
        await self._set(f"delta:{symbol}", float(delta), ttl=300)

    async def get_delta(self, symbol: str) -> float:
        return await self._get(f"delta:{symbol}") or 0.0

    # ========== IMBALANCE ==========

    async def set_imbalance(self, symbol: str, imbalance: float):
        await self._set(f"imbalance:{symbol}", float(imbalance), ttl=60)

    async def get_imbalance(self, symbol: str) -> float:
        return await self._get(f"imbalance:{symbol}") or 0.0

    # ========== LEVELS ==========

    async def set_levels(self, symbol: str, levels: List[Dict]):
        await self._set(f"levels:{symbol}", levels, ttl=3600)

    async def get_levels(self, symbol: str) -> List[Dict]:
        return await self._get(f"levels:{symbol}") or []

    # ========== OI / FUNDING ==========

    async def set_oi_data(self, symbol: str, data: Dict):
        await self._set(f"oi:{symbol}", data, ttl=300)

    async def get_oi_data(self, symbol: str) -> Dict:
        return await self._get(f"oi:{symbol}") or {"oi": 0, "timestamp": None}

    async def set_funding_data(self, symbol: str, data: Dict):
        await self._set(f"funding:{symbol}", data, ttl=600)

    async def get_funding_data(self, symbol: str) -> Dict:
        return await self._get(f"funding:{symbol}") or {"funding_rate": 0}

    # ========== VOLUME ==========

    async def update_volume_stats(self, symbol: str, buy_volume: float, sell_volume: float):
        await self._set(
            f"volume:{symbol}",
            {"buy": buy_volume, "sell": sell_volume, "timestamp": datetime.now().isoformat()},
            ttl=60,
        )

    async def get_volume_stats(self, symbol: str) -> Dict:
        return await self._get(f"volume:{symbol}") or {"buy": 0, "sell": 0}

    # ========== SIGNALS ==========

    async def save_signal(self, symbol: str, signal: Dict):
        await self._set(f"signal:{symbol}", signal, ttl=3600)

    async def get_active_signals(self) -> Dict:
        out = {}
        for key in await self._keys("signal:"):
            val = await self._get(key)
            if val:
                out[key.split(":", 1)[1]] = val
        return out

    async def get_current_price(self, symbol: str) -> Optional[float]:
        trades = await self.get_recent_trades(symbol, seconds=60)
        return trades[-1]["price"] if trades else None

    # ========== SCORE ==========

    async def set_current_score(self, symbol: str, score: int):
        await self._set(f"score:{symbol}", int(score), ttl=60)

    async def get_current_score(self, symbol: str) -> Optional[int]:
        return await self._get(f"score:{symbol}")

    # ========== SIGNAL MEMORY ==========

    async def set_signal_memory(self, key: str, data: Dict):
        await self._set(f"signal_memory:{key}", data, ttl=3600)

    async def get_signal_memory(self, key: str) -> Optional[Dict]:
        return await self._get(f"signal_memory:{key}")

    # ========== LARGE ORDERS ==========

    async def save_large_order(self, key: str, data: Dict):
        serializable = {k: v for k, v in data.items() if k != "history"}
        await self._set(f"order_track:{key}", serializable, ttl=3600)

    async def delete_key(self, key: str):
        await self._delete(key)

    # ========== AGGRESSION / LIQUIDITY ==========

    async def set_aggression(self, symbol: str, data: Dict):
        await self._set(f"aggression:{symbol}", data, ttl=60)

    async def get_aggression(self, symbol: str) -> Optional[Dict]:
        return await self._get(f"aggression:{symbol}")

    async def set_liquidity_analysis(self, symbol: str, data: Dict):
        await self._set(f"liquidity:{symbol}", data, ttl=60)

    async def set_oi_analysis(self, symbol: str, data: Dict):
        await self._set(f"oi_analysis:{symbol}", data, ttl=300)

    async def set_funding_analysis(self, symbol: str, data: Dict):
        await self._set(f"funding_analysis:{symbol}", data, ttl=600)

    async def set_volume_analysis(self, symbol: str, data: Dict):
        await self._set(f"volume_analysis:{symbol}", data, ttl=300)