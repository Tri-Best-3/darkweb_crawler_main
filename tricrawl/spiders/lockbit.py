import scrapy
from datetime import datetime, timezone
from tricrawl.items import LeakItem
import yaml
from pathlib import Path
import structlog

logger = structlog.get_logger(__name__)

class LockBitSpider(scrapy.Spider):
    name = "lockbit"
    # Config 로드 후 설정
    
    custom_settings = {
        "DOWNLOADER_MIDDLEWARES": {
            "tricrawl.middlewares.darknet_requests.RequestsDownloaderMiddleware": 543,
            "tricrawl.middlewares.TorProxyMiddleware": None,
            "scrapy.downloadermiddlewares.httpproxy.HttpProxyMiddleware": None,
        },
        "DOWNLOAD_DELAY": 3,
    }

    def __init__(self, *args, **kwargs):
        """YAML 설정을 로드하고 start_urls를 구성한다."""
        super().__init__(*args, **kwargs)

        self.config = {}
        try:
            project_root = Path(__file__).resolve().parents[2]
            config_path = project_root / "config" / "crawler_config.yaml"
            
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    full_conf = yaml.safe_load(f) or {}
                    self.config = full_conf.get('spiders', {}).get('lockbit', {})
                logger.info(f"Config loaded from {config_path}")
            else:
                logger.warning("Config file not found, using defaults")
                
        except Exception as e:
            logger.error(f"Config load failed: {e}")

        self.target_url = self.config.get('target_url')
        if self.target_url:
            self.start_urls = [self.target_url]
        else:
            logger.error("Target URL NOT found in config for lockbit.")
            self.start_urls = []

    def parse(self, response):
        self.logger.info(f"[LockBit] Status: {response.status}")
        
        # LockBit 3.0은 div.post-block 구조를 많이 사용
        posts = response.css('div.post-block, a.post-block')
        
        for post in posts:
            title = post.css('div.post-title::text, h3::text').get()
            if not title:
                continue
                
            link = post.attrib.get('href')
            url = response.urljoin(link) if link else response.url
            
            # 설명/본문
            desc = post.css('div.post-block-text::text, p::text').getall()
            content = " ".join([d.strip() for d in desc if d.strip()])
            
            # 날짜 (Deadline 등)
            date_str = post.css('div.post-timer::text').get('')
            # Post-hoc views extraction from full text if available
            # Note: We don't have full body text in list view sometimes, but 'desc' captures it.
            # Using regex to find "Views: <number>"
            # Views extraction (HTML based on user sample)
            # <div class="views"> ... <span>31001</span> ... </div>
            views_val = None
            try:
                # 1. 시도: div.views 내부의 두 번째 div 안의 span (숫자만 있는 span)
                views_candidate = post.css('div.views div:nth-child(2) span::text').get()
                if not views_candidate:
                    # 2. 시도: bold 스타일이 적용된 span
                    views_candidate = post.css('div.views span[style*="font-weight: bold"]::text').get()
                
                if views_candidate:
                    # 공백/콤마 제거 후 숫자만 추출
                    clean_views = views_candidate.strip().replace(",", "")
                    if clean_views.isdigit():
                        views_val = int(clean_views)
            except Exception:
                pass
            
            yield LeakItem(
                source="LockBit",
                title=title.strip(),
                url=url,
                author="LockBit 3.0",
                timestamp=datetime.now(timezone.utc).isoformat(),
                content=f"Deadline: {date_str}\n\n{content}",
                category="Ransomware",
                site_type="Ransomware",
                dedup_id=None,
                views=views_val
            )
