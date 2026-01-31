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
    Akira Ransomware Group Crawler
    
    Lineage:
    - Target: Akira ransomware victim list
    - Structure: JSON API based (/l endpoint)
    - site_type: "Ransomware"
    """
    
    name = "akira"
    
    # Custom settings to ensure proper Tor connection and headers
    custom_settings = {
        "DOWNLOADER_MIDDLEWARES": {
            "tricrawl.middlewares.darknet_requests.RequestsDownloaderMiddleware": 543,
            "tricrawl.middlewares.TorProxyMiddleware": None,
            "scrapy.downloadermiddlewares.httpproxy.HttpProxyMiddleware": None,
        },
        "DOWNLOAD_DELAY": 2,
        "VERIFY_SSL": False,  # Akira는 자체 서명 인증서 사용
        "DEFAULT_REQUEST_HEADERS": {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0',
            'Accept': '*/*',
            'X-Requested-With': 'XMLHttpRequest',
        }
    }

    def __init__(self, *args, **kwargs):
        """YAML 설정을 로드하고 start_urls를 구성한다."""
        super().__init__(*args, **kwargs)

        # 설정 파일 로드
        self.config = {}
        try:
            # 프로젝트 루트 (tricrawl/spiders -> ../../)
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
            # Fallback is dangerous, better to stop or warn heavily.
            # But consistent with others, we might leave it empty and fail gracefully in start_requests
            
    def start_requests(self):
        if not self.target_url:
            logger.error("[Akira] No target URL configured. Stopping.")
            return

        # Set allowed_domains based on target_url host
        domain = urlparse(self.target_url).hostname
        if domain:
            self.allowed_domains = [domain]
            
        self.base_url = self.target_url.rstrip('/')
        
        # Start with page 1
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
        
        # Stats에 총 조회 건수 누적
        self.crawler.stats.inc_value('items/discovered', len(victims))
        
        new_items_count = 0  # 새 아이템 카운터
        
        for v in victims:
            name = v.get('name', '').strip()
            desc = v.get('desc', '').strip()
            progress = v.get('progress', '')
            
            # Combine content
            content = f"{desc}\n\nProgress: {progress}"
            
            # Date parsing (Try common fields)
            date_str = v.get('date') or v.get('published') or v.get('time')
            if date_str:
                try:
                    # Try parsing "2023-10-25" or similar formats
                    # If it's pure text like "25 Oct 2023", we might need dateparser
                    posted_at = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc).isoformat()
                except ValueError:
                    posted_at = datetime.now(timezone.utc).isoformat()
            else:
                posted_at = datetime.now(timezone.utc).isoformat()

            # Use name and partial content for dedup key
            dedup_key = f"{name}|{self.name}"
            dedup_id = hashlib.md5(dedup_key.encode()).hexdigest()

            # [Pre-Request Dedup] Optimization
            if hasattr(self, 'seen_ids') and dedup_id in self.seen_ids:
                logger.debug(f"[Akira] Use cached item", title=name[:30])
                self.crawler.stats.inc_value('pre_dedup/skipped')
                continue
            
            new_items_count += 1  # 새 아이템 발견
            
            yield LeakItem(
                source="Akira",
                title=name,
                url=response.url, # API base URL
                author="Akira Group",
                timestamp=posted_at,
                content=content,
                category="Ransomware",
                site_type="Ransomware",
                dedup_id=dedup_id,
                views=None  # Standard for Ransomware sites (Abyss, Rhysida use None)
            )
        
        # Pagination: 새 아이템이 있을 때만 다음 페이지 요청
        if new_items_count > 0:
            yield self._make_api_request(page=page + 1)
        else:
            logger.info(f"[Akira] 페이지 {page}의 {len(victims)}개 항목 모두 기존 수집됨. 크롤링 조기 종료.")

