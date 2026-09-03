import os
from dotenv import load_dotenv
from typing import List, Dict, Any

load_dotenv()

class Config:
    # Bot
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    ADMIN_IDS = [int(x) for x in os.getenv('ADMIN_IDS', '').split(',') if x]
    
    # Database
    POSTGRES_HOST = os.getenv('POSTGRES_HOST', 'localhost')
    POSTGRES_PORT = int(os.getenv('POSTGRES_PORT', 5432))
    POSTGRES_DB = os.getenv('POSTGRES_DB', 'market_bot')
    POSTGRES_USER = os.getenv('POSTGRES_USER', 'market_bot')
    POSTGRES_PASSWORD = os.getenv('POSTGRES_PASSWORD', '')
    
    DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
    
    # Redis
    REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
    REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
    REDIS_DB = int(os.getenv('REDIS_DB', 0))
    REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', '')
    
    # Bybit
    BYBIT_API_KEY = os.getenv('BYBIT_API_KEY', '')
    BYBIT_API_SECRET = os.getenv('BYBIT_API_SECRET', '')
    BYBIT_WS_URL = "wss://stream.bybit.com/v5/public/linear"
    BYBIT_REST_URL = "https://api.bybit.com"
    
    # Trading settings
    TOP_SYMBOLS_COUNT = 50
    SYMBOLS_UPDATE_INTERVAL = 3600  # 1 hour
    ORDERBOOK_DEPTH = 50
    TRADES_HISTORY_MINUTES = 30
    ABSORPTION_WINDOW = 10  # seconds
    SIGNAL_COOLDOWN = 600  # 10 minutes
    SIGNAL_THRESHOLD = 70
    
    # Rating weights
    WEIGHTS = {
        'level': 20,
        'orderbook': 20,
        'trades': 15,
        'absorption': 20,
        'oi': 10,
        'funding': 5,
        'volume': 10
    }
    
    # Timeframes for levels
    TIMEFRAMES = {
        '1D': {'weight': 5, 'limit': 365},
        '4H': {'weight': 4, 'limit': 90},
        '1H': {'weight': 3, 'limit': 24},
        '15m': {'weight': 1, 'limit': 12}
    }
    
    # Category thresholds for order sizes
    ORDER_SIZE_THRESHOLDS = {
        'large': 3.0,
        'very_large': 5.0,
        'extreme': 10.0
    }

config = Config()