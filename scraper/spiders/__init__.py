"""
PricePoa Scraper Spiders Package.
"""
from .carrefour_spider import CarrefourSpider
from .chandarana_spider import ChandaranaSpider
from .naivas_spider import NaivasSpider
from .quickmart_spider import QuickmartSpider
from .thebar_spider import TheBarSpider

__all__ = [
    'CarrefourSpider',
    'ChandaranaSpider',
    'NaivasSpider',
    'QuickmartSpider',
    'TheBarSpider'
]