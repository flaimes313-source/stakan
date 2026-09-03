from enum import Enum
from typing import Dict, List, Optional
from datetime import datetime
from app.models import SignalState, Signal
from app.utils.logger import logger

class SignalStateMachine:
    """Машина состояний для сигналов"""
    
    def __init__(self):
        self.states: Dict[str, Dict] = {}
        
    def initialize(self, signal_id: str):
        """Инициализировать состояние"""
        self.states[signal_id] = {
            'state': SignalState.NEW,
            'timestamp': datetime.now(),
            'history': []
        }
    
    def transition(self, signal_id: str, new_state: SignalState) -> bool:
        """Перейти в новое состояние"""
        if signal_id not in self.states:
            return False
        
        current = self.states[signal_id]
        old_state = current['state']
        
        # Проверяем допустимость перехода
        if not self._is_valid_transition(old_state, new_state):
            logger.warning(f"Invalid transition: {old_state} -> {new_state}")
            return False
        
        # Выполняем переход
        current['state'] = new_state
        current['timestamp'] = datetime.now()
        current['history'].append({
            'from': old_state,
            'to': new_state,
            'timestamp': datetime.now()
        })
        
        logger.info(f"Signal {signal_id}: {old_state} -> {new_state}")
        return True
    
    def _is_valid_transition(self, old_state: SignalState, new_state: SignalState) -> bool:
        """Проверить валидность перехода"""
        valid_transitions = {
            SignalState.NEW: [SignalState.WATCH, SignalState.EXPIRED],
            SignalState.WATCH: [SignalState.ABSORPTION, SignalState.EXPIRED],
            SignalState.ABSORPTION: [SignalState.CONFIRMATION, SignalState.EXPIRED],
            SignalState.CONFIRMATION: [SignalState.TRIGGERED, SignalState.EXPIRED],
            SignalState.TRIGGERED: [SignalState.EXPIRED],
            SignalState.EXPIRED: []
        }
        
        return new_state in valid_transitions.get(old_state, [])
    
    def get_state(self, signal_id: str) -> Optional[SignalState]:
        """Получить текущее состояние"""
        if signal_id in self.states:
            return self.states[signal_id]['state']
        return None
    
    def get_history(self, signal_id: str) -> List[Dict]:
        """Получить историю состояний"""
        if signal_id in self.states:
            return self.states[signal_id]['history']
        return []