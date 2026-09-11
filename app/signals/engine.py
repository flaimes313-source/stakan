"""
Signal Engine:
1. Берём живые данные из FileStore (стакан, сделки, дельта, CVD, OI, funding, уровни, объём).
2. Прогоняем анализаторы: absorption, liquidity, OI, funding, volume.
3. Считаем рейтинг.
4. Если total >= SIGNAL_THRESHOLD и memory разрешает — отправляем.

Направление сигнала определяется:
- в первую очередь через поглощение (absorption);
- если поглощения нет — через fallback:
  * сильный imbalance стакана (> 30%);
  * крупная дельта за 15м (> $1M).
"""
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional

from app.storage.store import Store
from app.storage.postgres import PostgresStorage
from app.analysis.absorption import AbsorptionDetector
from app.analysis.liquidity import LiquidityAnalyzer
from app.analysis.oi_analysis import OIAnalyzer
from app.analysis.funding_analysis import FundingAnalyzer
from app.analysis.rating import RatingCalculator
from app.datasets.trades import TradeAnalyzer
from app.signals.memory import SignalMemory
from app.models import Signal, SignalState, SignalType, SignalLevel
from app.config import config
from app.utils.logger import logger


class SignalEngine:
    def __init__(
        self,
        store: Store,
        postgres: PostgresStorage,
        trades: TradeAnalyzer,
    ):
        self.store = store
        self.postgres = postgres
        self.trades = trades

        self.absorption = AbsorptionDetector(store)
        self.liquidity = LiquidityAnalyzer(store)
        self.oi = OIAnalyzer(store, postgres)
        self.funding = FundingAnalyzer(postgres)
        self.rating = RatingCalculator()
        self.memory = SignalMemory(store)

        self.running = False
        self._notifier = None

        self._volume_avg: Dict[str, float] = {}

        # Пороги fallback
        self.FALLBACK_IMBALANCE = 0.30     # 30% перевес в стакане
        self.FALLBACK_DELTA_USD = 1_000_000  # $1M за 15м

    def set_notifier(self, notifier):
        self._notifier = notifier

    async def start(self):
        self.running = True
        await self.memory.load()
        logger.info("Signal engine started")
        asyncio.create_task(self._loop())

    async def stop(self):
        self.running = False
        logger.info("Signal engine stopped")

    # ========== Основной цикл ==========

    async def _loop(self):
        while self.running:
            try:
                symbols = await self.store.get_active_symbols()
                for symbol in symbols:
                    if not self.running:
                        break
                    try:
                        await self.analyze(symbol)
                    except Exception as e:
                        logger.error(f"analyze {symbol}: {e}")
                    await asyncio.sleep(0.05)
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"signal loop: {e}")
                await asyncio.sleep(5)

    # ========== Анализ одного символа ==========

    async def analyze(self, symbol: str) -> Optional[Signal]:
        ob = await self.store.get_orderbook(symbol)
        if not ob or not ob.get("bids") or not ob.get("asks"):
            return None

        await self.trades.update_cvd_from_trades(symbol)
        cvd = await self.trades.get_cvd(symbol)
        delta = await self.trades.delta_window(symbol, seconds=900)

        absorption = await self.absorption.detect(symbol)
        liquidity = await self.liquidity.analyze(symbol)
        levels = await self.store.get_levels(symbol)
        oi = await self.oi.analyze(symbol)

        funding_data = await self.store.get_funding_data(symbol)
        funding = await self.funding.analyze(symbol, funding_data.get("funding_rate", 0))

        volume_ratio = await self._volume_ratio(symbol)

        rating = await self.rating.calculate(
            symbol=symbol,
            orderbook=ob,
            delta=delta,
            cvd=cvd,
            absorption=absorption,
            levels=levels,
            oi=oi,
            funding=funding,
            liquidity=liquidity,
            volume_ratio=volume_ratio,
        )

        total = rating["total"]
        await self.store.set_current_score(symbol, total)

        if total < config.SIGNAL_THRESHOLD:
            return None

        # ===== ОПРЕДЕЛЕНИЕ НАПРАВЛЕНИЯ =====
        direction = rating["direction"]

        # Fallback 1: сильный imbalance стакана
        if direction == "NEUTRAL":
            liq_total = liquidity.get("total_bid", 0) + liquidity.get("total_ask", 0)
            if liq_total > 0:
                imbalance_pct = (liquidity["total_bid"] - liquidity["total_ask"]) / liq_total
                if imbalance_pct > self.FALLBACK_IMBALANCE:
                    direction = "LONG"
                    logger.debug(f"{symbol}: direction=LONG (imbalance {imbalance_pct:.2f})")
                elif imbalance_pct < -self.FALLBACK_IMBALANCE:
                    direction = "SHORT"
                    logger.debug(f"{symbol}: direction=SHORT (imbalance {imbalance_pct:.2f})")

        # Fallback 2: крупная дельта
        if direction == "NEUTRAL" and abs(delta.get("delta", 0)) > self.FALLBACK_DELTA_USD:
            direction = "LONG" if delta["delta"] > 0 else "SHORT"
            logger.debug(f"{symbol}: direction={direction} (delta {delta['delta']:+,.0f})")

        if direction == "NEUTRAL":
            return None

        level_price = 0.0
        if levels:
            level_price = levels[0]["price"]

        allowed = await self.memory.should_send(symbol, direction, total, level_price)
        if not allowed:
            return None

        message = self._format_message(
            symbol=symbol,
            direction=direction,
            rating=rating,
            ob=ob,
            delta=delta,
            cvd=cvd,
            absorption=absorption,
            levels=levels,
            oi=oi,
            funding=funding,
            liquidity=liquidity,
            volume_ratio=volume_ratio,
        )

        signal = Signal(
            symbol=symbol,
            direction=direction,
            level=level_price,
            score=total,
            state=SignalState.NEW,
            signal_type=SignalType.SETUP,
            factors=rating["components"],
            message=message,
        )

        if self._notifier:
            await self._notifier.send(message)

        try:
            await self.postgres.save_signal(signal)
        except Exception as e:
            logger.debug(f"save_signal: {e}")

        await self.store.save_signal(symbol, {
            "symbol": symbol,
            "direction": direction,
            "score": total,
            "ts": datetime.now().isoformat(),
        })

        await self.memory.remember(symbol, direction, total, level_price, message)
        logger.info(f"🔔 SIGNAL {symbol} {direction} score={total}")
        return signal

    # ========== Объём ==========

    async def _volume_ratio(self, symbol: str) -> float:
        trades_1m = await self.store.get_recent_trades(symbol, seconds=60)
        trades_1h = await self.store.get_recent_trades(symbol, seconds=3600)

        if not trades_1m:
            return 0.0

        vol_1m = sum(t["notional"] for t in trades_1m)
        avg_1m = sum(t["notional"] for t in trades_1h) / 60 if trades_1h else 0
        if avg_1m <= 0:
            return 0.0
        return vol_1m / avg_1m

    # ========== Форматирование ==========

    def _format_message(
        self,
        symbol: str,
        direction: str,
        rating: Dict,
        ob: Dict,
        delta: Dict,
        cvd: float,
        absorption: Dict,
        levels: list,
        oi: Dict,
        funding: Dict,
        liquidity: Dict,
        volume_ratio: float,
    ) -> str:
        total = rating["total"]
        if total >= 90:
            emoji = "🔴"
            tag = "EXTREME"
        elif total >= 80:
            emoji = "🔴"
            tag = "STRONG"
        elif total >= 70:
            emoji = "🟠"
            tag = "WATCH"
        else:
            emoji = "🟡"
            tag = "INTERESTING"

        lines = [
            f"{emoji} {symbol} — {direction} {tag}",
            "━━━━━━━━━━━━━━━━",
        ]

        if ob and ob.get("bids") and ob.get("asks"):
            mid = (float(ob["bids"][0][0]) + float(ob["asks"][0][0])) / 2
            lines.append(f"Цена: {mid:.6g}")

        if levels:
            lvl = levels[0]
            lines.append(f"Уровень: {lvl['price']:.6g} | Сила {lvl['strength']}/100 ({lvl['timeframe']})")

        lines.append("")
        lines.append("📖 СТАКАН")
        lines.append(f"  Bid: ${liquidity['total_bid']:,.0f}")
        lines.append(f"  Ask: ${liquidity['total_ask']:,.0f}")

        lines.append("")
        lines.append("⚡ СДЕЛКИ (15м)")
        lines.append(f"  Buy: ${delta['buy']:,.0f}")
        lines.append(f"  Sell: ${delta['sell']:,.0f}")
        lines.append(f"  Delta: ${delta['delta']:+,.0f}")
        lines.append(f"  CVD: ${cvd:+,.0f}")

        if absorption.get("detected"):
            lines.append("")
            lines.append(f"🧱 ПОГЛОЩЕНИЕ: {absorption['type']}")
            lines.append(f"  Confidence: {absorption['confidence']}%")

        lines.append("")
        lines.append(f"📊 OI: {oi['change_15m']:+.2f}% / 15м")
        lines.append(f"💰 Funding: {funding['funding_rate']*100:.4f}% (pct={funding['percentile']:.0f})")
        lines.append(f"📈 Volume: {volume_ratio:.2f}× avg-1m")

        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━")
        comp = rating["components"]
        lines.append(f"SCORE: {total}/100")
        lines.append(f"  level={comp['level']} ob={comp['orderbook']} trades={comp['trades']}")
        lines.append(f"  abs={comp['absorption']} oi={comp['oi']} fund={comp['funding']} vol={comp['volume']}")
        lines.append("")
        lines.append("⚠️ Информационный сигнал. Не является рекомендацией.")
        return "\n".join(lines)