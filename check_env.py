import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Что видит dotenv до загрузки
print("cwd:", os.getcwd())
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
print("Ожидаемый путь .env:", env_path)
print("Существует?", os.path.exists(env_path))

# Загружаем
from dotenv import load_dotenv
load_dotenv(env_path)

print("\nПеременные:")
for k in ["BOT_TOKEN", "ADMIN_IDS", "DATABASE_URL", "REDIS_URL", "REDIS_HOST", "REDIS_PORT"]:
    v = os.getenv(k)
    if v and len(v) > 20:
        print(f"  {k} = {v[:20]}...")
    else:
        print(f"  {k} = {v}")

# Пробуем прочитать через config
print("\nЧерез config:")
from app.config import config
print("  BOT_TOKEN:", bool(config.BOT_TOKEN))
print("  ADMIN_IDS:", config.ADMIN_IDS)
print("  DATABASE_URL:", bool(config.DATABASE_URL))