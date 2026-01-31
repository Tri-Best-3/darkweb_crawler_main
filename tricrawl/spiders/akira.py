import scrapy
import json
import hashlib
import yaml
import structlog
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlparse
from tricrawl.items import LeakItem

logger = structlog.get_logger(__name__)


class AkiraSpider(scrapy.Spider):
    """
    Akira Ransomware Group Crawler.
    Target: JSON API endpoint (/l)
    """
    
    name = "akira"
    
    custom_settings = {
        "DOWNLOADER_MIDDLEWARES": {
            "tricrawl.middlewares.darknet_requests.RequestsDownloaderMiddleware": 543,
            "tricrawl.middlewares.TorProxyMiddleware": None,
            "scrapy.downloadermiddlewares.httpproxy.HttpProxyMiddleware": None,
        },
        "DOWNLOAD_DELAY": 2,
        "VERIFY_SSL": False,
        "DEFAULT_REQUEST_HEADERS": {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0',
            'Accept': '*/*',
            'X-Requested-With': 'XMLHttpRequest',
        }
    }

    def __init__(self, *args, **kwargs):
        """Loads configuration and executes initial setup."""
        super().__init__(*args, **kwargs)

        self.config = {}
        try:
            project_root = Path(__file__).resolve().parents[2]
            config_path = project_root / "config" / "crawler_config.yaml"
            
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    full_conf = yaml.safe_load(f) or {}
                    self.config = full_conf.get('spiders', {}).get('akira', {})
                logger.info(f"Config loaded from {config_path}")
            else:
                logger.warning("Config file not found, using defaults")
                
        except Exception as e:
            logger.error(f"Config load failed: {e}")

        self.target_url = self.config.get('target_url')
        if not self.target_url:
            logger.error("Target URL NOT found in config for akira.")
            
    def start_requests(self):
        if not self.target_url:
            logger.error("[Akira] No target URL configured. Stopping.")
            return

        domain = urlparse(self.target_url).hostname
        if domain:
            self.allowed_domains = [domain]
            
        self.base_url = self.target_url.rstrip('/')
        yield self._make_api_request(page=1)

    def _make_api_request(self, page):
        url = f"{self.base_url}/l?page={page}&sort=name:asc"
        logger.info(f"[Akira] Requesting page {page}", url=url)
        return scrapy.Request(
            url=url,
            callback=self.parse,
            meta={'page': page},
            dont_filter=True 
        )

    def parse(self, response):
        page = response.meta['page']
        
        try:
            data = response.json()
        except json.JSONDecodeError:
            logger.error(f"[Akira] Failed to parse JSON on page {page}", sample=response.text[:100])
            return

        victims = data.get('objects', [])
        if not victims:
            logger.info(f"[Akira] No more victims found on page {page}. Stopping.")
            return

        logger.info(f"[Akira] Found items on page {page}", count=len(victims))
        self.crawler.stats.inc_value('items/discovered', len(victims))
        
        new_items_count = 0 
        
        for v in victims:
            name = v.get('name', '').strip()
            desc = v.get('desc', '').strip()
            progress = v.get('progress', '')
            
            content = f"{desc}\n\nProgress: {progress}"
            
            date_str = v.get('date') or v.get('published') or v.get('time')
            if date_str:
                try:
                    posted_at = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc).isoformat()
                except ValueError:
                    posted_at = datetime.now(timezone.utc).isoformat()
            else:
                posted_at = datetime.now(timezone.utc).isoformat()

            dedup_key = f"{name}|{self.name}"
            dedup_id = hashlib.md5(dedup_key.encode()).hexdigest()

            if hasattr(self, 'seen_ids') and dedup_id in self.seen_ids:
                logger.debug(f"[Akira] Use cached item", title=name[:30])
                self.crawler.stats.inc_value('pre_dedup/skipped')
                continue
            
            new_items_count += 1
            
            yield LeakItem(
                source="Akira",
                title=name,
                url=response.url,
                author="Akira Group",
                timestamp=posted_at,
                content=content,
                category="Ransomware",
                site_type="Ransomware",
                dedup_id=dedup_id,
                views=None
            )
        
        if new_items_count > 0:
            yield self._make_api_request(page=page + 1)
        else:
            logger.info(f"[Akira] Page {page}: All {len(victims)} items were skipped. Stopping early.")
