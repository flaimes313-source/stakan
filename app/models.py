from dataclasses import dataclass
from typing import List, Dict, Optional, Any
from datetime import datetime
from enum import Enum

class SignalState(Enum):
    NEW = "NEW"
    WATCH = "WATCH"
    ABSORPTION = "ABSORPTION"
    CONFIRMATION = "CONFIRMATION"
    TRIGGERED = "TRIGGERED"
    EXPIRED = "EXPIRED"

class SignalLevel(Enum):
    EXTREME = "EXTREME"
    STRONG = "STRONG"
    WATCH = "WATCH"
    INTERESTING = "INTERESTING"
    NONE = "NONE"

class SignalType(Enum):
    SETUP = "SETUP"
    CONFIRMATION = "CONFIRMATION"

@dataclass
class OrderBookEntry:
    price: float
    size: float
    is_bid: bool
    
@dataclass
class OrderBook:
    symbol: str
    bids: List[OrderBookEntry]
    asks: List[OrderBookEntry]
    timestamp: datetime
    
    @property
    def best_bid(self) -> float:
        return self.bids[0].price if self.bids else 0
    
    @property
    def best_ask(self) -> float:
        return self.asks[0].price if self.asks else 0
    
    @property
    def spread(self) -> float:
        return self.best_ask - self.best_bid
    
    @property
    def mid_price(self) -> float:
        return (self.best_bid + self.best_ask) / 2

@dataclass
class Trade:
    symbol: str
    price: float
    size: float
    side: str  # 'Buy' or 'Sell'
    timestamp: datetime
    notional: float
    
@dataclass
class Level:
    price: float
    strength: float
    timeframe: str
    touches: int
    volume: float
    is_support: bool

@dataclass
class Signal:
    symbol: str
    direction: str  # 'LONG' or 'SHORT'
    level: float
    score: int
    state: SignalState
    signal_type: SignalType = SignalType.SETUP
    timestamp: datetime = None
    factors: Dict[str, Any] = None
    message: str = ""
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
        if self.factors is None:
            self.factors = {}