import os
import sys
from loguru import logger as _logger
from app.config import config


def setup_logger():
    _logger.remove()

    # Консоль
    _logger.add(
        sys.stdout,
        level=config.LOG_LEVEL,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
    )

    # Файл — в корень проекта
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    log_dir = os.path.join(base_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)

    _logger.add(
        os.path.join(log_dir, "bot_{time:YYYY-MM-DD}.log"),
        level="DEBUG",
        rotation="1 day",
        retention="14 days",
        encoding="utf-8",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    )

    return _logger


logger = setup_logger()