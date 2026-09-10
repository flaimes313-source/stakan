"""
Redis storage. Используется только если config.use_redis == True.
Иначе используется FileStore.
"""
import json
import redis.asyncio as aioredis
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from app.config import config
from app.utils.logger import logger


class RedisStorage:
    def __init__(self):
        self.redis = None
        if config.REDIS_URL:
            self.redis = aioredis.from_url(config.REDIS_URL, decode_responses=True)
        elif config.REDIS_HOST and config.REDIS_PORT:
            self.redis = aioredis.Redis(
                host=config.REDIS_HOST,
                port=config.REDIS_PORT,
                password=config.REDIS_PASSWORD or None,
                decode_responses=True,
            )
        logger.info("✅ RedisStorage initialized")

    async def get_active_symbols(self) -> List[str]:
        return list(await self.redis.smembers("active_symbols"))

    async def set_active_symbols(self, symbols: List[str]):
        await self.redis.delete("active_symbols")
        if symbols:
            await self.redis.sadd("active_symbols", *symbols)

    async def set_orderbook(self, symbol: str, orderbook):
        data = {
            "symbol": symbol,
            "bids": [[b.price, b.size] for b in orderbook.bids[:20]],
            "asks": [[a.price, a.size] for a in orderbook.asks[:20]],
            "timestamp": orderbook.timestamp.isoformat(),
        }
        await self.redis.setex(f"orderbook:{symbol}", 60, json.dumps(data))

    async def get_orderbook(self, symbol: str) -> Optional[Dict]:
        v = await self.redis.get(f"orderbook:{symbol}")
        return json.loads(v) if v else None

    async def add_trade(self, symbol: str, trade: Dict):
        data = {
            "price": trade["price"],
            "size": trade["size"],
            "side": trade["side"],
            "timestamp": trade["timestamp"].isoformat() if isinstance(trade["timestamp"], datetime) else str(trade["timestamp"]),
            "notional": trade["notional"],
        }
        key = f"trades:{symbol}"
        await self.redis.lpush(key, json.dumps(data))
        await self.redis.ltrim(key, 0, 1999)
        await self.redis.expire(key, 3600)

    async def get_recent_trades(self, symbol: str, seconds: int = 300) -> List[Dict]:
        rows = await self.redis.lrange(f"trades:{symbol}", 0, -1)
        cutoff = datetime.now() - timedelta(seconds=seconds)
        out = []
        for r in rows:
            try:
                t = json.loads(r)
                ts = datetime.fromisoformat(t["timestamp"])
                if ts >= cutoff:
                    out.append(t)
            except Exception:
                continue
        return out

    async def set_median_trade_size(self, symbol: str, size: float):
        await self.redis.setex(f"median_size:{symbol}", 600, str(size))

    async def get_median_trade_size(self, symbol: str) -> float:
        v = await self.redis.get(f"median_size:{symbol}")
        return float(v) if v else 0.0

    async def set_median_order_size(self, symbol: str, size: float):
        await self.redis.setex(f"median_order_size:{symbol}", 600, str(size))

    async def get_median_order_size(self, symbol: str) -> float:
        v = await self.redis.get(f"median_order_size:{symbol}")
        return float(v) if v else 0.0

    async def set_cvd(self, symbol: str, cvd: float):
        await self.redis.setex(f"cvd:{symbol}", 86400, str(cvd))

    async def get_cvd(self, symbol: str) -> float:
        v = await self.redis.get(f"cvd:{symbol}")
        return float(v) if v else 0.0

    async def set_delta(self, symbol: str, delta: float):
        await self.redis.setex(f"delta:{symbol}", 300, str(delta))

    async def get_delta(self, symbol: str) -> float:
        v = await self.redis.get(f"delta:{symbol}")
        return float(v) if v else 0.0

    async def set_imbalance(self, symbol: str, imbalance: float):
        await self.redis.setex(f"imbalance:{symbol}", 60, str(imbalance))

    async def get_imbalance(self, symbol: str) -> float:
        v = await self.redis.get(f"imbalance:{symbol}")
        return float(v) if v else 0.0

    async def set_levels(self, symbol: str, levels: List[Dict]):
        await self.redis.setex(f"levels:{symbol}", 3600, json.dumps(levels))

    async def get_levels(self, symbol: str) -> List[Dict]:
        v = await self.redis.get(f"levels:{symbol}")
        return json.loads(v) if v else []

    async def set_oi_data(self, symbol: str, data: Dict):
        await self.redis.setex(f"oi:{symbol}", 300, json.dumps(data, default=str))

    async def get_oi_data(self, symbol: str) -> Dict:
        v = await self.redis.get(f"oi:{symbol}")
        return json.loads(v) if v else {"oi": 0, "timestamp": None}

    async def set_funding_data(self, symbol: str, data: Dict):
        await self.redis.setex(f"funding:{symbol}", 600, json.dumps(data, default=str))

    async def get_funding_data(self, symbol: str) -> Dict:
        v = await self.redis.get(f"funding:{symbol}")
        return json.loads(v) if v else {"funding_rate": 0}

    async def update_volume_stats(self, symbol: str, buy: float, sell: float):
        data = {"buy": buy, "sell": sell, "timestamp": datetime.now().isoformat()}
        await self.redis.setex(f"volume:{symbol}", 60, json.dumps(data))

    async def get_volume_stats(self, symbol: str) -> Dict:
        v = await self.redis.get(f"volume:{symbol}")
        return json.loads(v) if v else {"buy": 0, "sell": 0}

    async def save_signal(self, symbol: str, signal: Dict):
        await self.redis.setex(f"signal:{symbol}", 3600, json.dumps(signal, default=str))

    async def get_active_signals(self) -> Dict:
        keys = await self.redis.keys("signal:*")
        out = {}
        for k in keys:
            v = await self.redis.get(k)
            if v:
                out[k.split(":", 1)[1]] = json.loads(v)
        return out

    async def get_current_price(self, symbol: str) -> Optional[float]:
        trades = await self.get_recent_trades(symbol, seconds=60)
        return trades[-1]["price"] if trades else None

    async def set_current_score(self, symbol: str, score: int):
        await self.redis.setex(f"score:{symbol}", 60, str(score))

    async def get_current_score(self, symbol: str) -> Optional[int]:
        v = await self.redis.get(f"score:{symbol}")
        return int(v) if v else None

    async def set_signal_memory(self, key: str, data: Dict):
        await self.redis.setex(f"signal_memory:{key}", 3600, json.dumps(data, default=str))

    async def get_signal_memory(self, key: str) -> Optional[Dict]:
        v = await self.redis.get(f"signal_memory:{key}")
        return json.loads(v) if v else None

    async def save_large_order(self, key: str, data: Dict):
        serializable = {k: v for k, v in data.items() if k != "history"}
        await self.redis.setex(f"order_track:{key}", 3600, json.dumps(serializable, default=str))

    async def delete_key(self, key: str):
        await self.redis.delete(key)

    async def set_aggression(self, symbol: str, data: Dict):
        await self.redis.setex(f"aggression:{symbol}", 60, json.dumps(data, default=str))

    async def get_aggression(self, symbol: str) -> Optional[Dict]:
        v = await self.redis.get(f"aggression:{symbol}")
        return json.loads(v) if v else None

    async def set_liquidity_analysis(self, symbol: str, data: Dict):
        await self.redis.setex(f"liquidity:{symbol}", 60, json.dumps(data, default=str))

    async def set_oi_analysis(self, symbol: str, data: Dict):
        await self.redis.setex(f"oi_analysis:{symbol}", 300, json.dumps(data, default=str))

    async def set_funding_analysis(self, symbol: str, data: Dict):
        await self.redis.setex(f"funding_analysis:{symbol}", 600, json.dumps(data, default=str))

    async def set_volume_analysis(self, symbol: str, data: Dict):
        await self.redis.setex(f"volume_analysis:{symbol}", 300, json.dumps(data, default=str))