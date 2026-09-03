from typing import Dict, List, Any
from app.config import config
from app.utils.logger import logger

class RatingCalculator:
    """Расчет рейтинга 0-100 с точными весами"""
    
    def __init__(self):
        self.weights = {
            'level': 20,
            'orderbook': 20,
            'trades': 15,
            'absorption': 20,
            'oi': 10,
            'funding': 5,
            'volume': 10
        }
        
    async def calculate_rating(self, symbol: str, orderbook: Dict, trades: List[Dict],
                              levels: List[Dict], oi_data: Dict, funding_data: Dict,
                              volume_data: Dict, delta_data: float, absorption: Dict,
                              current_price: float, relevant_levels: List[Dict],
                              cvd: float = 0, liquidity: Dict = None, 
                              imbalance: Dict = None, aggression: Dict = None,
                              spoofing: Dict = None) -> Dict:
        """Calculate comprehensive rating 0-100"""
        
        total_score = 0
        components = {}
        
        # 1. LEVEL (0-20)
        level_score = await self._calculate_level_score(relevant_levels)
        components['level'] = level_score
        total_score += level_score
        
        # 2. ORDERBOOK (0-20)
        orderbook_score = await self._calculate_orderbook_score(orderbook, liquidity, imbalance)
        components['orderbook'] = orderbook_score
        total_score += orderbook_score
        
        # 3. TRADES / DELTA (0-15)
        trades_score = await self._calculate_trades_score(trades, delta_data, cvd)
        components['trades'] = trades_score
        total_score += trades_score
        
        # 4. ABSORPTION (0-20)
        absorption_score = await self._calculate_absorption_score(absorption)
        components['absorption'] = absorption_score
        total_score += absorption_score
        
        # 5. OI (0-10)
        oi_score = await self._calculate_oi_score(oi_data)
        components['oi'] = oi_score
        total_score += oi_score
        
        # 6. FUNDING (0-5)
        funding_score = await self._calculate_funding_score(funding_data)
        components['funding'] = funding_score
        total_score += funding_score
        
        # 7. VOLUME (0-10)
        volume_score = await self._calculate_volume_score(volume_data)
        components['volume'] = volume_score
        total_score += volume_score
        
        # Cap at 100
        total_score = min(total_score, 100)
        
        # Determine direction and trend
        direction, trend = await self._determine_trend(
            orderbook, trades, absorption, oi_data, delta_data
        )
        
        # OI type
        oi_type = self._determine_oi_type(oi_data)
        
        return {
            'total': total_score,
            'components': components,
            'direction': direction,
            'trend': trend,
            'current_price': current_price,
            'ask_volume': orderbook_score * 0.1 if orderbook else 0,
            'bid_volume': orderbook_score * 0.1 if orderbook else 0,
            'imbalance': imbalance.get('imbalance', 0) if imbalance else 0,
            'buy_volume': trades_score * 0.1 if trades else 0,
            'sell_volume': trades_score * 0.1 if trades else 0,
            'delta': delta_data,
            'cvd': cvd,
            'oi_change': oi_data.get('change_15m', 0),
            'oi_type': oi_type,
            'funding_rate': funding_data.get('funding_rate', 0),
            'volume_ratio': volume_data.get('volume_ratio', 1),
            'aggression_type': aggression.get('type', 'neutral') if aggression else 'neutral',
            'aggression_score': aggression.get('aggression_score', 0) if aggression else 0
        }
    
    async def _calculate_level_score(self, levels: List[Dict]) -> float:
        """Уровни: 0-20"""
        if not levels:
            return 0
        
        # Take the strongest level
        strongest = levels[0]
        strength = strongest.get('strength', 0)
        
        # Convert strength (0-100) to score (0-20)
        return min(strength / 5, 20)
    
    async def _calculate_orderbook_score(self, orderbook: Dict, liquidity: Dict, imbalance: Dict) -> float:
        """Стакан: 0-20"""
        if not orderbook:
            return 0
        
        score = 0
        
        # 1. Liquidity concentration (0-10)
        if liquidity:
            concentration = liquidity.get('liquidity_concentration', 0)
            score += min(concentration * 15, 10)  # Max 10
        
        # 2. Large orders (0-5)
        if liquidity:
            large_orders = liquidity.get('large_orders', [])
            if large_orders:
                extreme = sum(1 for o in large_orders if o.get('category') == 'extreme')
                very_large = sum(1 for o in large_orders if o.get('category') == 'very_large')
                score += min(extreme * 2 + very_large * 1, 5)
        
        # 3. Imbalance (0-5)
        if imbalance:
            imb = abs(imbalance.get('imbalance', 0))
            score += min(imb / 10, 5)
        
        return min(score, 20)
    
    async def _calculate_trades_score(self, trades: List[Dict], delta: float, cvd: float) -> float:
        """Сделки/Дельта: 0-15"""
        if not trades:
            return 0
        
        score = 0
        
        # 1. Delta magnitude (0-8)
        delta_abs = abs(delta)
        if delta_abs > 1000000:  # > $1M
            score += 8
        elif delta_abs > 500000:
            score += 6
        elif delta_abs > 200000:
            score += 4
        elif delta_abs > 100000:
            score += 2
        
        # 2. CVD change (0-7)
        cvd_abs = abs(cvd)
        if cvd_abs > 5000000:  # > $5M
            score += 7
        elif cvd_abs > 2000000:
            score += 5
        elif cvd_abs > 1000000:
            score += 3
        elif cvd_abs > 500000:
            score += 1
        
        return min(score, 15)
    
    async def _calculate_absorption_score(self, absorption: Dict) -> float:
        """Поглощение: 0-20"""
        if not absorption or not absorption.get('detected', False):
            return 0
        
        confidence = absorption.get('details', {}).get('confidence', 0)
        
        # Scale: confidence 0-100 -> score 0-20
        score = (confidence / 100) * 20
        
        # Bonus for confirmed absorption
        if absorption.get('confirmed', False):
            score += 5
        
        return min(score, 20)
    
    async def _calculate_oi_score(self, oi_data: Dict) -> float:
        """OI: 0-10"""
        oi_change = oi_data.get('change_15m', 0)
        oi_abs = abs(oi_change)
        
        if oi_abs < 1:
            return 0
        
        # Scale: 0-10 based on OI change
        if oi_abs > 10:
            return 10
        elif oi_abs > 5:
            return 8
        elif oi_abs > 3:
            return 6
        elif oi_abs > 1:
            return 4
        
        return 0
    
    async def _calculate_funding_score(self, funding_data: Dict) -> float:
        """Funding: 0-5"""
        funding_rate = funding_data.get('funding_rate', 0)
        
        # Check if extreme
        if funding_data.get('is_extreme', False):
            return 5
        
        # Normal scaling
        funding_abs = abs(funding_rate)
        if funding_abs > 0.01:  # > 1%
            return 5
        elif funding_abs > 0.005:
            return 4
        elif funding_abs > 0.002:
            return 3
        elif funding_abs > 0.001:
            return 2
        
        return 0
    
    async def _calculate_volume_score(self, volume_data: Dict) -> float:
        """Объем: 0-10"""
        volume_ratio = volume_data.get('volume_ratio', 0)
        
        if volume_ratio < 1:
            return 0
        
        # Scale: 0-10 based on volume ratio
        if volume_ratio > 5:
            return 10
        elif volume_ratio > 4:
            return 8
        elif volume_ratio > 3:
            return 6
        elif volume_ratio > 2:
            return 4
        elif volume_ratio > 1.5:
            return 2
        
        return 0
    
    async def _determine_trend(self, orderbook: Dict, trades: List[Dict], 
                              absorption: Dict, oi_data: Dict, delta: float) -> tuple:
        """Определить направление и силу тренда"""
        direction = 'NEUTRAL'
        trend = 0
        
        # 1. Check absorption (highest priority)
        if absorption and absorption.get('detected', False):
            if 'SELLER_ABSORPTION' in absorption.get('type', ''):
                direction = 'SHORT'
                trend = -1
            elif 'BUYER_ABSORPTION' in absorption.get('type', ''):
                direction = 'LONG'
                trend = 1
        
        # 2. Check orderbook imbalance
        if orderbook:
            bids = orderbook.get('bids', [])
            asks = orderbook.get('asks', [])
            
            if bids and asks:
                bid_volume = sum(b[1] for b in bids[:5])
                ask_volume = sum(a[1] for a in asks[:5])
                
                if bid_volume > ask_volume * 2:
                    if direction == 'NEUTRAL':
                        direction = 'LONG'
                        trend = 0.5
                elif ask_volume > bid_volume * 2:
                    if direction == 'NEUTRAL':
                        direction = 'SHORT'
                        trend = -0.5
        
        # 3. Check delta
        if abs(delta) > 100000:
            if delta > 0 and direction == 'NEUTRAL':
                direction = 'LONG'
                trend = 0.3
            elif delta < 0 and direction == 'NEUTRAL':
                direction = 'SHORT'
                trend = -0.3
        
        # 4. Check OI + Price combination
        oi_change = oi_data.get('change_15m', 0)
        price_change = oi_data.get('price_change', 0)
        
        if price_change > 0 and oi_change > 0:
            # Bullish confirmation
            if direction == 'NEUTRAL':
                direction = 'LONG'
                trend = 0.4
        elif price_change < 0 and oi_change > 0:
            # Bearish confirmation
            if direction == 'NEUTRAL':
                direction = 'SHORT'
                trend = -0.4
        
        return direction, trend
    
    def _determine_oi_type(self, oi_data: Dict) -> str:
        """Определить тип движения OI"""
        price_change = oi_data.get('price_change', 0)
        oi_change = oi_data.get('change_15m', 0)
        
        if price_change > 0 and oi_change > 0:
            return 'bullish_confirmation'
        elif price_change < 0 and oi_change > 0:
            return 'bearish_confirmation'
        elif price_change > 0 and oi_change < 0:
            return 'short_covering'
        elif price_change < 0 and oi_change < 0:
            return 'long_liquidation'
        else:
            return 'neutral'