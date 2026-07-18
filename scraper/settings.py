"""
Scrapy settings for PricePoa project.
"""
import os

BOT_NAME = 'pricepoa_scraper'

SPIDER_MODULES = ['spiders']
NEWSPIDER_MODULE = 'spiders'

# Obey robots.txt rules
ROBOTSTXT_OBEY = False

# Configure maximum concurrent requests performed by Scrapy (default: 16)
CONCURRENT_REQUESTS = 6

# Configure a delay for requests for the same website (default: 0)
# See https://docs.scrapy.org/en/latest/topics/settings.html#download-delay
# See also autothrottle settings and docs
DOWNLOAD_DELAY = 3.0
RANDOMIZE_DOWNLOAD_DELAY = True

# The download delay setting will honor only one of:
CONCURRENT_REQUESTS_PER_DOMAIN = 2

# Disable cookies (enabled by default)
COOKIES_ENABLED = False

#temporary limit
#CLOSESPIDER_ITEMCOUNT = 50

# Disable Telnet Console (enabled by default)
TELNETCONSOLE_ENABLED = False

# Override the default request headers:
DEFAULT_REQUEST_HEADERS = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en',
    'User-Agent': 'PricePoa Scraper (+https://pricepoa.co.ke)'
}

# Enable or disable spider middlewares
# See https://docs.scrapy.org/en/latest/topics/spider-middleware.html
SPIDER_MIDDLEWARES = {
}

# Enable or disable downloader middlewares
# See https://docs.scrapy.org/en/latest/topics/downloader-middleware.html
DOWNLOADER_MIDDLEWARES = {
    'middleware.invisible_playwright_middleware.InvisiblePlaywrightMiddleware': 543,
}

# Enable or disable extensions
# See https://docs.scrapy.org/en/latest/topics/extensions.html
EXTENSIONS = {
    'scrapy.extensions.telnet.TelnetConsole': None,
}

# Configure item pipelines
# See https://docs.scrapy.org/en/latest/topics/item-pipeline.html
ITEM_PIPELINES = {
    'pipelines.normalization_pipeline.NormalizationPipeline': 300,
    'pipelines.validation_pipeline.PriceValidationPipeline': 400,
}

# Enable and configure the AutoThrottle extension (disabled by default)
# See https://docs.scrapy.org/en/latest/topics/autothrottle.html
AUTOTHROTTLE_ENABLED = True
# The initial download delay
AUTOTHROTTLE_START_DELAY = 1
# The maximum download delay to be allowed in case of bad responses
AUTOTHROTTLE_MAX_DELAY = 10
# The average number of requests Scrapy should be sending in parallel to
# each web site
AUTOTHROTTLE_TARGET_CONCURRENCY = 5.0
# Enable showing throttling stats for every response received:
AUTOTHROTTLE_DEBUG = False

# Enable and configure HTTP caching (disabled by default)
# See https://docs.scrapy.org/en/latest/topics/http-cache.html
HTTPCACHE_ENABLED = True
HTTPCACHE_EXPIRATION_SECS = 0
HTTPCACHE_DIR = 'httpcache'
HTTPCACHE_IGNORE_HTTP_CODES = []
HTTPCACHE_STORAGE = 'scrapy.extensions.httpcache.FilesystemCacheStorage'

# Logging configuration
LOG_LEVEL = os.getenv('SCRAPER_LOG_LEVEL', 'INFO')
LOG_FORMAT = '%(asctime)s [%(name)s] %(levelname)s: %(message)s'
LOG_DATEFORMAT = '%Y-%m-%d %H:%M:%S'

# Custom settings for PricePoa
PRICEPOA_SETTINGS = {
    'MONGODB_URI': os.getenv('MONGODB_URI', 'mongodb://localhost:27017/pricepoa'),
    'MONGODB_DB': os.getenv('MONGODB_DB', 'pricepoa'),
    # Scheduler settings
    'SCHEDULER_ENABLED': os.getenv('ENABLE_SCRAPER', 'true').lower() == 'true',
    # Scraping behavior
    'MAX_ITEMS_PER_SPIDER': int(os.getenv('SCRAPER_MAX_ITEMS', '1000')),
    # Price validation
    'MIN_PRICE_KES': float(os.getenv('SCRAPER_MIN_PRICE', '0.01')),
    'MAX_PRICE_KES': float(os.getenv('SCRAPER_MAX_PRICE', '100000.0')),
}