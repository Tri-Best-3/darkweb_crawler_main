"""
BFDX Forum Spider
Target: http://bfdxjkv5e2z3ilrifzbnvxxvhbzsj67akjpj3zc6smzr4vv6oz565gyd.onion/
Type: XenForo-like or Custom Forum
"""
import scrapy
import hashlib
import structlog
import yaml
from pathlib import Path
from datetime import datetime, timezone, timedelta
from tricrawl.items import LeakItem

logger = structlog.get_logger(__name__)

class BfdxSpider(scrapy.Spider):
    """
    BFDX 포럼 크롤러.
    
    Refactored to load settings from crawler_config.yaml
    """
    name = "bfdx"  # Config Key와 일치시킴
    
    # 동적 URL 생성 (Config 로드 후 __init__에서 설정)
    start_urls = []

    custom_settings = {
        "ROBOTSTXT_OBEY": False,
        "DOWNLOAD_TIMEOUT": 120,
        "CONCURRENT_REQUESTS": 1,
        "COOKIES_ENABLED": True,
        "DOWNLOADER_MIDDLEWARES": {
            "tricrawl.middlewares.darknet_requests.RequestsDownloaderMiddleware": 543,
            "tricrawl.middlewares.TorProxyMiddleware": None,
            "scrapy.downloadermiddlewares.httpproxy.HttpProxyMiddleware": None,
        }
    }

    def __init__(self, *args, **kwargs):
        """YAML 설정을 로드하고 start_urls/board limits를 구성한다."""
        super().__init__(*args, **kwargs)

        # 설정 파일 로드
        self.config = {}
        try:
            # 프로젝트 루트 (tricrawl/spiders -> ../../)
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

        # 전역 설정 적용
        global_conf = self.config.get('global', {})
        self.days_limit = global_conf.get('days_to_crawl', 14)
        
        # 스파이더별 설정 로드
        spider_conf = self.config.get('spiders', {}).get('bfdx', {})
        self.target_url = spider_conf.get('target_url')
        self.endpoints = spider_conf.get('endpoints', {})
        self.board_limits = spider_conf.get('boards', {})
        
        # 기본값
        self.default_max_pages = int(spider_conf.get("default_max_pages", 5))
        
        logger.info(f"Loaded Config - Global Days: {self.days_limit}")

        if not self.target_url:
            logger.error("Target URL NOT found in config for bfdx.")

    def start_requests(self):
        base = (self.target_url or "").rstrip("/")
        for key, path in (self.endpoints or {}).items():
            # path가 '/'인 경우 처리
            clean_path = str(path).lstrip("/")
            full_url = f"{base}/{clean_path}" if clean_path else base
            
            yield scrapy.Request(
                url=full_url,
                callback=self.parse,
                meta={"category": key, "board_key": key, "page": 1},
                dont_filter=True,
            )

    def parse(self, response):
        logger.info(f"BFDX Page Accessed: {response.url}")

        # 1. Main Page / Forum List (Existing Logic)
        nodes = response.css("div.node.node--forum")
        if nodes:
            logger.info(f"Found {len(nodes)} forum nodes.")
            for forum in nodes:
                title = forum.css("a.node-extra-title::text").get()
                url = forum.css("a.node-extra-title::attr(href)").get()
                author = forum.css("div.node-extra-row .username::text").get() or "Unknown"
                timestamp = forum.css("div.node-extra-row time::attr(datetime)").get()

                if not title or not url:
                    continue

                full_url = response.urljoin(url)
                
                # 상세 페이지 요청
                yield scrapy.Request(
                    full_url,
                    callback=self.parse_thread,
                    meta={
                        "title": title.strip(),
                        "author": author,
                        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
                        "category": response.meta.get("category", "Main"),
                        "views": None, # Index node usually doesn't show views for last post
                    }
                )

        # 2. Thread List (New Logic based on bfdx.md)
        threads = response.css("div.structItem--thread")
        if threads:
            logger.info(f"Found {len(threads)} threads.")
            cutoff = datetime.now(timezone.utc) - timedelta(days=self.days_limit)
            
            for thread in threads:
                title = thread.css("div.structItem-title a::text").get()
                url = thread.css("div.structItem-title a::attr(href)").get()
                author = thread.css("a.username::text").get() or "Unknown"
                timestamp_str = thread.css("time.u-dt::attr(datetime)").get()
                
                # 날짜 파싱 및 cutoff 필터링
                dt = None
                if timestamp_str:
                    try:
                        dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    except ValueError:
                        pass
                
                if dt and dt < cutoff:
                    logger.debug(f"Skipping old post: {title[:30] if title else 'N/A'} ({dt})")
                    continue
                
                # Views Extraction
                views_str = thread.css("div.structItem-cell--meta dl.structItem-minor dd::text").get()
                views = self.parse_views(views_str)

                if not title or not url:
                    continue

                full_url = response.urljoin(url)

                # [Pre-Request Dedup] dedup_id 생성 및 중복 체크
                dedup_key = f"{title.strip()}|{author}"
                dedup_id = hashlib.md5(dedup_key.encode()).hexdigest()
                
                if hasattr(self, 'seen_ids') and dedup_id in self.seen_ids:
                    logger.debug(f"Pre-skip: {title[:30]} (already in DB)")
                    self.crawler.stats.inc_value('pre_dedup/skipped')
                    continue

                yield scrapy.Request(
                    full_url,
                    callback=self.parse_thread,
                    meta={
                        "title": title.strip(),
                        "author": author,
                        "timestamp": timestamp_str or datetime.now(timezone.utc).isoformat(),
                        "category": response.meta.get("category", "Main"),
                        "views": views,
                        "dedup_id": dedup_id,  # 상세 페이지에서 사용
                    }
                )

    def parse_views(self, views_str):
        if not views_str:
            return None
        try:
            s = views_str.lower().strip()
            if 'k' in s:
                return int(float(s.replace('k', '')) * 1000)
            elif 'm' in s:
                return int(float(s.replace('m', '')) * 1000000)
            else:
                return int(s.replace(',', ''))
        except:
            return None

    def parse_thread(self, response):
        """상세 글 페이지에서 본문(content) 추출 + 작성자 보강 + 본문 정제"""
        title = response.meta["title"]
        author = response.meta["author"]
        timestamp = response.meta["timestamp"]
        category = response.meta["category"]

        # 작성자 보강
        page_author = response.css("span.username::text").get() or response.css("a.username::text").get()
        if page_author:
            author = page_author.strip()

        # 본문 추출 시도
        selectors = [
            "div.bbWrapper *::text",
            "div.message-body *::text",
            "div.node-extra-row *::text",
            "article.message *::text",
            "article *::text"
        ]

        content = []
        for sel in selectors:
            content = response.css(sel).getall()
            if content:
                break

        if not content:
            content = response.css("*::text").getall()

        # 본문 정제
        skip_patterns = ["*** Hidden text", "Click to expand", "said:"]
        clean_lines = []
        for c in content:
            line = c.strip()
            if not line: continue
            if any(p in line for p in skip_patterns): continue
            if len(line) < 3: continue
            clean_lines.append(line)

        content_text = "\n".join(clean_lines)

        item = LeakItem()
        item["source"] = "BFDX Forum"
        item["site_type"] = "Forum"
        item["category"] = category
        item["title"] = title
        item["url"] = response.url
        item["author"] = author
        item["timestamp"] = timestamp
        item["content"] = content_text or "[본문 추출 실패]"
        
        # 필드 추가: views
        item["views"] = response.meta.get("views") 

        # dedup_id는 리스트 페이지에서 이미 생성됨 (Pre-Request Dedup)
        item["dedup_id"] = response.meta.get("dedup_id")

        yield item