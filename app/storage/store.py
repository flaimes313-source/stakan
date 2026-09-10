from app.config import config
from app.utils.logger import logger


if config.use_redis:
    from app.storage.redis import RedisStorage as _Store
    logger.info("Store backend: Redis")
else:
    from app.storage.file_store import FileStore as _Store
    logger.info("Store backend: FileStore (SQLite)")


class Store(_Store):
    """Алиас, чтобы код работал одинаково."""
    pass