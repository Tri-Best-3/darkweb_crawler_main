"""
Scrapy Settings
"""
import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(PROJECT_ROOT / ".env")

BOT_NAME = "tricrawl"
SPIDER_MODULES = ["tricrawl.spiders"]
NEWSPIDER_MODULE = "tricrawl.spiders"

ROBOTSTXT_OBEY = False
CONCURRENT_REQUESTS = int(os.getenv("CONCURRENT_REQUESTS", 2))
DOWNLOAD_DELAY = int(os.getenv("CRAWL_DELAY", 5))
RANDOMIZE_DOWNLOAD_DELAY = True

CONCURRENT_REQUESTS_PER_DOMAIN = 1

TOR_PROXY_HOST = os.getenv("TOR_PROXY_HOST", "127.0.0.1")
TOR_PROXY_PORT = os.getenv("TOR_PROXY_PORT", "9050")
TOR_PROXY_SCHEME = os.getenv("TOR_PROXY_SCHEME", "socks5h")
TOR_PROXY = f"{TOR_PROXY_SCHEME}://{TOR_PROXY_HOST}:{TOR_PROXY_PORT}"

DOWNLOADER_MIDDLEWARES = {
    "tricrawl.middlewares.darknet_requests.RequestsDownloaderMiddleware": 900,
    "tricrawl.middlewares.TorProxyMiddleware": 740, 
    "scrapy.downloadermiddlewares.httpproxy.HttpProxyMiddleware": 750, 
}

ITEM_PIPELINES = {
    # "tricrawl.pipelines.ArchivePipeline": 10,
    "tricrawl.pipelines.DeduplicationPipeline": 50,
    "tricrawl.pipelines.KeywordFilterPipeline": 100,
    "tricrawl.pipelines.supabase.SupabasePipeline": 200,
    "tricrawl.pipelines.DiscordNotifyPipeline": 300,
}

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

KEYWORDS_CONFIG = PROJECT_ROOT / "config" / "keywords.yaml"

LOG_LEVEL = "DEBUG"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
LOG_DATEFORMAT = "%H:%M:%S"

LOG_FORMATTER = "tricrawl.log_formatter.QuietLogFormatter"


import structlog
import logging
import sys

LOG_ENABLED = True
LOG_FILE = os.getenv("TRICRAWL_LOG_FILE")

def setup_custom_logging():
    # Scrapy가 LOG_FILE 설정을 보고 FileLogObserver를 이미 부착했으므로,
    # 우리는 Console에 보여줄 "요약 정보(WARNING/INFO)"용 StreamHandler만 추가하면 됨.
    
    root_logger = logging.getLogger()
    
    # Console Handler (WARNING)
    has_stream = any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in root_logger.handlers)
    
    if not has_stream:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.ERROR)
        console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
        root_logger.addHandler(console_handler)
    else:
        for h in root_logger.handlers:
            if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
                h.setLevel(logging.ERROR)

setup_custom_logging()


EXTENSIONS = {
    "tricrawl.rich_progress.RichProgress": 500,
}

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False),
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

RETRY_ENABLED = True
RETRY_TIMES = 3
RETRY_HTTP_CODES = [500, 502, 503, 504, 408, 429]

DOWNLOAD_TIMEOUT = 60
VERIFY_SSL = os.getenv("VERIFY_SSL", "true").lower() in ("1", "true", "yes")

DEDUP_MAX_ENTRIES = int(os.getenv("DEDUP_MAX_ENTRIES", 20000))
DEDUP_MAX_DAYS = int(os.getenv("DEDUP_MAX_DAYS", 30))
DEDUP_PRUNE_UNSEEN = os.getenv("DEDUP_PRUNE_UNSEEN", "false").lower() in ("1", "true", "yes")

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/115.0"
