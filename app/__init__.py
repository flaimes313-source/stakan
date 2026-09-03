# app/__init__.py
"""
Market Analysis Bot Package
"""
from .config import config
from .utils.logger import logger

__version__ = "1.0.0"
__all__ = [
    'config',
    'logger'
]