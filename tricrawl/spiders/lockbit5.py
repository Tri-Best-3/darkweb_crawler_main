"""
LockBit 5.0 Spider
Target: LockBit 5.0 Leak Site (New Version)
Features: Cookie support (CAPTCHA bypass), Date parsing, Status tracking
"""
import scrapy
import hashlib
import json
import re
from datetime import datetime, timezone, timedelta
from scrapy.exceptions import CloseSpider
from tricrawl.items import LeakItem
import yaml
from pathlib import Path
import structlog

logger = structlog.get_logger(__name__)


class LockBit5Spider(scrapy.Spider):
    """
    LockBit 5.0 Ransomware Spider
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
        "DOWNLOAD_TIMEOUT": 30,  # 쿠키 만료 시 빠른 실패 (기본 180초 → 30초)
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setup_alerts = []  # UI에 표시할 경고 리스트

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
        
        # Global configs
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
        
        # Load cookies if available
        self._load_cookies()

    def _load_cookies(self):
        """Load cookies from config/lockbit5_cookies.json"""
        try:
            project_root = Path(__file__).resolve().parents[2]
            cookie_path = project_root / "config" / "lockbit5_cookies.json"
            
            if cookie_path.exists():
                with open(cookie_path, "r", encoding="utf-8") as f:
                    self.cookies = json.load(f)
                
                # 쿠키 유효성 검사
                dcap = self.cookies.get("dcap", "")
                if not dcap or dcap == "PASTE_HERE":
                    msg = f"[bold red]✗ LockBit 5.0 쿠키 미설정[/bold red] ({cookie_path.name})"
                    self.setup_alerts.append(msg)
                    logger.error(
                        "LockBit 5.0 Cookie Missing",
                        config_path=str(cookie_path),
                        instruction="Please update 'dcap' cookie in the JSON file."
                    )
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
        """Emulate browser headers and existing cookies"""
        
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
        """Parse date string to ISO 8601"""
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
        """Main parser for victim list"""
        logger.info(f"LockBit5 Page Accessed: {response.url}")
        
        # CAPTCHA/인증 실패 감지 → 즉시 종료
        body_lower = response.text.lower()
        if "captcha" in body_lower or "challenge" in body_lower or len(response.text) < 500:
            logger.error("🛑 Cookie expired or CAPTCHA detected! Please update cookies.")
            print("\n" + "="*60)
            print("🛑 [오류] LockBit 5.0 쿠키가 만료되었습니다!")
            print("👉 Tor 브라우저에서 새 쿠키를 복사해주세요.")
            print("="*60 + "\n")
            raise CloseSpider("cookie_expired")
        
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
