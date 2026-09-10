"""
Память сигналов.
Правила:
- Один и тот же сигнал (symbol + direction) не повторяется, пока:
  - не прошёл cooldown, И
  - score не вырос на MIN_DELTA.
- Память живёт в FileStore → переживает рестарт.
"""
import time
from typing import Dict, Optional

from app.storage.store import Store
from app.config import config
from app.utils.logger import logger


class SignalMemory:
    KEY = "signals_memory"

    def __init__(self, store: Store):
        self.store = store
        self._cache: Dict[str, Dict] = {}
        self._loaded = False

    async def load(self):
        data = await self.store._get(self.KEY)
        if isinstance(data, dict):
            self._cache = data
        self._loaded = True

    async def _flush(self):
        await self.store._set(self.KEY, self._cache, ttl=None)

    def _key(self, symbol: str, direction: str) -> str:
        return f"{symbol}:{direction}"

    async def should_send(
        self,
        symbol: str,
        direction: str,
        score: int,
        level_price: float,
        min_delta: int = 10,
    ) -> bool:
        if not self._loaded:
            await self.load()

        key = self._key(symbol, direction)
        now = time.time()
        rec = self._cache.get(key)

        if rec is None:
            return True

        # cooldown
        since = now - rec.get("last_ts", 0)
        if since < config.SIGNAL_COOLDOWN_SEC:
            # Только если score ощутимо вырос — можно прислать «усиление»
            if score - rec.get("score", 0) >= min_delta:
                return True
            return False

        # cooldown прошёл
        if score - rec.get("score", 0) >= min_delta:
            return True

        # Цена уровня сменилась — новый сигнал
        if abs(level_price - rec.get("level_price", 0)) / max(level_price, 1e-9) > 0.002:
            return True

        return False

    async def remember(
        self,
        symbol: str,
        direction: str,
        score: int,
        level_price: float,
        message: str = "",
    ):
        if not self._loaded:
            await self.load()

        key = self._key(symbol, direction)
        self._cache[key] = {
            "symbol": symbol,
            "direction": direction,
            "score": score,
            "level_price": level_price,
            "last_ts": time.time(),
            "message": message[:200],
        }
        await self._flush()