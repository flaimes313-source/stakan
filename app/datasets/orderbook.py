import asyncio
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from collections import deque

from app.models import OrderBook, OrderBookEntry
from app.api.bybit_ws import BybitWebSocket
from app.storage.store import Store
from app.config import config
from app.utils.logger import logger


class OrderBookManager:
    def __init__(self, ws: BybitWebSocket, store: Store):
        self.ws = ws
        self.store = store
        self.postgres = None

        # symbol -> {"bids": {price: size}, "asks": {price: size}, "u": int, "seq": int, "ts": datetime}
        self._books: Dict[str, Dict] = {}

        self.running = False
        self._lock = asyncio.Lock()

        self.ws.add_handler("orderbook", self._on_orderbook)
        self.ws.add_handler("trade", self._on_trade)

        self._order_sizes: Dict[str, deque] = {}
        self._order_sizes_max = 500

        self.tracking: Dict[str, Dict] = {}

    def set_postgres(self, postgres):
        self.postgres = postgres

    async def start(self):
        self.running = True
        asyncio.create_task(self._median_updater())
        asyncio.create_task(self._cleanup_task())
        logger.info("OrderBook manager started")

    async def stop(self):
        self.running = False
        logger.info("OrderBook manager stopped")

    # ========== ORDERBOOK ==========

    async def _on_orderbook(self, symbol: str, msg: Dict):
        try:
            data = msg.get("data")
            if not data:
                return

            msg_type = msg.get("type")
            update_id = int(data.get("u", 0) or 0)
            seq = int(data.get("seq", 0) or 0)

            b_raw = data.get("b") or []
            a_raw = data.get("a") or []

            # Пустой пакет без изменений — не трогаем книгу
            if not b_raw and not a_raw and msg_type != "snapshot":
                return

            async with self._lock:
                book = self._books.get(symbol)

                if msg_type == "snapshot" or book is None:
                    bids = {}
                    asks = {}
                    for p, s in b_raw:
                        try:
                            size = float(s)
                            if size > 0:
                                bids[float(p)] = size
                        except (TypeError, ValueError):
                            continue
                    for p, s in a_raw:
                        try:
                            size = float(s)
                            if size > 0:
                                asks[float(p)] = size
                        except (TypeError, ValueError):
                            continue
                    self._books[symbol] = {
                        "bids": bids,
                        "asks": asks,
                        "u": update_id,
                        "seq": seq,
                        "ts": datetime.now(),
                    }
                else:
                    if update_id and update_id <= book["u"]:
                        return
                    self._apply_side(book["bids"], b_raw)
                    self._apply_side(book["asks"], a_raw)
                    book["u"] = update_id
                    book["seq"] = seq
                    book["ts"] = datetime.now()

                top_bids = sorted(book["bids"].items(), key=lambda x: -x[0])[: config.ORDERBOOK_DEPTH]
                top_asks = sorted(book["asks"].items(), key=lambda x: x[0])[: config.ORDERBOOK_DEPTH]

            if not top_bids or not top_asks:
                return

            orderbook = OrderBook(
                symbol=symbol,
                bids=[OrderBookEntry(price=p, size=s) for p, s in top_bids],
                asks=[OrderBookEntry(price=p, size=s) for p, s in top_asks],
                timestamp=self._books[symbol]["ts"],
                update_id=self._books[symbol]["u"],
                is_snapshot=(msg_type == "snapshot"),
            )

            await self.store.set_orderbook(symbol, orderbook)
            await self._track_large_orders(symbol, orderbook)
            await self._analyze(symbol, orderbook)

            for _, size in top_bids[:20]:
                self._order_sizes.setdefault(symbol, deque(maxlen=self._order_sizes_max)).append(size)
            for _, size in top_asks[:20]:
                self._order_sizes.setdefault(symbol, deque(maxlen=self._order_sizes_max)).append(size)

        except Exception as e:
            logger.debug(f"orderbook skip {symbol}: {e}")

    def _apply_side(self, side: Dict[float, float], updates):
        if not updates:
            return
        for row in updates:
            try:
                price = float(row[0])
                size = float(row[1])
            except (TypeError, ValueError, IndexError):
                continue
            if size == 0:
                side.pop(price, None)
            else:
                side[price] = size

    # ========== TRADES ==========

    async def _on_trade(self, symbol: str, msg: Dict):
        try:
            trades = msg.get("data") or []
            for t in trades:
                try:
                    price = float(t["p"])
                    size = float(t["v"])
                except (KeyError, TypeError, ValueError):
                    continue
                trade = {
                    "symbol": symbol,
                    "price": price,
                    "size": size,
                    "side": t.get("S", "Buy"),
                    "timestamp": datetime.fromtimestamp(int(t["T"]) / 1000),
                    "notional": price * size,
                }
                await self.store.add_trade(symbol, trade)
                if self.postgres and trade["notional"] >= 5_000:
                    try:
                        await self.postgres.save_trade(symbol, trade)
                    except Exception as e:
                        logger.debug(f"save_trade {symbol}: {e}")
        except Exception as e:
            logger.debug(f"trade skip {symbol}: {e}")

    # ========== MEDIAN ==========

    async def _median_updater(self):
        while self.running:
            try:
                await asyncio.sleep(60)
                for symbol, dq in list(self._order_sizes.items()):
                    if not dq:
                        continue
                    sizes = sorted(dq)
                    median = sizes[len(sizes) // 2]
                    await self.store.set_median_order_size(symbol, median)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"median updater: {e}")

    # ========== LARGE ORDERS ==========

    async def _track_large_orders(self, symbol: str, ob: OrderBook):
        try:
            median = await self.store.get_median_order_size(symbol)
            if median <= 0:
                return

            now = datetime.now()
            session_id = int(now.timestamp() // 3600)

            for side, entries in (("bid", ob.bids), ("ask", ob.asks)):
                for e in entries[:10]:
                    ratio = e.size / median
                    if ratio < config.ORDER_SIZE_THRESHOLDS["large"]:
                        continue

                    key = f"{symbol}:{side}:{e.price}"
                    if key not in self.tracking:
                        rec = {
                            "symbol": symbol,
                            "side": side,
                            "price": e.price,
                            "initial_size": e.size,
                            "max_size": e.size,
                            "current_size": e.size,
                            "executed_estimate": 0.0,
                            "cancelled_estimate": 0.0,
                            "first_seen": now,
                            "last_seen": now,
                            "status": "active",
                            "session_id": session_id,
                        }
                        self.tracking[key] = rec
                    else:
                        rec = self.tracking[key]
                        rec["last_seen"] = now
                        rec["current_size"] = e.size
                        rec["max_size"] = max(rec["max_size"], e.size)

                    if self.postgres:
                        try:
                            await self.postgres.save_large_order(rec)
                        except Exception as e:
                            logger.debug(f"save_large_order {symbol}: {e}")
                    await self.store.save_large_order(key, rec)

        except Exception as e:
            logger.debug(f"track_large_orders {symbol}: {e}")

    # ========== ANALYZE ==========

    async def _analyze(self, symbol: str, ob: OrderBook):
        if not ob.bids or not ob.asks:
            return
        bid_vol = sum(b.size for b in ob.bids[:20])
        ask_vol = sum(a.size for a in ob.asks[:20])
        total = bid_vol + ask_vol
        if total <= 0:
            return
        imbalance = (bid_vol - ask_vol) / total
        await self.store.set_imbalance(symbol, imbalance)

    # ========== CLEANUP ==========

    async def _cleanup_task(self):
        while self.running:
            try:
                await asyncio.sleep(120)
                now = datetime.now()
                old = [k for k, r in self.tracking.items()
                       if (now - r["last_seen"]).total_seconds() > 3600]
                for k in old:
                    del self.tracking[k]
                    await self.store.delete_key(f"order_track:{k}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"cleanup: {e}")

    def get_local_book(self, symbol: str) -> Optional[Dict]:
        return self._books.get(symbol)