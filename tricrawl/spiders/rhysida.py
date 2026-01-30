import scrapy
from datetime import datetime, timezone
from tricrawl.items import LeakItem
import yaml
from pathlib import Path
import structlog

logger = structlog.get_logger(__name__)

class RhysidaSpider(scrapy.Spider):
    """
    Rhysida 랜섬웨어 그룹 크롤러 (Archive 페이지)
    
    Lineage:
    - 수집 대상: Rhysida의 전체 게시물 목록
    - 구조: div.border.m-2.p-2 가 하나의 카드
    - 날짜: 페이지에 날짜 정보가 없으므로 수집 시간(now)을 사용
    - site_type: "Ransomware"
    """
    
    name = "rhysida"
    # allowed_domains, start_urls -> Config 로드 후 설정
    
    # Tor 미들웨어 필수 설정
    custom_settings = {
        "DOWNLOADER_MIDDLEWARES": {
            "tricrawl.middlewares.darknet_requests.RequestsDownloaderMiddleware": 543,
            "tricrawl.middlewares.TorProxyMiddleware": None,
            "scrapy.downloadermiddlewares.httpproxy.HttpProxyMiddleware": None,
        },
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
    
    # Tor 미들웨어 필수 설정


    def parse(self, response):
        """
        Main Parser: div.border.m-2.p-2 블록을 순회하며 데이터 추출
        """
        # 각 게시물 카드는 'border m-2 p-2' 클래스를 가짐
        posts = response.css('div.border.m-2.p-2')
        
        for post in posts:
            # 1. 제목 추출 (div.h4 안에 있는 a 태그 텍스트)
            title = post.css('div.h4 a::text').get()
            if not title:
                continue  # 제목 없으면 스킵
            
            title = title.strip()
            
            # 2. 설명/본문 추출
            # 제목 div 바로 다음 형제 div.m-2가 본문임
            # CSS 선택자로 div.col-10 > div:nth-child(2) 형태로 접근 가능
            description_parts = post.css('div.col-10 > div:nth-child(2)::text').getall()
            description = " ".join([d.strip() for d in description_parts if d.strip()])
            
            # 3. 추가 상태 정보 (Sold 여부, 진행률 등)
            status_text = post.css('div.text-danger::text').get('')
            progress = post.css('div.progress-bar::text').get('')
            
            # 본문에 상태 정보 합치기
            full_content = f"{description}\n\n[Status: {status_text}] [Progress: {progress}]"
            
            # 4. 링크 추출 (More 버튼이나 제목 링크)
            # 여기서는 제목 링크를 원본 링크로 사용
            target_url = post.css('div.h4 a::attr(href)').get()
            
            yield LeakItem(
                source="Rhysida",
                title=title,
                url=target_url or response.url,
                author="Rhysida Group",  # 작성자는 항상 Rhysida
                timestamp=datetime.now(timezone.utc).isoformat(),  # 날짜 없음 -> 현재시간
                content=full_content,
                category="Ransomware",
                site_type="Ransomware",  # ⭐ 필수
                dedup_id=None,
                views=None
            )