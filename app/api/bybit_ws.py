import websockets
import json
import asyncio
from typing import Dict, List, Callable, Any
from datetime import datetime
from app.config import config
from app.utils.logger import logger

class BybitWebSocket:
    def __init__(self):
        self.ws_url = config.BYBIT_WS_URL  # Публичный WebSocket
        self.connections: Dict[str, websockets.WebSocketClientProtocol] = {}
        self.handlers: Dict[str, List[Callable]] = {}
        self.subscriptions: Dict[str, set] = {}
        self.running = False
        
    def add_handler(self, event_type: str, handler: Callable):
        """Add event handler"""
        if event_type not in self.handlers:
            self.handlers[event_type] = []
        self.handlers[event_type].append(handler)
    
    async def _handle_message(self, message: Dict, symbol: str):
        """Process incoming WebSocket message"""
        try:
            topic = message.get('topic', '')
            
            # Orderbook update
            if 'orderbook' in topic:
                if 'orderbook' in self.handlers:
                    for handler in self.handlers['orderbook']:
                        await handler(symbol, message)
            
            # Trade updates
            elif 'publicTrade' in topic:
                if 'trade' in self.handlers:
                    for handler in self.handlers['trade']:
                        await handler(symbol, message)
            
        except Exception as e:
            logger.error(f"Error handling message for {symbol}: {e}")
    
    async def _subscribe(self, symbol: str, topics: List[str]):
        """Subscribe to topics for a symbol"""
        if symbol not in self.subscriptions:
            self.subscriptions[symbol] = set()
        
        for topic in topics:
            self.subscriptions[symbol].add(topic)
        
        if symbol in self.connections:
            ws = self.connections[symbol]
            for topic in topics:
                subscription = {
                    "op": "subscribe",
                    "args": [f"{topic}.{symbol}"]
                }
                await ws.send(json.dumps(subscription))
                logger.info(f"Subscribed to {topic} for {symbol}")
    
    async def connect(self, symbol: str, topics: List[str]):
        """Connect and subscribe to symbol topics"""
        try:
            ws = await websockets.connect(self.ws_url)
            self.connections[symbol] = ws
            self.subscriptions[symbol] = set(topics)
            
            # Subscribe to topics
            for topic in topics:
                subscription = {
                    "op": "subscribe",
                    "args": [f"{topic}.{symbol}"]
                }
                await ws.send(json.dumps(subscription))
            
            logger.info(f"Connected to {symbol}")
            
            # Start message handler
            asyncio.create_task(self._listen(symbol, ws))
            
        except Exception as e:
            logger.error(f"Connection error for {symbol}: {e}")
            asyncio.create_task(self._reconnect(symbol, topics))
    
    async def _listen(self, symbol: str, ws: websockets.WebSocketClientProtocol):
        """Listen for messages from WebSocket"""
        while self.running:
            try:
                message = await ws.recv()
                data = json.loads(message)
                
                if 'topic' in data:
                    await self._handle_message(data, symbol)
                elif 'op' in data and data['op'] == 'subscribe':
                    if data.get('success', False):
                        logger.info(f"Subscription successful for {symbol}")
                
            except websockets.ConnectionClosed:
                logger.warning(f"Connection closed for {symbol}")
                asyncio.create_task(self._reconnect(symbol, list(self.subscriptions.get(symbol, []))))
                break
            except Exception as e:
                logger.error(f"Listen error for {symbol}: {e}")
                await asyncio.sleep(1)
    
    async def _reconnect(self, symbol: str, topics: List[str]):
        """Reconnect after connection loss"""
        await asyncio.sleep(5)
        if symbol in self.connections:
            try:
                await self.connections[symbol].close()
            except:
                pass
            del self.connections[symbol]
        
        await self.connect(symbol, topics)
    
    async def start(self):
        """Start WebSocket manager"""
        self.running = True
        logger.info("WebSocket manager started")
    
    async def stop(self):
        """Stop WebSocket manager"""
        self.running = False
        for symbol, ws in self.connections.items():
            try:
                await ws.close()
            except:
                pass
        logger.info("WebSocket manager stopped")