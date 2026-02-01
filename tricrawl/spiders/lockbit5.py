"""
LockBit 5.0 스파이더

LockBit 5.0 (새 버전) 랜섬웨어 그룹 Leak Site 크롤러.
기존 lockbit.py와 별도로 운영됨.

주요 기능:
- 리스트 페이지에서 피해 기업 정보 추출
- 날짜 파싱 (예: "28 Jan, 2026, 17:12 UTC")
- Views 추출
- 상태 구분 (타이머 진행 중 / published)
- 쿠키 지원 (CAPTCHA 우회용)

참고: LockBit 5.0은 CAPTCHA가 필요할 수 있습니다.
      config/lockbit5_cookies.json 파일에서 쿠키를 로드합니다.
"""
import scrapy
import hashlib
import json
import re
from datetime import datetime, timezone, timedelta
from tricrawl.items import LeakItem
import yaml
from pathlib import Path
import structlog

logger = structlog.get_logger(__name__)


class LockBit5Spider(scrapy.Spider):
    """
    LockBit 5.0 랜섬웨어 그룹 Leak Site 스파이더.
    
    셀렉터:
    - 피해자 목록: a.post-block
    - 제목: .post-title
    - 설명: .post-block-text
    - 날짜: .updated-post-date span
    - 조회수: .views div:last-child span
    - 상태: .post-timer (진행 중) / .post-timer-end (published)
    """
    name = "lockbit 5.0"
    
    custom_settings = {
        "DOWNLOADER_MIDDLEWARES": {
            "tricrawl.middlewares.darknet_requests.RequestsDownloaderMiddleware": 543,
            "tricrawl.middlewares.TorProxyMiddleware": None,
            "scrapy.downloadermiddlewares.httpproxy.HttpProxyMiddleware": None,
        },
        "COOKIES_ENABLED": True,
        "DOWNLOAD_DELAY": 3,
    }

    def __init__(self, *args, **kwargs):
        """YAML 설정을 로드하고 start_urls를 구성한다."""
        super().__init__(*args, **kwargs)

        self.config = {}
        self.cookies = {}
        
        try:
            project_root = Path(__file__).resolve().parents[2]
            config_path = project_root / "config" / "crawler_config.yaml"
            
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    full_conf = yaml.safe_load(f) or {}
                    self.config = full_conf.get('spiders', {}).get('lockbit5', {})
                logger.info(f"Config loaded from {config_path}")
            else:
                logger.warning("Config file not found, using defaults")
                
        except Exception as e:
            logger.error(f"Config load failed: {e}")

        self.target_url = self.config.get('target_url')
        if self.target_url:
            self.start_urls = [self.target_url]
        else:
            logger.error("Target URL NOT found in config for lockbit5.")
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
        
        # 쿠키 파일 로드 (있으면)
        self._load_cookies()

    def _load_cookies(self):
        """config/lockbit5_cookies.json에서 쿠키를 로드한다."""
        try:
            project_root = Path(__file__).resolve().parents[2]
            cookie_path = project_root / "config" / "lockbit5_cookies.json"
            
            if cookie_path.exists():
                with open(cookie_path, "r", encoding="utf-8") as f:
                    self.cookies = json.load(f)
                
                # 쿠키 유효성 검사
                dcap = self.cookies.get("dcap", "")
                if not dcap or dcap == "PASTE_HERE":
                    print("\n" + "="*60)
                    print("🛑 [오류] LockBit 5.0 쿠키가 설정되지 않았습니다!")
                    print(f"⚠️  설정 파일: {cookie_path}")
                    print("🌐 주소: http://lockbitapt67g6rwzjbcxnww5efpg4qok6vpfeth7wx3okj52ks4wtad.onion/")
                    print("👉 파일을 열고 Tor 브라우저의 'dcap' 쿠키 값을 입력해주세요.")
                    print("="*60 + "\n")
                    logger.error("Invalid cookie value (PASTE_HERE or empty). Stopping spider.")
                    # 스파이더 강제 종료 (CloseSpider 예외 발생 시키는 것이 좋으나, 여기서 바로 리턴하면 start_requests에서 빈 리스트가 됨)
                    self.cookies = {} 
                else:
                    logger.info(f"Loaded {len(self.cookies)} cookies from {cookie_path}")
            else:
                logger.warning(f"Cookie file not found at {cookie_path}")
                # 템플릿 자동 생성
                template = {
                    "_instructions": "Tor 브라우저에서 'dcap' 등의 쿠키를 복사해 여기에 입력하세요.",
                    "dcap": "PASTE_HERE"
                }
                with open(cookie_path, "w", encoding="utf-8") as f:
                    json.dump(template, f, indent=2, ensure_ascii=False)
                logger.warning(f"⚠️ Created template file at {cookie_path}. Please update it with valid cookies!")
        except Exception as e:
            logger.error(f"Cookie load failed: {e}")


    def start_requests(self):
        """사용자 브라우저 헤더를 완벽하게 모방하여 요청."""
        
        # 기본 헤더 설정 (사용자가 제공한 값 기반)
        headers = {
            "Host": "lockbitapt67g6rwzjbcxnww5efpg4qok6vpfeth7wx3okj52ks4wtad.onion",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            #"Accept-Encoding": "gzip, deflate, br, zstd",  # requests가 자동 처리하므로 생략 권장
            #"Referer": "http://lockbitapt67g6rwzjbcxnww5efpg4qok6vpfeth7wx3okj52ks4wtad.onion/", # 첫 요청엔 생략하거나 자기 자신
            "Sec-GPC": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Priority": "u=0, i"
        }

        # 쿠키 추가
        if not self.cookies:
            logger.error("No valid cookies found. Stopping spider.")
            return

        cookie_header = "; ".join([f"{k}={v}" for k, v in self.cookies.items()])
        if cookie_header:
            headers["Cookie"] = cookie_header
            logger.info(f"Cookie header set: {cookie_header[:50]}...")
        
        for url in self.start_urls:
            yield scrapy.Request(
                url=url,
                headers=headers,
                callback=self.parse,
                dont_filter=True,
            )

    def _parse_date(self, date_text: str) -> str:
        """
        날짜 문자열을 ISO 8601 형식으로 변환.
        
        예시 입력: "28 Jan, 2026, 17:12 UTC"
        출력: "2026-01-28T17:12:00+00:00"
        """
        if not date_text:
            return datetime.now(timezone.utc).isoformat()
            
        try:
            # "28 Jan, 2026, 17:12 UTC" 형식 파싱
            cleaned = date_text.strip().replace(" UTC", "").replace(",", "")
            # "28 Jan 2026 17:12"
            dt = datetime.strptime(cleaned, "%d %b %Y %H:%M")
            return dt.replace(tzinfo=timezone.utc).isoformat()
        except Exception as e:
            logger.debug(f"Date parse failed: {date_text} - {e}")
            return datetime.now(timezone.utc).isoformat()

    def _parse_views(self, views_text: str) -> int:
        """Views 문자열을 정수로 변환."""
        if not views_text:
            return None
        try:
            # "756" -> 756, "1,234" -> 1234
            cleaned = views_text.strip().replace(",", "")
            return int(cleaned)
        except ValueError:
            return None

    def parse(self, response):
        """
        메인 파서: a.post-block 요소를 순회하며 피해자 정보 추출.
        """
        logger.info(f"LockBit5 Page Accessed: {response.url}")
        
        # CAPTCHA 감지
        if "captcha" in response.text.lower() or "challenge" in response.text.lower():
            logger.warning("CAPTCHA detected! Please update cookies.")
            return
        
        posts = response.css('a.post-block')
        logger.info(f"Found {len(posts)} victims.")
        
        # items/discovered 통계 기록
        self.crawler.stats.inc_value('items/discovered', len(posts))
        
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.days_limit)
        new_items_count = 0
        
        for post in posts:
            # 1. 제목 (피해자 도메인)
            title = post.css('.post-title::text').get()
            if not title:
                continue
            title = title.strip()
            
            # 2. 설명
            description = post.css('.post-block-text::text').get()
            description = description.strip() if description else ""
            
            # 3. 날짜
            date_text = post.css('.updated-post-date span::text').get()
            if date_text:
                # 아이콘 이미지 다음 텍스트 추출
                date_parts = post.css('.updated-post-date span::text').getall()
                date_text = " ".join([d.strip() for d in date_parts if d.strip()])
            timestamp = self._parse_date(date_text)
            
            # 날짜 필터링
            try:
                dt = datetime.fromisoformat(timestamp)
                if dt < cutoff:
                    logger.debug(f"Skipping old post: {title[:30]} ({dt.date()})")
                    continue
            except Exception:
                pass
            
            # 4. 조회수
            views_text = post.css('.views div:last-child span::text').get()
            views = self._parse_views(views_text)
            
            # 5. 상태 (타이머 or published)
            timer = post.css('.post-timer::text').get()
            timer_end = post.css('.post-timer-end::text').get()
            status = timer.strip() if timer else (timer_end.strip() if timer_end else "unknown")
            
            # 6. 상세 링크
            detail_url = post.attrib.get('href', '')
            if detail_url and not detail_url.startswith('http'):
                detail_url = response.urljoin(detail_url)
            
            # dedup_id 생성 (title + lockbit5 기반)
            dedup_key = f"{title}|lockbit5"
            dedup_id = hashlib.md5(dedup_key.encode()).hexdigest()
            
            # [Pre-Request Dedup] 이미 DB에 있으면 스킵
            if hasattr(self, 'seen_ids') and dedup_id in self.seen_ids:
                logger.debug(f"Pre-skip: {title[:30]} (already in DB)")
                self.crawler.stats.inc_value('pre_dedup/skipped')
                continue
            
            new_items_count += 1
            
            # 콘텐츠에 상태 정보 포함
            content = f"{description}\n\n[Status: {status}]"
            
            yield LeakItem(
                source="LockBit5",
                title=title,
                url=detail_url or response.url,
                author="LockBit Group",
                timestamp=timestamp,
                content=content,
                category="Ransomware",
                site_type="Ransomware",
                dedup_id=dedup_id,
                views=views,
            )
        
        logger.info(f"[LockBit5] Page complete: {new_items_count} new items")
