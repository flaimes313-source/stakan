"""
Bybit V5 публичный REST.
Ключи не требуются.
"""
import asyncio
from typing import List, Dict, Optional
from datetime import datetime

import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.config import config
from app.utils.logger import logger


class BybitRestAPI:
    def __init__(self):
        self.base_url = config.BYBIT_REST_URL
        self._session: Optional[aiohttp.ClientSession] = None

    async def start(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=20)
            )

    async def stop(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)),
        reraise=True,
    )
    async def _get(self, endpoint: str, params: Dict) -> Dict:
        await self.start()
        url = f"{self.base_url}{endpoint}"
        async with self._session.get(url, params=params) as resp:
            data = await resp.json()
            if data.get("retCode") != 0:
                logger.warning(f"Bybit API error {endpoint}: {data.get('retMsg')}")
                return {}
            return data.get("result", {}) or {}

    # ========== ТИКЕРЫ ==========

    async def get_all_tickers(self) -> List[Dict]:
        """Все линейные тикеры (публичные)."""
        try:
            result = await self._get(
                "/v5/market/tickers", {"category": "linear"}
            )
            return result.get("list", []) or []
        except Exception as e:
            logger.error(f"get_all_tickers failed: {e}")
            return []

    async def get_top_symbols(self, limit: int = 50) -> List[str]:
        """
        Top-N USDT-перпетуалов по 24h обороту.
        Берём только те, у которых turnover24h доступен.
        """
        tickers = await self.get_all_tickers()
        if not tickers:
            logger.warning("Нет тикеров от Bybit — пустой список")
            return []

        rows = []
        for t in tickers:
            symbol = t.get("symbol", "")
            if not symbol.endswith("USDT"):
                continue
            try:
                turnover = float(t.get("turnover24h", 0) or 0)
                last_price = float(t.get("lastPrice", 0) or 0)
            except (TypeError, ValueError):
                continue
            if turnover <= 0 or last_price <= 0:
                continue
            rows.append((symbol, turnover))

        rows.sort(key=lambda x: x[1], reverse=True)
        symbols = [s for s, _ in rows[:limit]]
        logger.info(f"Top-{limit} символов получено (по turnover24h)")
        return symbols

    # ========== СВЕЧИ ==========

    async def get_klines(self, symbol: str, interval: str, limit: int = 200) -> List[Dict]:
        try:
            result = await self._get(
                "/v5/market/kline",
                {
                    "category": "linear",
                    "symbol": symbol,
                    "interval": interval,
                    "limit": limit,
                },
            )
        except Exception as e:
            logger.debug(f"get_klines {symbol} {interval} failed: {e}")
            return []

        raw = result.get("list", []) or []
        out = []
        for row in raw:
            try:
                out.append({
                    "timestamp": datetime.fromtimestamp(int(row[0]) / 1000),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                    "turnover": float(row[6]),
                })
            except (ValueError, IndexError):
                continue
        # Bybit отдаёт от новых к старым — перевернём для удобства
        out.reverse()
        return out

    # ========== OI ==========

    async def get_oi(self, symbol: str) -> Optional[Dict]:
        """
        Открытый интерес на 5-минутном интервале.
        Возвращает: {"oi": float, "timestamp": datetime}
        """
        try:
            result = await self._get(
                "/v5/market/open-interest",
                {
                    "category": "linear",
                    "symbol": symbol,
                    "intervalTime": "5min",
                    "limit": 1,
                },
            )
        except Exception as e:
            logger.debug(f"get_oi {symbol} failed: {e}")
            return None

        rows = result.get("list", []) or []
        if not rows:
            return None

        try:
            oi = float(rows[0].get("openInterest", 0))
        except (TypeError, ValueError):
            return None

        return {"oi": oi, "timestamp": datetime.now()}

    # ========== FUNDING ==========

    async def get_funding(self, symbol: str) -> Optional[Dict]:
        """
        Текущий funding rate.
        Bybit отдаёт в виде десятичной дроби (0.0001 = 0.01%).
        """
        try:
            result = await self._get(
                "/v5/market/tickers",
                {"category": "linear", "symbol": symbol},
            )
        except Exception as e:
            logger.debug(f"get_funding {symbol} failed: {e}")
            return None

        rows = result.get("list", []) or []
        if not rows:
            return None
        t = rows[0]
        try:
            rate = float(t.get("fundingRate", 0) or 0)
            next_ts = int(t.get("nextFundingTime", 0) or 0)
        except (TypeError, ValueError):
            return None

        return {
            "funding_rate": rate,                       # десятичная дробь
            "next_funding_time": datetime.fromtimestamp(next_ts / 1000) if next_ts else None,
            "timestamp": datetime.now(),
        }