import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from app.models import Signal, SignalState, SignalLevel, SignalType
from app.storage.redis import RedisStorage
from app.storage.postgres import PostgresStorage
from app.analysis import (
    LevelAnalyzer, LiquidityAnalyzer, ImbalanceAnalyzer,
    AggressionAnalyzer, AbsorptionDetector, SpoofingDetector,
    OIAnalyzer, FundingAnalyzer, VolumeAnalyzer, RatingCalculator
)
from app.signals.state import SignalStateMachine
from app.config import config
from app.utils.logger import logger

class SignalEngine:
    def __init__(self, redis: RedisStorage, postgres: PostgresStorage):
        self.redis = redis
        self.postgres = postgres
        
        # Initialize analyzers
        self.level_analyzer = LevelAnalyzer(None, redis)
        self.liquidity_analyzer = LiquidityAnalyzer(redis)
        self.imbalance_analyzer = ImbalanceAnalyzer(redis)
        self.aggression_analyzer = AggressionAnalyzer(redis)
        self.absorption_detector = AbsorptionDetector(redis)
        self.spoofing_detector = SpoofingDetector(redis)
        self.oi_analyzer = OIAnalyzer(redis, postgres)
        self.funding_analyzer = FundingAnalyzer(redis, postgres)
        self.volume_analyzer = VolumeAnalyzer(redis)
        self.rating_calculator = RatingCalculator()
        
        self.state_machine = SignalStateMachine()
        self.active_signals: Dict[str, Dict] = {}
        self.signal_memory: Dict[str, Dict] = {}
        self.running = False
        
        # Thresholds
        self.setup_threshold = 70
        self.confirmation_threshold = 80
        self.extreme_threshold = 90
        
    async def analyze_symbol(self, symbol: str) -> Optional[Signal]:
        """Full symbol analysis"""
        try:
            # Get data
            orderbook = await self.redis.get_orderbook(symbol)
            trades = await self.redis.get_recent_trades(symbol, minutes=5)
            
            if not orderbook or not trades:
                return None
            
            # Run all analyses
            levels = await self.level_analyzer.calculate_levels(symbol)
            liquidity = await self.liquidity_analyzer.analyze_liquidity(symbol, orderbook)
            imbalance = await self.imbalance_analyzer.calculate_imbalance(symbol, orderbook)
            aggression = await self.aggression_analyzer.analyze_aggression(symbol, trades)
            absorption = await self.absorption_detector.detect_absorption(symbol)
            spoofing = await self.spoofing_detector.detect_spoofing(symbol, orderbook)
            oi = await self.oi_analyzer.analyze_oi(symbol)
            funding = await self.funding_analyzer.analyze_funding(symbol)
            volume = await self.volume_analyzer.analyze_volume(symbol, trades)
            
            # Get current price
            current_price = await self.redis.get_current_price(symbol)
            if not current_price:
                return None
            
            # Find relevant levels
            relevant_levels = self._find_relevant_levels(levels, current_price)
            
            # Get CVD
            cvd = await self.redis.get_cvd(symbol)
            
            # Calculate rating with all components
            rating = await self.rating_calculator.calculate_rating(
                symbol=symbol,
                orderbook=orderbook,
                trades=trades,
                levels=levels,
                oi_data=oi,
                funding_data=funding,
                volume_data=volume,
                delta_data=await self.redis.get_delta(symbol),
                absorption=absorption,
                current_price=current_price,
                relevant_levels=relevant_levels,
                cvd=cvd,
                liquidity=liquidity,
                imbalance=imbalance,
                aggression=aggression,
                spoofing=spoofing
            )
            
            # Check signal conditions
            if rating['total'] >= self.setup_threshold:
                return await self._process_signal(symbol, rating, relevant_levels, 
                                                  absorption, spoofing, liquidity, current_price)
            
            # Check existing signals for confirmation
            await self._check_confirmation(symbol, rating, current_price)
            
            return None
            
        except Exception as e:
            logger.error(f"Error analyzing {symbol}: {e}")
            return None
    
    async def _process_signal(self, symbol: str, rating: Dict, levels: List[Dict],
                             absorption: Dict, spoofing: Dict, liquidity: Dict, 
                             current_price: float) -> Optional[Signal]:
        """Process and create signal"""
        direction = rating.get('direction', 'NEUTRAL')
        score = rating['total']
        
        # Determine signal level
        signal_level = self._get_signal_level(score)
        signal_type = SignalType.SETUP
        
        # Check if this is a confirmation
        key = f"{symbol}:{direction}"
        if key in self.signal_memory:
            last = self.signal_memory[key]
            if last['state'] in [SignalState.WATCH, SignalState.ABSORPTION]:
                # Check if score increased significantly
                if score - last['score'] >= 10:
                    signal_type = SignalType.CONFIRMATION
        
        # Check anti-spam
        if key in self.signal_memory:
            last = self.signal_memory[key]
            if (datetime.now() - last['timestamp']).total_seconds() < config.SIGNAL_COOLDOWN:
                if score - last['score'] < 10:
                    return None
        
        # Create message
        message = self._create_message(symbol, rating, levels, absorption, spoofing, liquidity, signal_type)
        
        # Create signal
        signal = Signal(
            symbol=symbol,
            direction=direction,
            level=levels[0]['price'] if levels else current_price,
            score=score,
            state=SignalState.NEW,
            signal_type=signal_type,
            timestamp=datetime.now(),
            factors=rating,
            message=message
        )
        
        # Save to memory
        self.signal_memory[key] = {
            'timestamp': datetime.now(),
            'score': score,
            'state': SignalState.NEW,
            'signal_type': signal_type
        }
        await self.redis.set_signal_memory(key, self.signal_memory[key])
        
        # Save to database
        signal_id = await self.postgres.save_signal(signal)
        
        # Send notification
        await self._send_signal(signal)
        
        return signal
    
    async def _check_confirmation(self, symbol: str, rating: Dict, current_price: float):
        """Check for confirmation of existing signals"""
        # Check if there's an active signal
        for key, data in self.signal_memory.items():
            if key.startswith(f"{symbol}:") and data['state'] in [SignalState.WATCH, SignalState.ABSORPTION]:
                # Check if price moved in expected direction
                direction = key.split(':')[1]
                score = rating['total']
                
                if direction == 'LONG' and rating.get('trend', 0) > 0 and score >= self.confirmation_threshold:
                    await self._update_signal(key, score, SignalState.CONFIRMATION, 'CONFIRMATION')
                
                elif direction == 'SHORT' and rating.get('trend', 0) < 0 and score >= self.confirmation_threshold:
                    await self._update_signal(key, score, SignalState.CONFIRMATION, 'CONFIRMATION')
    
    async def _update_signal(self, key: str, score: int, state: SignalState, signal_type: str):
        """Update existing signal"""
        if key in self.signal_memory:
            self.signal_memory[key]['score'] = score
            self.signal_memory[key]['state'] = state
            self.signal_memory[key]['signal_type'] = signal_type
            self.signal_memory[key]['timestamp'] = datetime.now()
            
            await self.redis.set_signal_memory(key, self.signal_memory[key])
            
            # Send confirmation notification
            message = self._create_confirmation_message(key, score)
            await self._send_notification(message)
    
    def _get_signal_level(self, score: int) -> SignalLevel:
        """Get signal level based on score"""
        if score >= 90:
            return SignalLevel.EXTREME
        elif score >= 80:
            return SignalLevel.STRONG
        elif score >= 70:
            return SignalLevel.WATCH
        elif score >= 60:
            return SignalLevel.INTERESTING
        return SignalLevel.NONE
    
    def _find_relevant_levels(self, levels: List[Dict], current_price: float) -> List[Dict]:
        """Find relevant levels near current price"""
        relevant = []
        for level in levels:
            distance = abs(level['price'] - current_price) / current_price
            if distance < 0.02:
                relevant.append(level)
        return sorted(relevant, key=lambda x: x['strength'], reverse=True)[:3]
    
    def _create_message(self, symbol: str, rating: Dict, levels: List[Dict],
                       absorption: Dict, spoofing: Dict, liquidity: Dict,
                       signal_type: SignalType) -> str:
        """Create formatted message"""
        score = rating['total']
        signal_level = self._get_signal_level(score)
        
        emojis = {
            SignalLevel.EXTREME: "🔴",
            SignalLevel.STRONG: "🔴",
            SignalLevel.WATCH: "🟠",
            SignalLevel.INTERESTING: "🟡",
            SignalLevel.NONE: "⚪"
        }
        emoji = emojis.get(signal_level, "⚪")
        
        type_label = "CONFIRMATION" if signal_type == SignalType.CONFIRMATION else "SETUP DETECTED"
        
        lines = [
            f"{emoji} {symbol} — {rating['direction']} {type_label}",
            "━━━━━━━━━━━━━━━━",
            f"Цена: {rating['current_price']:.2f}",
            f"Score: {score}/100",
        ]
        
        # Level information
        if levels:
            level = levels[0]
            lines.append(f"\n📊 УРОВЕНЬ")
            lines.append(f"  {level['price']:.2f}")
            lines.append(f"  Сила: {level['strength']:.0f}/100")
        
        # Orderbook
        lines.append(f"\n📖 СТАКАН")
        lines.append(f"  Ask: ${liquidity.get('total_ask_liquidity', 0)/1e6:.2f}M")
        lines.append(f"  Bid: ${liquidity.get('total_bid_liquidity', 0)/1e6:.2f}M")
        lines.append(f"  Imbalance: {rating.get('imbalance', 0):.0f}%")
        
        # Trades
        lines.append(f"\n⚡ СДЕЛКИ")
        lines.append(f"  Buy: ${rating.get('buy_volume', 0)/1e6:.2f}M")
        lines.append(f"  Sell: ${rating.get('sell_volume', 0)/1e6:.2f}M")
        lines.append(f"  Delta: ${rating.get('delta', 0)/1e6:.2f}M")
        lines.append(f"  CVD: ${rating.get('cvd', 0)/1e6:.2f}M")
        
        # Absorption
        if absorption and absorption.get('detected'):
            lines.append(f"\n🧱 ПОГЛОЩЕНИЕ")
            lines.append(f"  {absorption['type']}")
            lines.append(f"  Confidence: {absorption.get('details', {}).get('confidence', 0):.0f}%")
        
        # Spoofing
        if spoofing and spoofing.get('detected'):
            lines.append(f"\n⚠️ SPOOFING")
            lines.append(f"  Possible spoofing detected")
        
        # OI
        lines.append(f"\n📊 OI")
        lines.append(f"  {rating.get('oi_change', 0):.1f}% / 15m")
        lines.append(f"  {rating.get('oi_type', 'neutral')}")
        
        # Funding
        lines.append(f"\n💰 FUNDING")
        lines.append(f"  {rating.get('funding_rate', 0):.4f}%")
        
        # Volume
        lines.append(f"\n📈 VOLUME")
        lines.append(f"  {rating.get('volume_ratio', 0):.1f}× avg")
        
        # Aggression
        lines.append(f"\n🔥 AGGRESSION")
        lines.append(f"  {rating.get('aggression_type', 'neutral')}")
        lines.append(f"  Score: {rating.get('aggression_score', 0):.0f}")
        
        lines.append("━━━━━━━━━━━━━━━━")
        
        # Level description
        if signal_level == SignalLevel.EXTREME:
            lines.append("🔥 EXTREME - Множество факторов подтверждают")
        elif signal_level == SignalLevel.STRONG:
            lines.append("💪 STRONG - Сильная комбинация факторов")
        elif signal_level == SignalLevel.WATCH:
            lines.append("👀 WATCH - Стоит обратить внимание")
        
        # Components breakdown
        components = rating.get('components', {})
        lines.append(f"\n📊 Компоненты:")
        lines.append(f"  Level: {components.get('level', 0):.0f}/20")
        lines.append(f"  Orderbook: {components.get('orderbook', 0):.0f}/20")
        lines.append(f"  Trades: {components.get('trades', 0):.0f}/15")
        lines.append(f"  Absorption: {components.get('absorption', 0):.0f}/20")
        lines.append(f"  OI: {components.get('oi', 0):.0f}/10")
        lines.append(f"  Funding: {components.get('funding', 0):.0f}/5")
        lines.append(f"  Volume: {components.get('volume', 0):.0f}/10")
        
        lines.append("")
        lines.append("⚠️ Информационный сигнал.")
        lines.append("Не является рекомендацией открыть позицию.")
        
        return "\n".join(lines)
    
    def _create_confirmation_message(self, key: str, score: int) -> str:
        """Create confirmation message"""
        symbol, direction = key.split(':')
        return f"""
🔴 {symbol} — {direction} CONFIRMATION
━━━━━━━━━━━━━━━━
Score: {score}/100

✅ Подтверждение движения
⚠️ Информационный сигнал.
Не является рекомендацией открыть позицию.
        """
    
    async def _send_signal(self, signal: Signal):
        """Send signal"""
        from app.main import app
        
        if hasattr(app, 'telegram') and app.telegram:
            await app.telegram.send_notification(
                signal.message,
                [admin for admin in config.ADMIN_IDS]
            )
        
        logger.info(f"Signal sent: {signal.symbol} {signal.direction} Score: {signal.score}")
    
    async def _send_notification(self, message: str):
        """Send notification"""
        from app.main import app
        
        if hasattr(app, 'telegram') and app.telegram:
            await app.telegram.send_notification(
                message,
                [admin for admin in config.ADMIN_IDS]
            )
    
    async def start(self):
        """Start engine"""
        self.running = True
        logger.info("Signal engine started")
        asyncio.create_task(self._analysis_loop())
    
    async def stop(self):
        """Stop engine"""
        self.running = False
        logger.info("Signal engine stopped")
    
    async def _analysis_loop(self):
        """Main analysis loop"""
        while self.running:
            try:
                symbols = await self.redis.get_active_symbols()
                if not symbols:
                    await asyncio.sleep(10)
                    continue
                
                for symbol in symbols:
                    if not self.running:
                        break
                    await self.analyze_symbol(symbol)
                    await asyncio.sleep(0.5)
                
                await asyncio.sleep(5)
                
            except Exception as e:
                logger.error(f"Analysis loop error: {e}")
                await asyncio.sleep(5)