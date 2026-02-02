import scrapy
import hashlib
from datetime import datetime, timezone
from tricrawl.items import LeakItem
import yaml
from pathlib import Path
import structlog

logger = structlog.get_logger(__name__)

class RhysidaSpider(scrapy.Spider):
    """
    Rhysida Ransomware Group Crawler.
    Parses the full victim list from the archive page.
    """
    
    name = "rhysida"
    
    custom_settings = {
        "DOWNLOADER_MIDDLEWARES": {
            "tricrawl.middlewares.darknet_requests.RequestsDownloaderMiddleware": 543,
            "tricrawl.middlewares.TorProxyMiddleware": None,
            "scrapy.downloadermiddlewares.httpproxy.HttpProxyMiddleware": None,
        },
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
                    self.config = full_conf.get('spiders', {}).get('rhysida', {})
                logger.info(f"Config loaded from {config_path}")
            else:
                logger.warning("Config file not found, using defaults")
                
        except Exception as e:
            logger.error(f"Config load failed: {e}")

        self.target_url = self.config.get('target_url')
        if self.target_url:
            self.start_urls = [self.target_url]
        else:
            logger.error("Target URL NOT found in config for rhysida.")
            self.start_urls = []
    
    def parse(self, response):
        """Parses victim cards (div.border.m-2.p-2)."""
        posts = response.css('div.border.m-2.p-2')
        
        for post in posts:
            title = post.css('div.h4 a::text').get()
            if not title:
                continue
            
            title = title.strip()
            
            description_parts = post.css('div.col-10 > div:nth-child(2)::text').getall()
            description = " ".join([d.strip() for d in description_parts if d.strip()])
            
            status_text = post.css('div.text-danger::text').get('')
            progress = post.css('div.progress-bar::text').get('')
            
            full_content = f"{description}\n\n[Status: {status_text}] [Progress: {progress}]"
            
            target_url = post.css('div.h4 a::attr(href)').get()
            
            dedup_key = f"{title}|rhysida"
            dedup_id = hashlib.md5(dedup_key.encode()).hexdigest()
            
            if hasattr(self, 'seen_ids') and dedup_id in self.seen_ids:
                logger.debug(f"[Rhysida] Pre-skip: {title[:30]} (already in DB)")
                self.crawler.stats.inc_value('pre_dedup/skipped')
                continue
            
            yield LeakItem(
                source="Rhysida",
                title=title,
                url=target_url or response.url,
                author="Rhysida Group",
                timestamp=datetime.now(timezone.utc).isoformat(),
                content=full_content,
                category="Ransomware",
                site_type="Ransomware",
                dedup_id=dedup_id,
                views=None
            )