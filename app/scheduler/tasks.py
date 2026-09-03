import asyncio
from typing import Dict, List
from datetime import datetime, timedelta
from app.config import config
from app.utils.logger import logger

class Scheduler:
    def __init__(self, bot):
        self.bot = bot
        self.running = False
        self.tasks = []
    
    async def start(self):
        """Start scheduler"""
        self.running = True
        logger.info("Scheduler started")
        
        # Schedule tasks
        self.tasks = [
            asyncio.create_task(self._update_symbols_task()),
            asyncio.create_task(self._update_oi_task()),
            asyncio.create_task(self._update_funding_task()),
            asyncio.create_task(self._cleanup_task())
        ]
    
    async def stop(self):
        """Stop scheduler"""
        self.running = False
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        logger.info("Scheduler stopped")
    
    async def _update_symbols_task(self):
        """Update symbols periodically"""
        while self.running:
            try:
                await asyncio.sleep(config.SYMBOLS_UPDATE_INTERVAL)
                await self.bot.update_symbols()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in update symbols task: {e}")
    
    async def _update_oi_task(self):
        """Update OI periodically"""
        while self.running:
            try:
                await asyncio.sleep(60)  # Every minute
                
                for symbol in self.bot.active_symbols:
                    if not self.running:
                        break
                    
                    oi_data = await self.bot.rest_api.get_oi(symbol)
                    if oi_data:
                        await self.bot.redis.set_oi_data(symbol, oi_data)
                        await self.bot.postgres.save_oi(symbol, oi_data['oi'])
                    
                    await asyncio.sleep(0.1)  # Rate limiting
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in OI update task: {e}")
    
    async def _update_funding_task(self):
        """Update funding rates periodically"""
        while self.running:
            try:
                await asyncio.sleep(300)  # Every 5 minutes
                
                for symbol in self.bot.active_symbols:
                    if not self.running:
                        break
                    
                    funding_data = await self.bot.rest_api.get_funding_rate(symbol)
                    if funding_data:
                        await self.bot.redis.set_funding_data(symbol, funding_data)
                        await self.bot.postgres.save_funding(symbol, funding_data['funding_rate'])
                    
                    await asyncio.sleep(0.1)  # Rate limiting
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in funding update task: {e}")
    
    async def _cleanup_task(self):
        """Cleanup old data periodically"""
        while self.running:
            try:
                await asyncio.sleep(3600)  # Every hour
                
                # Clean old signals
                # Clean old trades
                # Clean old OI data
                logger.info("Cleanup task executed")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup task: {e}")