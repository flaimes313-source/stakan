"""
Периодические задачи:
- обновление Top-50 (1 ч)
- OI (60 сек) → Postgres
- Funding (5 мин) → Postgres
- свечи 1H (15 мин) → Postgres
- уровни (5 мин)
- чистка
"""
import asyncio
from typing import List

from app.config import config
from app.utils.logger import logger


class Scheduler:
    def __init__(self, app):
        self.app = app
        self.running = False
        self.tasks: List[asyncio.Task] = []

    async def start(self):
        self.running = True
        self.tasks = [
            asyncio.create_task(self._symbols_loop()),
            asyncio.create_task(self._oi_loop()),
            asyncio.create_task(self._funding_loop()),
            asyncio.create_task(self._candles_loop()),
            asyncio.create_task(self._levels_loop()),
        ]
        logger.info("Scheduler started")

    async def stop(self):
        self.running = False
        for t in self.tasks:
            t.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        logger.info("Scheduler stopped")

    # ========== LOOPS ==========

    async def _symbols_loop(self):
        while self.running:
            try:
                await asyncio.sleep(config.SYMBOLS_UPDATE_INTERVAL)
                await self.app.market_data.refresh_symbols()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"symbols_loop: {e}")

    async def _oi_loop(self):
        while self.running:
            try:
                await asyncio.sleep(60)
                for s in list(self.app.active_symbols):
                    if not self.running:
                        break
                    data = await self.app.rest.get_oi(s)
                    if data and data.get("oi", 0) > 0:
                        await self.app.store.set_oi_data(s, data)
                        try:
                            await self.app.postgres.save_oi(s, data["oi"])
                        except Exception as e:
                            logger.debug(f"save_oi {s}: {e}")
                    await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"oi_loop: {e}")

    async def _funding_loop(self):
        while self.running:
            try:
                await asyncio.sleep(300)
                for s in list(self.app.active_symbols):
                    if not self.running:
                        break
                    data = await self.app.rest.get_funding(s)
                    if data:
                        await self.app.store.set_funding_data(s, data)
                        try:
                            await self.app.postgres.save_funding(
                                s, data["funding_rate"], data.get("next_funding_time")
                            )
                        except Exception as e:
                            logger.debug(f"save_funding {s}: {e}")
                    await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"funding_loop: {e}")

    async def _candles_loop(self):
        while self.running:
            try:
                await asyncio.sleep(900)
                for s in list(self.app.active_symbols):
                    if not self.running:
                        break
                    candles = await self.app.rest.get_klines(s, "60", limit=100)
                    for c in candles:
                        try:
                            await self.app.postgres.save_candle(s, "60", c)
                        except Exception:
                            pass
                    await asyncio.sleep(0.2)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"candles_loop: {e}")

    async def _levels_loop(self):
        # Первый прогон — сразу, потом каждые 5 минут
        while self.running:
            try:
                for s in list(self.app.active_symbols):
                    if not self.running:
                        break
                    await self.app.levels.update_levels_for_symbol(s)
                    await asyncio.sleep(0.15)
                await asyncio.sleep(300)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"levels_loop: {e}")