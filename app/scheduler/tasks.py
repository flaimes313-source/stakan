"""
Периодические задачи.
Все loops защищены от любых сбоев: при ошибке — sleep и continue,
никогда не выходят сами, кроме явного stop().
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
            asyncio.create_task(self._symbols_loop(), name="symbols_loop"),
            asyncio.create_task(self._oi_loop(), name="oi_loop"),
            asyncio.create_task(self._funding_loop(), name="funding_loop"),
            asyncio.create_task(self._candles_loop(), name="candles_loop"),
            asyncio.create_task(self._levels_loop(), name="levels_loop"),
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
                if not self.running:
                    break
                await self.app.market_data.refresh_symbols()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"symbols_loop: {e}")
                await asyncio.sleep(30)   # не выходим

    async def _oi_loop(self):
        while self.running:
            try:
                await asyncio.sleep(60)
                if not self.running:
                    break

                symbols = list(self.app.active_symbols)
                if not symbols:
                    logger.debug("oi_loop: пустой список символов")
                    continue

                ok, err = 0, 0
                for s in symbols:
                    if not self.running:
                        break
                    try:
                        data = await self.app.rest.get_oi(s)
                        if data and data.get("oi", 0) > 0:
                            await self.app.store.set_oi_data(s, data)
                            try:
                                await self.app.postgres.save_oi(s, data["oi"])
                                ok += 1
                            except Exception as e:
                                logger.debug(f"save_oi {s}: {e}")
                    except Exception as e:
                        err += 1
                        logger.debug(f"oi {s}: {e}")
                    await asyncio.sleep(0.1)

                logger.debug(f"oi_loop: ok={ok}, errors={err}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"oi_loop: {e}")
                await asyncio.sleep(15)   # не выходим

    async def _funding_loop(self):
        while self.running:
            try:
                await asyncio.sleep(300)
                if not self.running:
                    break

                symbols = list(self.app.active_symbols)
                if not symbols:
                    continue

                ok = 0
                for s in symbols:
                    if not self.running:
                        break
                    try:
                        data = await self.app.rest.get_funding(s)
                        if data:
                            await self.app.store.set_funding_data(s, data)
                            try:
                                await self.app.postgres.save_funding(
                                    s, data["funding_rate"], data.get("next_funding_time")
                                )
                                ok += 1
                            except Exception as e:
                                logger.debug(f"save_funding {s}: {e}")
                    except Exception as e:
                        logger.debug(f"funding {s}: {e}")
                    await asyncio.sleep(0.1)

                logger.debug(f"funding_loop: saved={ok}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"funding_loop: {e}")
                await asyncio.sleep(30)   # не выходим

    async def _candles_loop(self):
        while self.running:
            try:
                await asyncio.sleep(900)
                if not self.running:
                    break

                symbols = list(self.app.active_symbols)
                for s in symbols:
                    if not self.running:
                        break
                    try:
                        candles = await self.app.rest.get_klines(s, "60", limit=100)
                        for c in candles:
                            try:
                                await self.app.postgres.save_candle(s, "60", c)
                            except Exception:
                                pass
                    except Exception as e:
                        logger.debug(f"candles {s}: {e}")
                    await asyncio.sleep(0.2)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"candles_loop: {e}")
                await asyncio.sleep(30)   # не выходим

    async def _levels_loop(self):
        # Первый прогон — сразу, потом каждые 5 минут
        while self.running:
            try:
                symbols = list(self.app.active_symbols)
                for s in symbols:
                    if not self.running:
                        break
                    try:
                        await self.app.levels.update_levels_for_symbol(s)
                    except Exception as e:
                        logger.debug(f"levels {s}: {e}")
                    await asyncio.sleep(0.15)
                await asyncio.sleep(300)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"levels_loop: {e}")
                await asyncio.sleep(30)   # не выходим