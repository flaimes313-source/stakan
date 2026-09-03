import aiohttp
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from app.config import config
from app.utils.logger import logger

class BybitRestAPI:
    def __init__(self):
        self.base_url = config.BYBIT_REST_URL
        # API ключи НЕ используются для публичных данных
        
    async def _request(self, endpoint: str, params: Dict = None) -> Dict:
        """Make public API request (no auth needed)"""
        url = f"{self.base_url}{endpoint}"
        headers = {'Content-Type': 'application/json'}
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, params=params, headers=headers, timeout=30) as response:
                    data = await response.json()
                    if data.get('retCode') != 0:
                        logger.error(f"API Error: {data.get('retMsg')}")
                        return {}
                    return data.get('result', {})
            except asyncio.TimeoutError:
                logger.error(f"Request timeout: {endpoint}")
                return {}
            except Exception as e:
                logger.error(f"Request error: {e}")
                return {}
    
    async def get_instruments(self, category: str = 'linear') -> List[Dict]:
        """Get all instruments for a category (PUBLIC)"""
        try:
            result = await self._request('/v5/market/instruments-info', params={'category': category})
            return result.get('list', []) if result else []
        except Exception as e:
            logger.error(f"Error getting instruments: {e}")
            return []
    
    async def get_top_symbols(self, limit: int = 50) -> List[str]:
        """Get top symbols by 24h turnover (PUBLIC)"""
        try:
            instruments = await self.get_instruments('linear')
            
            if not instruments:
                logger.warning("No instruments found, using fallback list")
                return self._get_fallback_symbols(limit)
            
            # Filter USDT perpetual contracts
            usdt_perps = [
                inst for inst in instruments 
                if inst.get('contractType') == 'LinearPerpetual' 
                and inst.get('quoteCoin') == 'USDT'
            ]
            
            if not usdt_perps:
                logger.warning("No USDT perpetual found, using fallback list")
                return self._get_fallback_symbols(limit)
            
            # Sort by turnover (PUBLIC data)
            sorted_instruments = sorted(
                usdt_perps, 
                key=lambda x: float(x.get('turnover24h', 0)), 
                reverse=True
            )
            
            symbols = [inst['symbol'] for inst in sorted_instruments[:limit]]
            logger.info(f"Found {len(symbols)} symbols")
            return symbols
            
        except Exception as e:
            logger.error(f"Error getting top symbols: {e}")
            return self._get_fallback_symbols(limit)
    
    def _get_fallback_symbols(self, limit: int = 50) -> List[str]:
        """Return fallback symbol list if API fails"""
        fallback = [
            'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT',
            'BNBUSDT', 'ADAUSDT', 'LINKUSDT', 'AVAXUSDT', 'SUIUSDT',
            'DOTUSDT', 'MATICUSDT', 'SHIBUSDT', 'LTCUSDT', 'TRXUSDT',
            'ATOMUSDT', 'UNIUSDT', 'ARBUSDT', 'OPUSDT', 'APTUSDT',
            'NEARUSDT', 'FILUSDT', 'ICPUSDT', 'ETCUSDT', 'XLMUSDT',
            'HBARUSDT', 'VETUSDT', 'ALGOUSDT', 'EGLDUSDT', 'RNDRUSDT',
            'STXUSDT', 'INJUSDT', 'MKRUSDT', 'AAVEUSDT', 'CRVUSDT',
            'SNXUSDT', 'COMPUSDT', 'ZECUSDT', 'XMRUSDT', 'DASHUSDT',
            'EOSUSDT', 'NEOUSDT', 'WAVESUSDT', 'XEMUSDT', 'LSKUSDT',
            'ZILUSDT', 'ONTUSDT', 'QTUMUSDT', 'VTHOUSDT', 'CHZUSDT'
        ]
        logger.info(f"Using fallback symbols: {len(fallback[:limit])}")
        return fallback[:limit]
    
    async def get_oi(self, symbol: str) -> Dict:
        """Get Open Interest for a symbol (PUBLIC)"""
        try:
            result = await self._request('/v5/market/open-interest', params={
                'category': 'linear',
                'symbol': symbol
            })
            if result and 'list' in result and result['list']:
                return {
                    'oi': float(result['list'][0].get('openInterest', 0)),
                    'timestamp': datetime.now()
                }
            return {'oi': 0, 'timestamp': datetime.now()}
        except Exception as e:
            logger.error(f"Error getting OI for {symbol}: {e}")
            return {'oi': 0, 'timestamp': datetime.now()}
    
    async def get_funding_rate(self, symbol: str) -> Dict:
        """Get funding rate for a symbol (PUBLIC)"""
        try:
            result = await self._request('/v5/market/tickers', params={
                'category': 'linear',
                'symbol': symbol
            })
            if result and 'list' in result and result['list']:
                ticker = result['list'][0]
                return {
                    'funding_rate': float(ticker.get('fundingRate', 0)),
                    'next_funding_time': datetime.fromtimestamp(
                        int(ticker.get('nextFundingTime', 0)) / 1000
                    ) if ticker.get('nextFundingTime') else datetime.now(),
                    'timestamp': datetime.now()
                }
            return {'funding_rate': 0, 'next_funding_time': datetime.now(), 'timestamp': datetime.now()}
        except Exception as e:
            logger.error(f"Error getting funding for {symbol}: {e}")
            return {'funding_rate': 0, 'next_funding_time': datetime.now(), 'timestamp': datetime.now()}
    
    async def get_klines(self, symbol: str, interval: str, limit: int = 200) -> List[Dict]:
        """Get kline/candlestick data (PUBLIC)"""
        try:
            result = await self._request('/v5/market/kline', params={
                'category': 'linear',
                'symbol': symbol,
                'interval': interval,
                'limit': limit
            })
            if result and 'list' in result:
                klines = []
                for item in result['list']:
                    klines.append({
                        'timestamp': datetime.fromtimestamp(int(item[0]) / 1000),
                        'open': float(item[1]),
                        'high': float(item[2]),
                        'low': float(item[3]),
                        'close': float(item[4]),
                        'volume': float(item[5]),
                        'turnover': float(item[6])
                    })
                return klines
            return []
        except Exception as e:
            logger.error(f"Error getting klines for {symbol}: {e}")
            return []