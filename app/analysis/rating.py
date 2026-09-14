"""
Рейтинг 0..100 с плавными шкалами.

Идея:
- каждый компонент даёт от 0 до своего максимума (WEIGHTS из config),
- внутри компонента — плавная логарифмическая/линейная шкала,
- сумма = score,
- премия за confluence (совпадение факторов одного направления).
"""
from typing import Dict
from app.config import config


class RatingCalculator:

    async def calculate(
        self,
        symbol: str,
        orderbook: Dict,
        delta: Dict,
        cvd: float,
        absorption: Dict,
        levels: list,
        oi: Dict,
        funding: Dict,
        liquidity: Dict,
        volume_ratio: float,
    ) -> Dict:
        W = config.WEIGHTS
        comp = {}

        # ---------- LEVEL (0..20) ----------
        comp["level"] = self._level_score(orderbook, levels, W["level"])

        # ---------- ORDERBOOK (0..20) ----------
        comp["orderbook"] = self._orderbook_score(orderbook, liquidity, W["orderbook"])

        # ---------- TRADES / DELTA (0..15) ----------
        comp["trades"] = self._trades_score(delta, cvd, W["trades"])

        # ---------- ABSORPTION (0..20) ----------
        comp["absorption"] = self._absorption_score(absorption, W["absorption"])

        # ---------- OI (0..10) ----------
        comp["oi"] = self._oi_score(oi, W["oi"])

        # ---------- FUNDING (0..5) ----------
        comp["funding"] = self._funding_score(funding, W["funding"])

        # ---------- VOLUME (0..10) ----------
        comp["volume"] = self._volume_score(volume_ratio, W["volume"])

        total = int(round(sum(comp.values())))

        # ---------- DIRECTION ----------
        direction = self._direction(absorption, liquidity, delta, levels, orderbook)

        return {
            "total": min(total, 100),
            "components": comp,
            "direction": direction,
        }

    # ================================================================
    # LEVEL — 0..20
    # Чем ближе уровень к текущей цене и чем сильнее — тем больше балл.
    # ================================================================
    def _level_score(self, ob: Dict, levels: list, max_pts: int) -> float:
        if not levels or not ob or not ob.get("bids") or not ob.get("asks"):
            return 0.0

        try:
            mid = (float(ob["bids"][0][0]) + float(ob["asks"][0][0])) / 2
        except (TypeError, ValueError, IndexError):
            return 0.0
        if mid <= 0:
            return 0.0

        best = 0.0
        for lvl in levels[:5]:
            dist = abs(lvl["price"] - mid) / mid
            # 0% → 1.0, 2% → 0
            proximity = max(0.0, 1.0 - dist / 0.02)
            strength = lvl.get("strength", 0) / 100.0
            score = strength * proximity
            best = max(best, score)

        return round(best * max_pts, 2)

    # ================================================================
    # ORDERBOOK — 0..20
    # Имбалланс (0..10) + концентрация (0..4) + крупные заявки (0..6)
    # ================================================================
    def _orderbook_score(self, ob: Dict, liq: Dict, max_pts: int) -> float:
        if not ob:
            return 0.0

        score = 0.0

        # Imbalance
        total_bid = liq.get("total_bid", 0.0)
        total_ask = liq.get("total_ask", 0.0)
        total = total_bid + total_ask
        if total > 0:
            imbalance = abs(total_bid - total_ask) / total
            score += min(imbalance * 15, 10)

        # Концентрация топ-5
        conc = liq.get("concentration", 0.0)
        score += min(conc * 10, 4)

        # Крупные заявки
        large = liq.get("large_orders", [])
        extreme = sum(1 for o in large if o.get("category") == "extreme")
        very_large = sum(1 for o in large if o.get("category") == "very_large")
        normal_large = sum(1 for o in large if o.get("category") == "large")
        score += min(extreme * 2.0 + very_large * 1.5 + normal_large * 0.7, 6)

        return round(min(score, max_pts), 2)

    # ================================================================
    # TRADES / DELTA — 0..15
    # Плавная шкала по log10(|delta|).
    # ================================================================
    def _trades_score(self, delta: Dict, cvd: float, max_pts: int) -> float:
        import math

        # Дельта: $10k → 1 балл, $100k → 3, $1M → 6, $10M → 10
        d = abs(delta.get("delta", 0.0))
        if d < 10_000:
            delta_pts = 0.0
        else:
            delta_pts = min(math.log10(d / 10_000) * 2.5 + 1.0, 10.0)

        # CVD: $100k → 1, $10M → 5
        c = abs(cvd)
        if c < 100_000:
            cvd_pts = 0.0
        else:
            cvd_pts = min(math.log10(c / 100_000) * 1.7 + 1.0, 5.0)

        return round(min(delta_pts + cvd_pts, max_pts), 2)

    # ================================================================
    # ABSORPTION — 0..20
    # Если есть — то по confidence. Если нет — 0.
    # ================================================================
    def _absorption_score(self, absorption: Dict, max_pts: int) -> float:
        if not absorption or not absorption.get("detected"):
            return 0.0
        conf = absorption.get("confidence", 0)
        return round(min(conf / 100.0 * max_pts, max_pts), 2)

    # ================================================================
    # OI — 0..10
    # Log-шкала по |change_15m| %.
    # ================================================================
    def _oi_score(self, oi: Dict, max_pts: int) -> float:
        import math

        ch = abs(oi.get("change_15m", 0.0))
        if ch < 0.1:
            return 0.0
        # 0.1% → 1, 1% → 3, 5% → 7, 10%+ → 10
        return round(min(math.log10(ch * 10 + 1) * 4.0, max_pts), 2)

    # ================================================================
    # FUNDING — 0..5
    # Экстремальные значения — балл.
    # ================================================================
    def _funding_score(self, funding: Dict, max_pts: int) -> float:
        if funding.get("is_extreme"):
            return float(max_pts)
        pct = funding.get("percentile", 50.0)
        # Отклонение от центра
        dist = abs(pct - 50) / 50.0   # 0..1
        if dist < 0.3:
            return 0.0
        return round(min((dist - 0.3) / 0.7 * max_pts, max_pts), 2)

    # ================================================================
    # VOLUME — 0..10
    # 1.0× → 0, 2× → 3, 3× → 5, 5× → 8, 10× → 10
    # ================================================================
    def _volume_score(self, ratio: float, max_pts: int) -> float:
        import math

        if ratio <= 1.0:
            return 0.0
        return round(min(math.log2(ratio) * 3.3, max_pts), 2)

    # ================================================================
    # DIRECTION
    # ================================================================
    def _direction(self, absorption, liquidity, delta, levels, ob) -> str:
        # 1. Поглощение — приоритет
        if absorption and absorption.get("detected"):
            t = absorption.get("type", "")
            if "SELLER" in t:
                return "SHORT"
            if "BUYER" in t:
                return "LONG"

        # 2. Имбалланс стакана
        total_bid = liquidity.get("total_bid", 0.0)
        total_ask = liquidity.get("total_ask", 0.0)
        total = total_bid + total_ask
        if total > 0:
            imbalance = (total_bid - total_ask) / total
            if imbalance > 0.30:
                return "LONG"
            if imbalance < -0.30:
                return "SHORT"

        # 3. Дельта
        d = delta.get("delta", 0.0)
        if abs(d) > 1_000_000:
            return "LONG" if d > 0 else "SHORT"

        return "NEUTRAL"