import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.api.bybit_rest import BybitRestAPI
from app.api.bybit_ws import BybitWebSocket
from app.storage.store import Store


async def main():
    rest = BybitRestAPI()
    store = Store()

    print("=== REST: Top-10 символов по turnover24h ===")
    symbols = await rest.get_top_symbols(10)
    print(symbols)

    print("\n=== REST: OI для BTCUSDT ===")
    oi = await rest.get_oi("BTCUSDT")
    print(oi)

    print("\n=== REST: Funding для BTCUSDT ===")
    f = await rest.get_funding("BTCUSDT")
    print(f)

    print("\n=== REST: свечи 15м BTCUSDT (3 шт) ===")
    k = await rest.get_klines("BTCUSDT", "15", limit=3)
    print(k)

    print("\n=== WS: 3 секунды приёма по BTCUSDT/ETHUSDT ===")
    ws = BybitWebSocket()
    got = {"orderbook": 0, "trade": 0}

    async def on_ob(symbol, msg):
        got["orderbook"] += 1

    async def on_tr(symbol, msg):
        got["trade"] += len(msg.get("data", []))

    ws.add_handler("orderbook", on_ob)
    ws.add_handler("trade", on_tr)
    await ws.start()
    await ws.subscribe(["BTCUSDT", "ETHUSDT"])
    await asyncio.sleep(3)
    await ws.stop()
    print("orderbook пакетов:", got["orderbook"], "сделок:", got["trade"])

    await rest.stop()


asyncio.run(main())