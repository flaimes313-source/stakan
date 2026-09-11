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
        # Проверка, что список символов уже есть
        logger.info(f"Scheduler: active_symbols={len(self.app.active_symbols)}")

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
                logger.info(f"symbols_loop: обновлено {len(self.app.active_symbols)} символов")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"symbols_loop: {e}")
                await asyncio.sleep(30)

    async def _oi_loop(self):
        logger.info("oi_loop: старт")
        while self.running:
            try:
                await asyncio.sleep(60)
                if not self.running:
                    break

                symbols = list(self.app.active_symbols)
                if not symbols:
                    logger.warning("oi_loop: пустой список символов")
                    continue

                logger.info(f"oi_loop: начало цикла по {len(symbols)} символам")

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
                                logger.warning(f"save_oi {s}: {e}")
                        else:
                            err += 1
                            logger.warning(f"oi_loop: пустой ответ для {s}")
                    except Exception as e:
                        err += 1
                        logger.warning(f"oi_loop: {s}: {e}")
                    await asyncio.sleep(0.1)

                logger.info(f"oi_loop: ok={ok}, errors={err}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"oi_loop: {e}")
                await asyncio.sleep(15)

    async def _funding_loop(self):
        logger.info("funding_loop: старт")
        while self.running:
            try:
                await asyncio.sleep(300)
                if not self.running:
                    break

                symbols = list(self.app.active_symbols)
                if not symbols:
                    logger.warning("funding_loop: пустой список символов")
                    continue

                logger.info(f"funding_loop: начало цикла по {len(symbols)} символам")

                ok, err = 0, 0
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
                                logger.warning(f"save_funding {s}: {e}")
                        else:
                            err += 1
                    except Exception as e:
                        err += 1
                        logger.warning(f"funding_loop: {s}: {e}")
                    await asyncio.sleep(0.1)

                logger.info(f"funding_loop: ok={ok}, errors={err}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"funding_loop: {e}")
                await asyncio.sleep(30)

    async def _candles_loop(self):
        while self.running:
            try:
                await asyncio.sleep(900)
                if not self.running:
                    break

                symbols = list(self.app.active_symbols)
                ok = 0
                for s in symbols:
                    if not self.running:
                        break
                    try:
                        candles = await self.app.rest.get_klines(s, "60", limit=100)
                        for c in candles:
                            try:
                                await self.app.postgres.save_candle(s, "60", c)
                                ok += 1
                            except Exception:
                                pass
                    except Exception as e:
                        logger.warning(f"candles_loop: {s}: {e}")
                    await asyncio.sleep(0.2)
                logger.info(f"candles_loop: сохранено {ok} свечей")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"candles_loop: {e}")
                await asyncio.sleep(30)

    async def _levels_loop(self):
        while self.running:
            try:
                symbols = list(self.app.active_symbols)
                if not symbols:
                    logger.warning("levels_loop: пустой список символов")
                    await asyncio.sleep(30)
                    continue

                ok = 0
                for s in symbols:
                    if not self.running:
                        break
                    try:
                        await self.app.levels.update_levels_for_symbol(s)
                        ok += 1
                    except Exception as e:
                        logger.warning(f"levels_loop: {s}: {e}")
                    await asyncio.sleep(0.15)
                logger.info(f"levels_loop: обновлено {ok} монет")
                await asyncio.sleep(300)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"levels_loop: {e}")
                await asyncio.sleep(30)