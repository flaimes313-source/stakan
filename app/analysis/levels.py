import asyncio
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import numpy as np
from app.api.bybit_rest import BybitRestAPI
from app.storage.redis import RedisStorage
from app.config import config
from app.utils.logger import logger

class LevelAnalyzer:
    def __init__(self, rest_api: BybitRestAPI, redis: RedisStorage):
        self.rest = rest_api
        self.redis = redis
        self.postgres = None  # Будет установлен извне
        self.levels_cache: Dict[str, List[Dict]] = {}
    
    def set_postgres(self, postgres):
        """Установить ссылку на PostgreSQL"""
        self.postgres = postgres
        
    async def calculate_levels(self, symbol: str) -> List[Dict]:
        """Calculate technical levels for a symbol"""
        levels = []
        
        try:
            for timeframe, tf_config in config.TIMEFRAMES.items():
                klines = await self.rest.get_klines(symbol, timeframe, tf_config['limit'])
                if klines:
                    timeframe_levels = await self._find_levels(klines, timeframe, tf_config['weight'])
                    levels.extend(timeframe_levels)
            
            levels = await self._merge_levels(levels)
            levels = await self._calculate_strength(levels)
            levels.sort(key=lambda x: x['strength'], reverse=True)
            
            # Сохраняем в Redis
            await self.redis.set_levels(symbol, levels)
            
            # Сохраняем в PostgreSQL (только сильные уровни > 50)
            if self.postgres:
                for level in levels[:10]:  # Топ 10 уровней
                    if level.get('strength', 0) > 50:
                        try:
                            await self.postgres.save_level(symbol, level)
                        except Exception as e:
                            logger.debug(f"Error saving level: {e}")
            
            return levels
            
        except Exception as e:
            logger.error(f"Error calculating levels for {symbol}: {e}")
            return []
    
    async def _find_levels(self, klines: List[Dict], timeframe: str, weight: int) -> List[Dict]:
        """Find swing highs and lows in kline data"""
        levels = []
        
        if len(klines) < 3:
            return levels
        
        for i in range(1, len(klines) - 1):
            if (klines[i]['high'] > klines[i-1]['high'] and 
                klines[i]['high'] > klines[i+1]['high']):
                levels.append({
                    'price': klines[i]['high'],
                    'type': 'resistance',
                    'timeframe': timeframe,
                    'weight': weight,
                    'timestamp': klines[i]['timestamp'],
                    'touches': 1,
                    'volume': klines[i]['volume']
                })
            
            if (klines[i]['low'] < klines[i-1]['low'] and 
                klines[i]['low'] < klines[i+1]['low']):
                levels.append({
                    'price': klines[i]['low'],
                    'type': 'support',
                    'timeframe': timeframe,
                    'weight': weight,
                    'timestamp': klines[i]['timestamp'],
                    'touches': 1,
                    'volume': klines[i]['volume']
                })
        
        return levels
    
    async def _merge_levels(self, levels: List[Dict]) -> List[Dict]:
        """Merge nearby levels"""
        if not levels:
            return []
        
        merged = []
        sorted_levels = sorted(levels, key=lambda x: x['price'])
        
        current = sorted_levels[0]
        for level in sorted_levels[1:]:
            if abs(level['price'] - current['price']) / current['price'] < 0.002:
                current['touches'] += 1
                current['weight'] += level['weight']
                current['volume'] += level['volume']
                if level['timestamp'] > current['timestamp']:
                    current['timestamp'] = level['timestamp']
            else:
                merged.append(current)
                current = level
        
        merged.append(current)
        return merged
    
    async def _calculate_strength(self, levels: List[Dict]) -> List[Dict]:
        """Calculate strength score for each level"""
        for level in levels:
            strength = 0
            
            touches_score = min(level['touches'] * 4, 20)
            strength += touches_score
            
            reaction_score = min(level['volume'] / 1000000 * 10, 20)
            strength += reaction_score
            
            timeframe_score = level['weight'] * 4
            strength += min(timeframe_score, 20)
            
            days_old = (datetime.now() - level['timestamp']).days
            recency_score = max(0, 10 - days_old)
            strength += recency_score
            
            level['strength'] = min(strength, 100)
        
        return levels
    
    async def update_levels_for_symbol(self, symbol: str):
        """Update levels for a single symbol"""
        try:
            levels = await self.calculate_levels(symbol)
            self.levels_cache[symbol] = levels
            logger.info(f"Updated levels for {symbol}: {len(levels)} levels found")
        except Exception as e:
            logger.error(f"Error updating levels for {symbol}: {e}")