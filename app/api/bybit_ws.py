"""
Bybit V5 публичный WebSocket (linear).
Правильные топики:
  orderbook.50.SYMBOL
  publicTrade.SYMBOL
Одно соединение держит несколько подписок (до 20 символов).
Обработка snapshot/delta стакана — в app/datasets/orderbook.py.
"""
import asyncio
import json
from typing import Dict, List, Callable, Any, Optional
from datetime import datetime

import websockets

from app.config import config
from app.utils.logger import logger


class BybitWebSocket:
    # Bybit рекомендует ≤ 10 топиков на соединение для надёжности
    SYMBOLS_PER_CONNECTION = 10

    def __init__(self):
        self.ws_url = config.BYBIT_WS_URL
        self.connections: Dict[int, websockets.WebSocketClientProtocol] = {}
        self.symbol_to_conn: Dict[str, int] = {}
        self.handlers: Dict[str, List[Callable]] = {
            "orderbook": [],
            "trade": [],
        }
        self.running = False
        self._conn_tasks: List[asyncio.Task] = []
        self._recv_tasks: List[asyncio.Task] = []

    def add_handler(self, event: str, handler: Callable):
        if event not in self.handlers:
            self.handlers[event] = []
        self.handlers[event].append(handler)

    async def start(self):
        self.running = True
        logger.info("WebSocket manager started")

    async def stop(self):
        self.running = False
        for task in self._recv_tasks + self._conn_tasks:
            task.cancel()
        for ws in list(self.connections.values()):
            try:
                await ws.close()
            except Exception:
                pass
        self.connections.clear()
        self.symbol_to_conn.clear()
        logger.info("WebSocket manager stopped")

    async def subscribe(self, symbols: List[str]):
        """
        Разбиваем symbols на группы и открываем на каждую группу соединение.
        """
        if not symbols:
            return

        # Исключаем уже подписанные
        new_symbols = [s for s in symbols if s not in self.symbol_to_conn]
        if not new_symbols:
            return

        chunks = [
            new_symbols[i:i + self.SYMBOLS_PER_CONNECTION]
            for i in range(0, len(new_symbols), self.SYMBOLS_PER_CONNECTION)
        ]

        for idx, chunk in enumerate(chunks):
            conn_id = len(self.connections) + idx
            for s in chunk:
                self.symbol_to_conn[s] = conn_id
            task = asyncio.create_task(self._run_connection(conn_id, chunk))
            self._conn_tasks.append(task)

        logger.info(f"Открываем {len(chunks)} WS-соединений на {len(new_symbols)} символов")

    # ========== Соединение ==========

    async def _run_connection(self, conn_id: int, symbols: List[str]):
        backoff = 1
        while self.running:
            try:
                async with websockets.connect(
                    self.ws_url,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=10,
                    max_size=2**23,      # 8 МБ на пакет
                ) as ws:
                    self.connections[conn_id] = ws

                    args = []
                    for s in symbols:
                        args.append(f"orderbook.{config.ORDERBOOK_DEPTH}.{s}")
                        args.append(f"publicTrade.{s}")

                    await ws.send(json.dumps({"op": "subscribe", "args": args}))
                    logger.info(
                        f"WS[{conn_id}] подписка на {len(symbols)} символов "
                        f"({len(args)} топиков)"
                    )

                    backoff = 1

                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                        except Exception:
                            continue
                        await self._dispatch(msg)

            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning(f"WS[{conn_id}] ошибка: {e} (переподключение через {backoff}с)")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    # ========== Диспетчер ==========

    async def _dispatch(self, msg: Dict):
        topic = msg.get("topic", "")
        if not topic:
            return

        if topic.startswith("orderbook."):
            # topic = orderbook.50.BTCUSDT
            parts = topic.split(".")
            if len(parts) < 3:
                return
            symbol = parts[2]
            for h in self.handlers["orderbook"]:
                try:
                    await h(symbol, msg)
                except Exception as e:
                    logger.error(f"orderbook handler error {symbol}: {e}")

        elif topic.startswith("publicTrade."):
            symbol = topic.split(".", 1)[1]
            for h in self.handlers["trade"]:
                try:
                    await h(symbol, msg)
                except Exception as e:
                    logger.error(f"trade handler error {symbol}: {e}")