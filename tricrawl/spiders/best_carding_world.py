"""
Best Carding World Forum Spider (phpBB)
Target: http://bestteermb42clir6ux7xm76d4jjodh3fpahjqgbddbmfrgp4skg2wqd.onion/
"""
import scrapy
import structlog
import yaml
from pathlib import Path
from tricrawl.items import LeakItem
from datetime import datetime, timedelta, timezone
import re
import hashlib

logger = structlog.get_logger(__name__)

RX_LASTPOST_DT = re.compile(r"\b[A-Z][a-z]{2}\s+[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}\s+\d{1,2}:\d{2}\s+[ap]m\b")
RX_FORUM_DT = re.compile(
    r"\b[A-Z][a-z]{2}\s+[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}\s+\d{1,2}:\d{2}\s+[ap]m\b"
)


class BestCardingWorldSpider(scrapy.Spider):
    """
    Spiders the Best Carding World forum (phpBB based).
    """
    
    name = "best_carding_world"
    start_urls = []
    
    custom_settings = {
        'ROBOTSTXT_OBEY': False,
        'DOWNLOAD_TIMEOUT': 120,
        'USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/115.0',
        'COOKIES_ENABLED': True,
        'DOWNLOADER_MIDDLEWARES': {
            'tricrawl.middlewares.darknet_requests.RequestsDownloaderMiddleware': 543,
            'tricrawl.middlewares.TorProxyMiddleware': None,
            'scrapy.downloadermiddlewares.httpproxy.HttpProxyMiddleware': None,
        }
    }
    
    def __init__(self, *args, **kwargs):
        """Initializes spider with config from crawler_config.yaml"""
        super().__init__(*args, **kwargs)
        
        self.config = {}
        try:
            project_root = Path(__file__).resolve().parents[2]
            config_path = project_root / "config" / "crawler_config.yaml"
            
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    self.config = yaml.safe_load(f) or {}
                logger.info(f"Config loaded from {config_path}")
            else:
                logger.warning("Config file not found, using defaults")
                
        except Exception as e:
            logger.error(f"Config load failed: {e}")
            
        global_conf = self.config.get('global', {})
        self.days_limit = global_conf.get('days_to_crawl', 3)
        override_days = kwargs.get("days_limit")
        if override_days is not None:
            try:
                self.days_limit = int(override_days)
            except ValueError:
                logger.warning("Invalid days_limit override", value=override_days)
        
        spider_conf = self.config.get('spiders', {}).get('best_carding_world', {})
        self.target_url = spider_conf.get('target_url')
        self.endpoints = spider_conf.get('endpoints', {})
        self.board_limits = spider_conf.get('boards', {})
        
        if self.target_url and self.endpoints:
            base = self.target_url.rstrip('/')
            for key, path in self.endpoints.items():
                clean_path = path.lstrip('/')
                full_url = f"{base}/{clean_path}"
                self.start_urls.append(full_url)
                logger.debug(f"Added start URL: {full_url}")
        else:
            logger.error("Target URL or Endpoints NOT found in config.")

        self.default_max_pages = 5
        logger.info(f"Loaded Config - Global Days: {self.days_limit}, URLs: {len(self.start_urls)}")

    def start_requests(self):
        base = (self.target_url or "").rstrip("/")
        for key, path in (self.endpoints or {}).items():
            clean_path = str(path).lstrip("/")
            full_url = f"{base}/{clean_path}"
            yield scrapy.Request(
                url=full_url,
                callback=self.parse,
                meta={"category": key, "board_key": key},
                dont_filter=True,
            )

    def extract_lastpost_dt_text(self, row):
        """Extracts date string from lastpost column."""
        lastpost_text = " ".join(row.css("dd.lastpost *::text").getall()).strip()
        m = RX_FORUM_DT.search(lastpost_text)
        return m.group(0) if m else ""
    
    def parse_forum_dt(self, dt_str: str):
        """Parses phpBB specific date format."""
        if not dt_str:
            return None
        try:
            # Format: Sun Jan 18, 2026 11:36 am
            dt = datetime.strptime(dt_str, "%a %b %d, %Y %I:%M %p")
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    def parse(self, response):
        """Parses thread list."""
        logger.info(f"Scanning: {response.url}")
        
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.days_limit)

        for row in response.css("li.row"):
            title = row.css("a.topictitle::text").get()
            href  = row.css("a.topictitle::attr(href)").get()

            if not title or not href:
                continue

            url = response.urljoin(href)
            author = row.css("dd.lastpost a.username-coloured::text").get() or "Unknown"

            dt_text = self.extract_lastpost_dt_text(row)
            dt = self.parse_forum_dt(dt_text)
            
            # Date limit check
            if dt and dt < cutoff:
                logger.debug(f"Skipping old post: {title[:30]}")
                continue
            
            ts_iso = dt.isoformat() if dt else datetime.now(timezone.utc).isoformat()
            
            item = LeakItem()
            item["source"] = "BestCardingWorld"
            item["title"] = title.strip()
            item["url"] = url
            item["author"] = author.strip()
            item["timestamp"] = ts_iso
            item["content"] = ""
            item["category"] = response.meta.get("category") or "none"
            item["site_type"] = "Forum"
            
            # Views extraction
            try:
                raw_views = row.css("dd.views::text").get()
                if raw_views:
                    m = re.search(r"(\d+)", raw_views)
                    item["views"] = int(m.group(1)) if m else None
                else:
                    item["views"] = None
            except Exception:
                item["views"] = None

            # Pre-Request Deduplication
            dedup_key = f"{item['title']}|{item['author']}"
            item["dedup_id"] = hashlib.md5(dedup_key.encode()).hexdigest()
            
            if hasattr(self, 'seen_ids') and item["dedup_id"] in self.seen_ids:
                logger.debug(f"Skipping duplicate: {title[:30]}")
                self.crawler.stats.inc_value('pre_dedup/skipped')
                continue

            yield scrapy.Request(
                url=url,
                callback=self.parse_topic,
                cb_kwargs={"item": item},
                meta=response.meta, 
                dont_filter=True,
            )

    def parse_topic(self, response, item: LeakItem):
        """Parses thread content."""
        # Priority: div.postbody .content -> div.postbody all
        text_parts = response.css("div.postbody .content *::text").getall()
        if not text_parts:
            text_parts = response.css("div.postbody *::text").getall()

        tmp = " ".join(text_parts)
        content = " ".join((tmp or "").split())

        MAX_CONTENT_LEN = 2000
        if len(content) > MAX_CONTENT_LEN:
            content = content[:MAX_CONTENT_LEN] + " ..."

        item["content"] = content

        yield item
