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
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
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

    def get_max_pages_for_board(self, board_key: str) -> int:
        try:
            v = (self.board_limits or {}).get(board_key)
            if v is None:
                return int(self.default_max_pages)
            return int(v)
        except Exception:
            return int(self.default_max_pages)
        
    def _next_page_url(self, response, page: int) -> str | None:
        """
        phpBB forum pagination (direct):
        /viewforum.php?f=30&start=50 형태로 직접 이동
        - f: 게시판 ID 유지
        - start: (page * TOPICS_PER_PAGE)로 계산
        """
        TOPICS_PER_PAGE = 25  # 필요하면 10/20/50으로 조정
        new_start = page * TOPICS_PER_PAGE  # page=1 -> start=25, page=2 -> start=50 ...

        u = urlparse(response.url)
        qs = parse_qs(u.query)

        # f 파라미터가 없으면 다음 페이지를 만들 수 없음
        # (endpoint가 viewforum.php?f=xx 형태여야 함)
        if "f" not in qs or not qs["f"]:
            logger.warning("Missing forum id (f=) in url; cannot paginate", url=response.url)
            return None

        # start만 덮어쓰기
        qs["start"] = [str(new_start)]

        new_query = urlencode(qs, doseq=True)

        # 혹시 다른 경로로 들어왔다면 viewforum.php로 고정하고 싶을 때:
        path = u.path
        # 예: path가 /viewforum.php가 아닐 수 있으면 강제
        if not path.endswith("viewforum.php"):
            # 현재 프로젝트 구조상 대부분 viewforum.php일 텐데, 안전장치로 둠
            path = "/viewforum.php"

        return urlunparse((u.scheme, u.netloc, path, u.params, new_query, u.fragment))


    def start_requests(self):
        base = (self.target_url or "").rstrip("/")
        for key, path in (self.endpoints or {}).items():
            clean_path = str(path).lstrip("/")
            full_url = f"{base}/{clean_path}"
            yield scrapy.Request(
                url=full_url,
                callback=self.parse,
                meta={"category": key, "board_key": key, "page": 1},
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

        board_key = response.meta.get("board_key") or response.meta.get("category") or "default"
        page = int(response.meta.get("page", 1))
        max_pages = self.get_max_pages_for_board(board_key)

        row_count = 0

        for row in response.css("li.row"):
            row_count += 1
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

        if page < max_pages:
            next_url = self._next_page_url(response, page)
            if next_url and row_count > 0:
                yield scrapy.Request(
                    url=next_url,
                    callback=self.parse,
                    meta={**response.meta, "page": page + 1},
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
