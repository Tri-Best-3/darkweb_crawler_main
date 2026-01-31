"""
PLAY News Leak Site Spider
Target: http://k7kg3jqxang3wh7hnmaiokchk7qoebupfgoik6rha6mjpzwupwtj25yd.onion/
Type: Ransomware Leak Site (Card-Based Listing, List-Only)
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
    
    # 동적 URL 생성 (Config 로드 후 __init__에서 설정)
    start_urls = []

    custom_settings = {
        "ROBOTSTXT_OBEY": False,
        "DOWNLOAD_TIMEOUT": 120,
        "DOWNLOAD_DELAY": 3,  # 5초 → 3초로 단축
        # 사이트 부하 및 토르 노드 안정성을 위해 동시성 제한
        "CONCURRENT_REQUESTS": 1,
        # 전체 목록 기반 업데이트 감지를 위해 사용
        "COOKIES_ENABLED": True,
        # .onion 요청 처리를 위한 전용 미들웨어 설정
        "DOWNLOADER_MIDDLEWARES": {
            "tricrawl.middlewares.darknet_requests.RequestsDownloaderMiddleware": 543,
            "tricrawl.middlewares.TorProxyMiddleware": None,
            "scrapy.downloadermiddlewares.httpproxy.HttpProxyMiddleware": None,
        },
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
        global_conf = self.config.get("global", {})
        self.days_limit = global_conf.get("days_to_crawl", 3)
        override_days = kwargs.get("days_limit")
        if override_days is not None:
            try:
                self.days_limit = int(override_days)
            except ValueError:
                logger.warning("Invalid days_limit override", value=override_days)

        # 스파이더별 설정 로드 및 start_urls 구성
        spider_conf = self.config.get('spiders', {}).get('play_news', {})
        self.target_url = spider_conf.get('target_url')
        self.endpoints = spider_conf.get('endpoints', {})
        self.board_limits = spider_conf.get('boards', {})
        
        # config 기반 기본 페이지 제한(없으면 5)
        self.default_max_pages = int(spider_conf.get("default_max_pages", 5))

        if not self.target_url or not self.endpoints:
            logger.error("Target URL or Endpoints NOT found in config. Spider may not crawl anything.")

        logger.info(
            f"Loaded Config - Global Days: {self.days_limit}, Endpoints: {len(self.endpoints) if self.endpoints else 0}"
        )

    def get_max_pages_for_board(self, board_key: str) -> int:
        """boards 설정이 있으면 보드별로 페이지 제한, 없으면 default."""
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
            # 제목 = th.News의 첫 텍스트
            title = (card.xpath("normalize-space(text()[1])").get() or "").strip()
            if not title:
                continue

            # 카드 텍스트 전체
            parts = [t.strip() for t in card.css("*::text").getall() if t.strip()]
            all_text = " ".join(parts)

            # id
            onclick = card.attrib.get("onclick", "")
            m = RX_TOPIC_ID.search(onclick)
            topic_id = m.group(1) if m else ""

            # 메타 추출
            views_match = RX_VIEWS.search(all_text)
            views = int(views_match.group(1)) if views_match else None
            added = RX_ADDED.search(all_text).group(1) if RX_ADDED.search(all_text) else None
            pub = RX_PUB.search(all_text).group(1) if RX_PUB.search(all_text) else None

            # timestamp는 added 우선 (없으면 now)
            ts_iso = datetime.now(timezone.utc).isoformat()
            if added:
                try:
                    dt = datetime.strptime(added, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    if dt < cutoff:
                        continue
                    ts_iso = dt.isoformat()
                except Exception:
                    pass

            # URL은 클릭 불가, 식별용으로 topic.php?id= 넣어둠
            # url = response.url
            # if topic_id:
            #     url = response.urljoin(f"../topic.php?id={topic_id}")

            item = LeakItem()
            item["source"] = "PLAY"
            item["site_type"] = "Ransomware"
            item["category"] = "Ransomware"  # 랜섬웨어 그룹 통일
            item["author"] = "Play News"
            item["title"] = title
            # item["url"] = url
            item["url"] = response.url
            item["url"] = response.url
            item["timestamp"] = ts_iso
            item["views"] = views

            # content: 본문만 저장 (메타데이터는 별도 필드에 이미 저장됨)
            # all_text에서 메타 정보 제거
            content_text = all_text
            # id:xxx, views:xxx, added:xxx 등 메타 패턴 제거
            for pattern in [RX_VIEWS, RX_ADDED, RX_PUB]:
                content_text = pattern.sub("", content_text)
            content_text = content_text.strip()
            
            if len(content_text) > 1200:
                content_text = content_text[:1200] + "..."
            item["content"] = content_text

            dedup_key = topic_id or f"{title}|{added or pub or ''}"
            item["dedup_id"] = hashlib.md5(dedup_key.encode("utf-8")).hexdigest()

            # [Pre-Request Dedup] 이미 DB에 있으면 상세 페이지 요청 스킵
            if hasattr(self, 'seen_ids') and item["dedup_id"] in self.seen_ids:
                logger.debug(f"Pre-skip: {title[:30]} (already in DB)")
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

            # yield item
            
        # 페이지네이션 (boards 제한까지만)
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
        # 상세 페이지에서 본문 추출 (리스트 페이지 content 대체)
        detail_text = response.css(".News").xpath("string(.)").get() or ""
        # 공백 정리
        detail_text = " ".join(detail_text.split()).strip()
        
        if len(detail_text) > 2000:
            detail_text = detail_text[:2000] + "..."
        
        # 상세 본문이 있으면 교체, 없으면 기존 유지
        if detail_text:
            item["content"] = detail_text
        yield item