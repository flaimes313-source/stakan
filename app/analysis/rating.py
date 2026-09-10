"""
Рейтинг 0..100 с реальными данными.
"""
from typing import Dict, Any
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
        components = {}

        # LEVEL
        level_score = 0.0
        if levels:
            lvl = levels[0]
            # Учитываем, насколько близко к цене
            if orderbook and orderbook.get("bids"):
                mid = (float(orderbook["bids"][0][0]) + float(orderbook["asks"][0][0])) / 2
                if mid > 0:
                    dist = abs(lvl["price"] - mid) / mid
                    proximity = max(0.0, 1.0 - dist / 0.02)   # 2% = 0
                    level_score = min(lvl["strength"] / 100 * 20 * (0.4 + 0.6 * proximity), 20)
        components["level"] = round(level_score, 1)

        # ORDERBOOK
        ob_score = 0.0
        if orderbook:
            total_bid = liquidity.get("total_bid", 0)
            total_ask = liquidity.get("total_ask", 0)
            total = total_bid + total_ask
            if total > 0:
                imbalance = abs(total_bid - total_ask) / total
                ob_score += min(imbalance * 10, 10)
            conc = liquidity.get("concentration", 0)
            ob_score += min(conc * 10, 5)
            large_orders = liquidity.get("large_orders", [])
            extreme = sum(1 for o in large_orders if o["category"] == "extreme")
            very_large = sum(1 for o in large_orders if o["category"] == "very_large")
            ob_score += min(extreme * 2 + very_large * 1, 5)
        components["orderbook"] = round(min(ob_score, 20), 1)

        # TRADES / DELTA
        trades_score = 0.0
        delta_abs = abs(delta.get("delta", 0))
        if delta_abs > 2_000_000:
            trades_score += 8
        elif delta_abs > 500_000:
            trades_score += 6
        elif delta_abs > 100_000:
            trades_score += 4
        elif delta_abs > 20_000:
            trades_score += 2

        cvd_abs = abs(cvd)
        if cvd_abs > 5_000_000:
            trades_score += 7
        elif cvd_abs > 2_000_000:
            trades_score += 5
        elif cvd_abs > 500_000:
            trades_score += 3
        elif cvd_abs > 100_000:
            trades_score += 1
        components["trades"] = round(min(trades_score, 15), 1)

        # ABSORPTION
        absorption_score = 0.0
        if absorption.get("detected"):
            conf = absorption.get("confidence", 0)
            absorption_score = min(conf / 100 * 20, 20)
        components["absorption"] = round(absorption_score, 1)

        # OI
        oi_score = 0.0
        oi_change = abs(oi.get("change_15m", 0))
        if oi_change > 10:
            oi_score = 10
        elif oi_change > 5:
            oi_score = 8
        elif oi_change > 3:
            oi_score = 6
        elif oi_change > 1:
            oi_score = 4
        elif oi_change > 0.3:
            oi_score = 2
        components["oi"] = round(oi_score, 1)

        # FUNDING
        funding_score = 0.0
        if funding.get("is_extreme"):
            funding_score = 5
        else:
            pct = funding.get("percentile", 50)
            if pct >= 85 or pct <= 15:
                funding_score = 3
            elif pct >= 70 or pct <= 30:
                funding_score = 1
        components["funding"] = round(funding_score, 1)

        # VOLUME
        volume_score = 0.0
        if volume_ratio >= 5:
            volume_score = 10
        elif volume_ratio >= 3:
            volume_score = 8
        elif volume_ratio >= 2:
            volume_score = 6
        elif volume_ratio >= 1.5:
            volume_score = 3
        elif volume_ratio >= 1.2:
            volume_score = 1
        components["volume"] = round(volume_score, 1)

        total = int(round(sum(components.values())))

        # direction
        direction = "NEUTRAL"
        if absorption.get("detected"):
            if "SELLER" in absorption.get("type", ""):
                direction = "SHORT"
            elif "BUYER" in absorption.get("type", ""):
                direction = "LONG"

        return {
            "total": min(total, 100),
            "components": components,
            "direction": direction,
        }