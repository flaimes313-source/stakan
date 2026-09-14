import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config import config
from app.api.bybit_rest import BybitRestAPI


async def main():
    print("=== CONFIG ===")
    print("DATABASE_URL set:", bool(config.DATABASE_URL))

    rest = BybitRestAPI()
    await rest.start()

    print("\n=== get_oi('BTCUSDT') ===")
    data = await rest.get_oi("BTCUSDT")
    print(data)

    print("\n=== get_oi('ETHUSDT') ===")
    data = await rest.get_oi("ETHUSDT")
    print(data)

    print("\n=== get_funding('BTCUSDT') ===")
    data = await rest.get_funding("BTCUSDT")
    print(data)

    await rest.stop()


asyncio.run(main())