"""bilibili-mall: 一个用于在 b 站市集中搜索折扣商品的系统"""

from .crawler import BMallSpider

# Package metadata
__author__ = "ChijiangZhai"
__email__ = "chijiangzhai@gmail.com"
__description__ = """bilibili-mall: 一个用于在 b 站市集中搜索折扣商品的系统"""
__version__ = "0.1.0"

__all__ = [
    "BMallSpider",
]
