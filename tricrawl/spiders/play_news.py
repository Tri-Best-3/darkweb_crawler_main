"""
PLAY News Leak Site Spider
Target: http://k7kg3jqxang3wh7hnmaiokchk7qoebupfgoik6rha6mjpzwupwtj25yd.onion/
"""
import scrapy
import structlog
import yaml
import re
import hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta
from tricrawl.items import LeakItem

logger = structlog.get_logger(__name__)

RX_TOPIC_ID = re.compile(r"viewtopic\('([^']+)'\)")
RX_VIEWS = re.compile(r"views:\s*(\d+)", re.I)
RX_ADDED = re.compile(r"added:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", re.I)
RX_PUB = re.compile(r"publication date:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", re.I)

class PlayNewsSpider(scrapy.Spider):
    name = "play_news"
    start_urls = []

    custom_settings = {
        "ROBOTSTXT_OBEY": False,
        "DOWNLOAD_TIMEOUT": 120,
        "DOWNLOAD_DELAY": 3,
        "CONCURRENT_REQUESTS": 1,
        "COOKIES_ENABLED": True,
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
                    self.config = yaml.safe_load(f) or {}
                logger.info(f"Config loaded from {config_path}")
            else:
                logger.warning("Config file not found, using defaults")
                
        except Exception as e:
            logger.error(f"Config load failed: {e}")

        global_conf = self.config.get("global", {})
        self.days_limit = global_conf.get("days_to_crawl", 3)
        override_days = kwargs.get("days_limit")
        if override_days is not None:
            try:
                self.days_limit = int(override_days)
            except ValueError:
                logger.warning("Invalid days_limit override", value=override_days)

        spider_conf = self.config.get('spiders', {}).get('play_news', {})
        self.target_url = spider_conf.get('target_url')
        self.endpoints = spider_conf.get('endpoints', {})
        self.board_limits = spider_conf.get('boards', {})
        self.default_max_pages = int(spider_conf.get("default_max_pages", 5))

        if not self.target_url or not self.endpoints:
            logger.error("Target URL or Endpoints NOT found in config.")

        logger.info(
            f"Loaded Config - Global Days: {self.days_limit}, Endpoints: {len(self.endpoints) if self.endpoints else 0}"
        )

    def get_max_pages_for_board(self, board_key: str) -> int:
        try:
            v = self.board_limits.get(board_key)
            if v is None:
                return int(self.default_max_pages)
            return int(v)
        except Exception:
            return int(self.default_max_pages)

    def start_requests(self):
        base = (self.target_url or "").rstrip("/")
        for board_key, path in (self.endpoints or {}).items():
            full_url = f"{base}/{str(path).lstrip('/')}"
            yield scrapy.Request(
                url=full_url,
                callback=self.parse,
                meta={"category": board_key, "board_key": board_key, "page": 1},
                dont_filter=True,
            )

    def parse(self, response):
        logger.info("PLAY parse", url=response.url, status=response.status)

        cutoff = datetime.now(timezone.utc) - timedelta(days=self.days_limit)
        
        board_key = response.meta.get("board_key") or response.meta.get("category") or "news"
        page = int(response.meta.get("page", 1))
        max_pages = self.get_max_pages_for_board(board_key)

        for card in response.css("th.News"):
            title = (card.xpath("normalize-space(text()[1])").get() or "").strip()
            if not title:
                continue

            parts = [t.strip() for t in card.css("*::text").getall() if t.strip()]
            all_text = " ".join(parts)

            onclick = card.attrib.get("onclick", "")
            m = RX_TOPIC_ID.search(onclick)
            topic_id = m.group(1) if m else ""

            views_match = RX_VIEWS.search(all_text)
            views = int(views_match.group(1)) if views_match else None
            added = RX_ADDED.search(all_text).group(1) if RX_ADDED.search(all_text) else None
            pub = RX_PUB.search(all_text).group(1) if RX_PUB.search(all_text) else None

            ts_iso = datetime.now(timezone.utc).isoformat()
            if added:
                try:
                    dt = datetime.strptime(added, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    if dt < cutoff:
                        continue
                    ts_iso = dt.isoformat()
                except Exception:
                    pass

            item = LeakItem()
            item["source"] = "PLAY"
            item["site_type"] = "Ransomware"
            item["category"] = "Ransomware"
            item["author"] = "Play News"
            item["title"] = title
            item["url"] = response.url
            item["timestamp"] = ts_iso
            item["views"] = views

            content_text = all_text
            for pattern in [RX_VIEWS, RX_ADDED, RX_PUB]:
                content_text = pattern.sub("", content_text)
            content_text = content_text.strip()
            
            if len(content_text) > 1200:
                content_text = content_text[:1200] + "..."
            item["content"] = content_text

            dedup_key = topic_id or f"{title}|{added or pub or ''}"
            item["dedup_id"] = hashlib.md5(dedup_key.encode("utf-8")).hexdigest()

            if hasattr(self, 'seen_ids') and item["dedup_id"] in self.seen_ids:
                logger.debug(f"Pre-skip: {title[:30]}")
                self.crawler.stats.inc_value('pre_dedup/skipped')
                continue

            if not topic_id:
                continue

            topic_url = response.urljoin(f"topic.php?id={topic_id}")

            yield scrapy.Request(
                url=topic_url,
                callback=self.parse_topic,
                meta={**response.meta, "item": item, "topic_id": topic_id},
                dont_filter=True,
            )

        if page < max_pages:
            next_page = page + 1
            next_url = response.urljoin(f"../index.php?page={next_page}")
            yield scrapy.Request(
                url=next_url,
                callback=self.parse,
                meta={**response.meta, "page": next_page},
                dont_filter=True,
            )

    def parse_topic(self, response):
        item = response.meta["item"]
        detail_text = response.css(".News").xpath("string(.)").get() or ""
        detail_text = " ".join(detail_text.split()).strip()
        
        if len(detail_text) > 2000:
            detail_text = detail_text[:2000] + "..."
        
        if detail_text:
            item["content"] = detail_text
        yield item