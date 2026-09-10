"""
Redis storage - заменён на MemoryStorage для работы без Redis на хостинге
"""
from app.storage.memory_storage import MemoryStorage
from app.utils.logger import logger

class RedisStorage(MemoryStorage):
    """Алиас для MemoryStorage (для совместимости с существующим кодом)"""
    
    def __init__(self):
        super().__init__()
        logger.info("✅ RedisStorage работает в режиме MemoryStorage (без Redis)")