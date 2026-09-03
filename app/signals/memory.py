from typing import Dict, List, Optional
from datetime import datetime, timedelta
from app.models import Signal
from app.storage.redis import RedisStorage
from app.utils.logger import logger

class SignalMemory:
    """Память сигналов для антиспама"""
    
    def __init__(self, redis: RedisStorage):
        self.redis = redis
        self.signals: Dict[str, Dict] = {}
        self.cooldown = 600  # 10 минут
        
    async def remember(self, signal: Signal) -> bool:
        """Запомнить сигнал"""
        key = f"{signal.symbol}:{signal.direction}"
        
        # Проверяем, есть ли уже такой сигнал
        if key in self.signals:
            last = self.signals[key]
            
            # Проверяем cooldown
            if (datetime.now() - last['timestamp']).total_seconds() < self.cooldown:
                # Проверяем, значительно ли улучшился скор
                if signal.score - last['score'] < 10:
                    return False
            
            # Обновляем
            self.signals[key].update({
                'score': signal.score,
                'state': signal.state,
                'timestamp': datetime.now(),
                'message': signal.message
            })
        else:
            # Новый сигнал
            self.signals[key] = {
                'symbol': signal.symbol,
                'direction': signal.direction,
                'score': signal.score,
                'state': signal.state,
                'timestamp': datetime.now(),
                'message': signal.message,
                'first_seen': datetime.now()
            }
        
        # Сохраняем в Redis
        await self.redis.save_signal(key, self.signals[key])
        
        return True
    
    def get_last_signal(self, symbol: str, direction: str) -> Optional[Dict]:
        """Получить последний сигнал"""
        key = f"{symbol}:{direction}"
        return self.signals.get(key)
    
    def get_active_signals(self) -> Dict[str, Dict]:
        """Получить все активные сигналы"""
        # Очищаем старые сигналы
        self._cleanup()
        return self.signals
    
    def _cleanup(self):
        """Очистить старые сигналы"""
        now = datetime.now()
        expired = []
        
        for key, signal in self.signals.items():
            if (now - signal['timestamp']).total_seconds() > self.cooldown * 6:  # 1 час
                expired.append(key)
        
        for key in expired:
            del self.signals[key]
            logger.debug(f"Removed expired signal: {key}")