import scrapy
import hashlib
import re
from datetime import datetime, timezone, timedelta
from tricrawl.items import LeakItem
import yaml
from pathlib import Path
import structlog

logger = structlog.get_logger(__name__)


class LockBitSpider(scrapy.Spider):
    """
    LockBit 랜섬웨어 그룹 Leak Site 스파이더.
    
    주요 기능:
    - 리스트 페이지에서 피해 기업 정보 추출
    - Updated 날짜 파싱 (예: "Updated: 05 Dec, 2025, 10:16 UTC")
    - Views 추출 (숫자 span 요소)
    - dedup_id 생성 (title + lockbit 기반 해시)
    """
    name = "lockbit 3.0"
    
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
        
        # 전역 설정 적용
        try:
            project_root = Path(__file__).resolve().parents[2]
            config_path = project_root / "config" / "crawler_config.yaml"
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    fc = yaml.safe_load(f) or {}
                    global_conf = fc.get('global', {})
                    self.days_limit = global_conf.get('days_to_crawl', 14)
            else:
                self.days_limit = 14
        except Exception:
            self.days_limit = 14
        logger.info(f"Loaded Config - Global Days: {self.days_limit}")

    def _parse_date(self, date_text: str) -> str:
        """
        Updated 날짜 문자열을 ISO 8601 형식으로 변환.
        
        예시 입력: "Updated: 05 Dec, 2025,  10:16 UTC"
        예시 출력: "2025-12-05T10:16:00+00:00"
        """
        if not date_text:
            return datetime.now(timezone.utc).isoformat()
        
        try:
            # 정규식으로 날짜 부분 추출: "05 Dec, 2025,  10:16 UTC"
            match = re.search(r'(\d{1,2})\s+(\w{3}),?\s*(\d{4}),?\s*(\d{1,2}):(\d{2})', date_text)
            if match:
                day, month_str, year, hour, minute = match.groups()
                # 월 이름을 숫자로 변환
                month_map = {
                    'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
                    'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12
                }
                month = month_map.get(month_str, 1)
                dt = datetime(int(year), month, int(day), int(hour), int(minute), tzinfo=timezone.utc)
                return dt.isoformat()
        except Exception as e:
            logger.debug(f"Date parsing failed: {e}, using now()")
        
        return datetime.now(timezone.utc).isoformat()

    def _parse_views(self, post) -> int | None:
        """
        Views 수 추출.
        
        HTML 구조: <div class="views"> ... <span style="font-size: 12px; font-weight: bold">31332</span> ...
        """
        try:
            # 1차 시도: font-weight: bold 스타일이 있는 span
            views_candidate = post.css('div.views span[style*="font-weight: bold"]::text').get()
            
            # 2차 시도: div.views 내 두 번째 div의 span
            if not views_candidate:
                views_candidate = post.css('div.views > div:nth-child(2) span::text').get()
            
            if views_candidate:
                clean_views = views_candidate.strip().replace(",", "")
                if clean_views.isdigit():
                    return int(clean_views)
        except Exception:
            pass
        
        return None

    def _generate_dedup_id(self, title: str) -> str:
        """title + lockbit 기반 dedup_id 생성."""
        raw = f"{title.strip().lower()}|lockbit"
        return hashlib.md5(raw.encode()).hexdigest()

    def parse(self, response):
        self.logger.info(f"[LockBit] Status: {response.status}")
        
        # 전역 설정 기반 cutoff 날짜
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.days_limit)
        
        # LockBit 3.0은 a.post-block 구조 사용
        posts = response.css('a.post-block')
        
        for post in posts:
            title = post.css('div.post-title::text').get()
            if not title:
                continue
            
            title = title.strip()
            link = post.attrib.get('href')
            url = response.urljoin(link) if link else response.url
            
            # 설명/본문
            desc = post.css('div.post-block-text::text').getall()
            content = " ".join([d.strip() for d in desc if d.strip()])
            
            # Deadline (타이머 데이터)
            deadline = post.css('div.post-timer .timer::text').getall()
            deadline_str = " ".join([d.strip() for d in deadline if d.strip()])
            
            # Updated 날짜 파싱
            updated_raw = post.css('div.updated-post-date span::text').get('') or ''
            timestamp = self._parse_date(updated_raw)
            
            # Views 추출
            views_val = self._parse_views(post)
            
            # dedup_id 생성
            dedup_id = self._generate_dedup_id(title)
            
            # 날짜 기반 필터링: cutoff 이전 게시글 스킵
            try:
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                if dt < cutoff:
                    self.logger.debug(f"[LockBit] Skipping old post: {title[:30]} ({dt})")
                    continue
            except ValueError:
                pass
            
            # Pre-Request Dedup: 파이프라인에서 주입된 seen_ids로 중복 체크
            if hasattr(self, 'seen_ids') and dedup_id in self.seen_ids:
                self.logger.debug(f"[Pre-Dedup] Skipping already seen: {title}")
                self.crawler.stats.inc_value('pre_dedup/skipped')
                continue
            
            yield LeakItem(
                source="LockBit",
                title=title,
                url=url,
                author="LockBit 3.0",
                timestamp=timestamp,
                content=f"Deadline: {deadline_str}\n\n{content}" if deadline_str else content,
                category="Ransomware",
                site_type="Ransomware",
                dedup_id=dedup_id,
                views=views_val
            )
