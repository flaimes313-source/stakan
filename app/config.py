import os
from typing import List
from dotenv import load_dotenv, find_dotenv

# Ищем .env вверх по дереву от текущего файла
_env_file = find_dotenv(usecwd=False)
if _env_file:
    load_dotenv(_env_file, override=False)
else:
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    load_dotenv(os.path.join(_root, ".env"), override=False)


def _int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


class Config:
    # ===== Telegram =====
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

    # ADMIN_IDS — необязателен.
    # Если пусто — подписчики собираются автоматически через /start.
    _admin_raw: str = os.getenv("ADMIN_IDS", "").strip()
    ADMIN_IDS: List[int] = [
        int(x) for x in _admin_raw.split(",") if x.strip().isdigit()
    ]

    # ===== PostgreSQL =====
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")

    # ===== Redis (опционально — есть fallback на FileStore) =====
    REDIS_URL: str = os.getenv("REDIS_URL", "")
    REDIS_HOST: str = os.getenv("REDIS_HOST", "")
    REDIS_PORT: int = _int(os.getenv("REDIS_PORT", "0"))
    REDIS_PASSWORD: str = os.getenv("REDIS_PASSWORD", "")

    # ===== Bybit =====
    BYBIT_REST_URL: str = os.getenv("BYBIT_REST_URL", "https://api.bybit.com")
    BYBIT_WS_URL: str = os.getenv("BYBIT_WS_URL", "wss://stream.bybit.com/v5/public/linear")

    # ===== Логи =====
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # ===== Торговые настройки =====
    TOP_SYMBOLS_COUNT: int = 30
    SYMBOLS_UPDATE_INTERVAL: int = 3600
    ORDERBOOK_DEPTH: int = 50
    TRADES_HISTORY_SECONDS: int = 1800

    ABSORPTION_WINDOW_SEC: int = 15
    SIGNAL_COOLDOWN_SEC: int = 600
    SIGNAL_THRESHOLD: int = 70

    WEIGHTS = {
        "level": 20,
        "orderbook": 20,
        "trades": 15,
        "absorption": 20,
        "oi": 10,
        "funding": 5,
        "volume": 10,
    }

    TIMEFRAMES = {
        "D":   {"weight": 5, "limit": 200},
        "240": {"weight": 4, "limit": 200},
        "60":  {"weight": 3, "limit": 200},
        "15":  {"weight": 1, "limit": 200},
    }

    ORDER_SIZE_THRESHOLDS = {
        "large": 3.0,
        "very_large": 5.0,
        "extreme": 10.0,
    }

    @property
    def use_redis(self) -> bool:
        return bool(self.REDIS_URL or (self.REDIS_HOST and self.REDIS_PORT))

    def validate(self) -> None:
        errors = []
        if not self.BOT_TOKEN:
            errors.append("BOT_TOKEN не задан")
        if not self.DATABASE_URL:
            errors.append("DATABASE_URL не задан (PostgreSQL обязателен)")
        # ADMIN_IDS не проверяем — он необязателен
        if errors:
            raise RuntimeError("Ошибки конфигурации:\n  - " + "\n  - ".join(errors))


config = Config()