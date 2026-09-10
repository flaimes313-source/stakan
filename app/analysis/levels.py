"""
Поиск технических уровней: фракталы + кластеризация по ATR.
"""
import asyncio
from typing import List, Dict
from datetime import datetime, timezone

import numpy as np

from app.api.bybit_rest import BybitRestAPI
from app.storage.store import Store
from app.storage.postgres import PostgresStorage
from app.config import config
from app.utils.logger import logger


class LevelAnalyzer:
    FRACTAL_K = 2          # окно фрактала
    MERGE_ATR = 0.35       # объединяем уровни в пределах 0.35 * ATR

    def __init__(self, rest: BybitRestAPI, store: Store, postgres: PostgresStorage):
        self.rest = rest
        self.store = store
        self.postgres = postgres

    async def calculate_levels(self, symbol: str) -> List[Dict]:
        try:
            all_levels: List[Dict] = []

            for tf, opts in config.TIMEFRAMES.items():
                klines = await self.rest.get_klines(symbol, tf, limit=opts["limit"])
                if len(klines) < 20:
                    continue
                levels = self._find_levels(klines, tf, opts["weight"])
                all_levels.extend(levels)

            if not all_levels:
                return []

            all_levels = self._merge(all_levels)
            all_levels = self._score(all_levels)
            all_levels.sort(key=lambda x: x["strength"], reverse=True)
            all_levels = all_levels[:20]

            await self.store.set_levels(symbol, all_levels)

            for lvl in all_levels[:10]:
                if lvl["strength"] >= 50:
                    try:
                        await self.postgres.save_level(symbol, lvl)
                    except Exception:
                        pass

            return all_levels

        except Exception as e:
            logger.error(f"calculate_levels {symbol}: {e}")
            return []

    # ========== Фракталы ==========

    def _find_levels(self, klines: List[Dict], timeframe: str, weight: int) -> List[Dict]:
        highs = np.array([k["high"] for k in klines], dtype=float)
        lows = np.array([k["low"] for k in klines], dtype=float)
        vols = np.array([k["volume"] for k in klines], dtype=float)

        # ATR
        atr = float(np.mean(np.abs(highs - lows)))
        if atr <= 0:
            return []

        out: List[Dict] = []
        k = self.FRACTAL_K
        for i in range(k, len(klines) - k):
            win_h = highs[i - k : i + k + 1]
            win_l = lows[i - k : i + k + 1]

            if highs[i] == win_h.max() and (win_h == highs[i]).sum() == 1:
                out.append({
                    "price": float(highs[i]),
                    "type": "resistance",
                    "timeframe": timeframe,
                    "weight": weight,
                    "timestamp": klines[i]["timestamp"],
                    "touches": 1,
                    "volume": float(vols[i]),
                    "atr": atr,
                })
            if lows[i] == win_l.min() and (win_l == lows[i]).sum() == 1:
                out.append({
                    "price": float(lows[i]),
                    "type": "support",
                    "timeframe": timeframe,
                    "weight": weight,
                    "timestamp": klines[i]["timestamp"],
                    "touches": 1,
                    "volume": float(vols[i]),
                    "atr": atr,
                })
        return out

    # ========== Кластеризация ==========

    def _merge(self, levels: List[Dict]) -> List[Dict]:
        if not levels:
            return []
        levels.sort(key=lambda x: x["price"])

        merged: List[Dict] = []
        cur = levels[0]
        for nxt in levels[1:]:
            threshold = self.MERGE_ATR * max(cur.get("atr", 0), nxt.get("atr", 0))
            if abs(nxt["price"] - cur["price"]) <= threshold:
                cur["touches"] += 1
                cur["volume"] += nxt["volume"]
                cur["weight"] = max(cur["weight"], nxt["weight"])
                if nxt["timestamp"] > cur["timestamp"]:
                    cur["timestamp"] = nxt["timestamp"]
                # тип оставляем тот, у которого больше touches совпадений по стороне
                if nxt["type"] == cur["type"]:
                    pass
                else:
                    # конфликт типов — решаем по количеству совпадений
                    pass
            else:
                merged.append(cur)
                cur = nxt
        merged.append(cur)
        return merged

    # ========== Сила уровня ==========

    def _score(self, levels: List[Dict]) -> List[Dict]:
        now = datetime.now(timezone.utc)
        for lvl in levels:
            strength = 0.0

            # касания: 0..25
            strength += min(lvl["touches"] * 5, 25)

            # вес ТФ: 0..25
            strength += min(lvl["weight"] * 5, 25)

            # объём: 0..25 (log-шкала, чтобы не съедал альтов)
            if lvl["volume"] > 0:
                strength += min(np.log10(lvl["volume"] + 1) * 4, 25)

            # свежесть: 0..25
            age_days = max((now - lvl["timestamp"].replace(tzinfo=timezone.utc)).total_seconds() / 86400, 0)
            if age_days < 1:
                strength += 25
            elif age_days < 3:
                strength += 20
            elif age_days < 7:
                strength += 15
            elif age_days < 30:
                strength += 8
            else:
                strength += 3

            lvl["strength"] = int(min(strength, 100))
        return levels

    async def update_levels_for_symbol(self, symbol: str):
        levels = await self.calculate_levels(symbol)
        logger.info(f"levels {symbol}: {len(levels)} найдено")