from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Dict, Any, Optional


class SignalState(str, Enum):
    NEW = "NEW"
    WATCH = "WATCH"
    ABSORPTION = "ABSORPTION"
    CONFIRMATION = "CONFIRMATION"
    TRIGGERED = "TRIGGERED"
    EXPIRED = "EXPIRED"


class SignalType(str, Enum):
    SETUP = "SETUP"
    CONFIRMATION = "CONFIRMATION"


class SignalLevel(str, Enum):
    EXTREME = "EXTREME"
    STRONG = "STRONG"
    WATCH = "WATCH"
    INTERESTING = "INTERESTING"
    NONE = "NONE"


@dataclass
class OrderBookEntry:
    price: float
    size: float


@dataclass
class OrderBook:
    symbol: str
    bids: List[OrderBookEntry]
    asks: List[OrderBookEntry]
    timestamp: datetime
    update_id: int = 0
    is_snapshot: bool = False

    @property
    def best_bid(self) -> float:
        return self.bids[0].price if self.bids else 0.0

    @property
    def best_ask(self) -> float:
        return self.asks[0].price if self.asks else 0.0

    @property
    def mid_price(self) -> float:
        bb, ba = self.best_bid, self.best_ask
        return (bb + ba) / 2 if bb and ba else 0.0

    @property
    def spread(self) -> float:
        return self.best_ask - self.best_bid if self.best_bid and self.best_ask else 0.0


@dataclass
class Trade:
    symbol: str
    price: float
    size: float
    side: str                # "Buy" / "Sell"
    timestamp: datetime
    notional: float


@dataclass
class Ticker:
    symbol: str
    last_price: float
    turnover_24h: float
    volume_24h: float
    timestamp: datetime


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
    direction: str                       # "LONG" / "SHORT"
    level: float
    score: int
    state: SignalState
    signal_type: SignalType = SignalType.SETUP
    timestamp: Optional[datetime] = None
    factors: Dict[str, Any] = field(default_factory=dict)
    message: str = ""

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()