"""
DarkNetArmy Forum Spider
Target: http://dna777qhcrxy5sbvk7rkdd2phhxbftpdtxvwibih26nr275cdazx4uyd.onion/
Type: XenForo Forum
"""
import scrapy
import structlog
import yaml
from pathlib import Path
from tricrawl.items import LeakItem
from datetime import datetime, timedelta, timezone

logger = structlog.get_logger(__name__)


class DarkNetArmySpider(scrapy.Spider):
    """
    DarkNetArmy 포럼 크롤러 (XenForo).

    데이터 컨트랙트:
    - LeakItem의 필수 필드(source/title/url/author/timestamp)를 반드시 채움
    - content는 요약/클린 텍스트로 구성 (키워드 필터 입력)
    - category는 가능하면 게시판/분류명으로 채움
    """
    
    name = "darknet_army"
    
    # 동적 URL 생성 (Config 로드 후 __init__에서 설정)
    start_urls = []
    
    custom_settings = {
        'ROBOTSTXT_OBEY': False,
        'DOWNLOAD_TIMEOUT': 120,
        'USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/115.0',
        'COOKIES_ENABLED': True,
        # DarkNet 전용 미들웨어 사용
        'DOWNLOADER_MIDDLEWARES': {
            'tricrawl.middlewares.darknet_requests.RequestsDownloaderMiddleware': 543,
            'tricrawl.middlewares.TorProxyMiddleware': None,
            'scrapy.downloadermiddlewares.httpproxy.HttpProxyMiddleware': None,
        }
    }
    
    def __init__(self, *args, **kwargs):
        """YAML 설정을 로드하고 start_urls/board limits를 구성한다."""
        super(DarkNetArmySpider, self).__init__(*args, **kwargs)
        
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
        self.days_limit = global_conf.get('days_to_crawl', 3)
        override_days = kwargs.get("days_limit")
        if override_days is not None:
            try:
                self.days_limit = int(override_days)
            except ValueError:
                logger.warning("Invalid days_limit override", value=override_days)
        
        # 스파이더별 설정 로드 및 start_urls 구성
        spider_conf = self.config.get('spiders', {}).get('darknet_army', {})
        self.target_url = spider_conf.get('target_url')
        self.endpoints = spider_conf.get('endpoints', {})
        self.board_limits = spider_conf.get('boards', {})
        
        if self.target_url and self.endpoints:
            # Base URL의 trailing slash 처리
            base = self.target_url.rstrip('/')
            for key, path in self.endpoints.items():
                # Endpoints path의 leading slash 처리
                clean_path = path.lstrip('/')
                full_url = f"{base}/{clean_path}"
                self.start_urls.append(full_url)
                logger.debug(f"Added start URL: {full_url} (Key: {key})")
        else:
            logger.error("Target URL or Endpoints NOT found in config. Spider may not crawl anything.")

        # 기본값 로직 조정: Config에 없으면 내부 기본값(5) 사용
        self.default_max_pages = 5
        
        logger.info(f"Loaded Config - Global Days: {self.days_limit}, URLs: {len(self.start_urls)}")

    def get_max_pages_for_url(self, url):
        """URL에 해당하는 게시판별 제한 확인 (config의 boards 기준)."""
        # Config의 Endpoints 경로를 역추적하여 Key를 찾고, 그 Key로 Limits를 조회
        # 현재는 URL에 endpoint path가 포함되어 있는지 단순 문자열 매칭으로 확인
        for key, path in self.endpoints.items():
            # URL 디코딩 문제가 있을 수 있으므로 단순 포함 여부 확인이 안전
            # Config의 path 부분만 잘라서 비교
            if path.lstrip('/') in url:
                return self.board_limits.get(key, self.default_max_pages)
        
        return self.default_max_pages

    def parse(self, response):
        """
        포럼 목록(Latest posts 등) 파싱 - XenForo List View.

        - 리스트에서 제목/작성자/시간/링크만 추출
        - 날짜 컷오프 로직으로 불필요한 페이지네이션을 줄임
        """
        # 현재 페이지 카운트 (기본 1)
        page_count = response.meta.get('page_count', 1)
        
        # 현재 게시판의 Max Pages 결정
        current_max_pages = self.get_max_pages_for_url(response.url)
        
        logger.info(f"DarkNetArmy 접속 (Page {page_count}/{current_max_pages})", url=response.url)
        
        # ... (중략) ... --> 기존 코드 유지, cutoff_date 부분만 수정
        
        # XenForo 게시물 리스트 아이템 (li.structItem or div.structItem)
        threads = response.css(".structItem")
        
        if not threads:
            logger.warning("게시물 목록 발견 실패 (structItem), 구조 변경 또는 권한 문제 가능성")
            return

        logger.info(f"게시물 목록 {len(threads)}개 감지 (필터링 전)")
        
        found_recent_on_this_page = False
        found_old_normal_post = False  # 일반 게시글 중 오래된 글 발견 여부
        
        # 공지사항(Sticky)만 있는 페이지일 경우, 일반 게시글이 없으므로 다음 페이지를 봐야 함
        # 따라서 "일반 게시글(Non-Sticky) 중 최신글이 있는지"를 체크하거나,
        # "일반 게시글이 하나도 없으면" 다음 페이지로 가야 함.
        # 전략: "오래된 글"을 만났을 때, 그것이 Sticky라면 무시하고 계속 진행. 
        # Non-Sticky인데 오래된 글이면 -> 그 시점에서 중단 고려.
        
        for thread in threads:
            # Sticky 여부 확인
            is_sticky = "structItem--status--sticky" in (thread.attrib.get("class") or "")
            
            # 1. 제목 및 상세 링크 (Selector 보강)
            # 일반적인 XenForo: .structItem-title a
            # 일부 테마: .structItem-cell--title a
            title_el = thread.css(".structItem-title a") or thread.css(".structItem-cell--title a")
            
            # 여기서도 없으면 data-preview-url 속성을 가진 a 태그 찾기
            if not title_el:
                title_el = thread.css("a[data-preview-url]")

            link = title_el.css("::attr(href)").get()
            title = (title_el.css("::text").get() or "").strip()
            
            # 2. 메타데이터 (작성자, 날짜)
            author = thread.css(".structItem-parts .username::text").get() or \
                     thread.css(".structItem-cell--avatar img::attr(alt)").get() or "Unknown"
            
            # 날짜: 가능한 timestamp 중 최신값을 사용 (최근 업데이트 기준)
            # data-time (Unix timestamp)이 가장 신뢰할 수 있음
            timestamp_candidates = []
            for raw_ts in thread.css("time::attr(data-time)").getall():
                try:
                    ts = int(raw_ts)
                except (TypeError, ValueError):
                    continue
                # ms 단위 timestamp 방어
                if ts > 10**12:
                    ts = ts // 1000
                timestamp_candidates.append(ts)

            timestamp_unix = max(timestamp_candidates) if timestamp_candidates else None

            # Fallback: datetime 속성 (ISO) 중 최신값 선택
            date_str_candidates = []
            if not timestamp_unix:
                date_str_candidates = thread.css("time::attr(datetime)").getall()

            date_time = None
            is_recent = False
            
            # 날짜 파싱 로직 (Flag: Force UTC)
            try:
                dt = None
                if timestamp_unix:
                    dt = datetime.fromtimestamp(int(timestamp_unix), tz=timezone.utc)
                elif date_str_candidates:
                    parsed = []
                    for date_str in date_str_candidates:
                        try:
                            d = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                            if d.tzinfo is None:
                                d = d.replace(tzinfo=timezone.utc)
                            parsed.append(d)
                        except Exception:
                            continue
                    if parsed:
                        dt = max(parsed)
                
                if dt:
                    date_time = dt.isoformat()
                    # 설정된 날짜 제한 적용 (UTC 기준 비교)
                    cutoff_date = datetime.now(timezone.utc) - timedelta(days=self.days_limit)
                    
                    if dt >= cutoff_date:
                        is_recent = True
                        # Sticky여도 최신이면 OK, Non-Sticky면 당연히 OK
                        found_recent_on_this_page = True
                    else:
                        # 오래된 글임.
                        if is_sticky:
                            # Sticky는 오래되어도 상단에 있을 수 있으므로, 
                            # 이것만 보고 "더 이상 최신글 없다"고 판단하면 안 됨.
                            logger.debug(f"Skipping old sticky post: {title[:15]}...")
                        else:
                            # 일반 글인데 오래되었다? -> 이후 글들도 다 오래되었을 확률 높음
                            found_old_normal_post = True  # 일반 글 중 오래된 것 발견 표시
                            logger.debug(f"Skipping old post: {title[:15]}...")
                            pass
                else:
                    # 날짜 파싱 실패 -> 안전하게 수집
                    is_recent = True
                    found_recent_on_this_page = True
                    
            except Exception as e:
                is_recent = True
                found_recent_on_this_page = True
            
            # 메타 데이터 패키징
            meta_data = {
                'title': title,
                'author': author,
                'timestamp': date_time
            }

            if link and is_recent:
                # 상세 페이지 크롤링 요청
                yield response.follow(link, callback=self.parse_post, meta=meta_data)

        # 페이지네이션 (Smart Stop + Config Limit)
        
        # 1. 날짜 기준 중단
        # "최신 글"을 하나도 못 찾았고, "오래된 일반 글"을 찾았다면 중단.
        # (Sticky만 잔뜩 있어서 최신글을 못 찾은거라면 다음 페이지를 확인해야 함)
        if not found_recent_on_this_page and found_old_normal_post:
            logger.info("모든 게시물이 날짜 기준 미달(Sticky 제외). 페이지네이션 중단.")
            return

        # 2. 페이지 수 기준 중단 (0이면 무제한)
        if current_max_pages > 0 and page_count >= current_max_pages:
            logger.info(f"게시판별 최대 페이지({current_max_pages}) 도달. 페이지네이션 중단.")
            return

        next_page = response.css("a.pageNav-jump--next::attr(href)").get()
        if next_page:
            logger.info(f"다음 페이지로 이동 (Next Page: {page_count + 1})")
            yield response.follow(next_page, callback=self.parse, meta={'page_count': page_count + 1})

    def parse_post(self, response):
        """
        게시물 상세 내용 파싱 - XenForo Thread View.

        - LeakItem의 필수 필드를 채우고 content를 정제한다.
        - Hidden Content 여부를 표기해 팀원이 쉽게 확인하도록 한다.
        - 생성 데이터의 소비처:
          - title/content → `tricrawl/pipelines/keyword_filter.py:KeywordFilterPipeline.process_item`
          - content → `tricrawl/pipelines/archive.py:ArchivePipeline._extract_contacts`
          - author/title → `tricrawl/pipelines/dedup.py:DeduplicationPipeline.get_hash`
          - timestamp/category → `tricrawl/pipelines/discord_notify.py:DiscordNotifyPipeline._build_embed`
        """
        item = LeakItem()
        # 필수 필드: source/title/url/author/timestamp
        item["source"] = "DarkNetArmy"
        item["url"] = response.url
        
        # 1. 메타데이터 복원 (List View에서 가져온 정보 우선)
        meta_title = response.meta.get('title')
        meta_author = response.meta.get('author')
        meta_time = response.meta.get('timestamp')
        
        # 상세 페이지에서 제목 재확인 (더 정확할 수 있음)
        item["title"] = (
            response.css("h1.p-title-value::text").get() or 
            meta_title or
            response.css("title::text").get()
        ).strip()
        
        # 2. 본문 추출 (첫 번째 게시물 = 작성글)
        # XenForo: article.message--post
        # 2. 본문 추출 (첫 번째 게시물 = 작성글)
        # XenForo: article.message--post
        posts = response.css("article.message--post") or response.css("article.message")
        
        if posts:
            first_post = posts[0]
            # 본문 영역: .message-content -> .bbWrapper
            content_div = first_post.css(".message-content .bbWrapper")
            
            # Hidden Content 감지 (Reaction Wall)
            hidden_block = content_div.css(".bbCodeBlock--hide")
            is_hidden = bool(hidden_block)
            
            # 텍스트 추출 (줄바꿈 보존을 위해 getall 후 처리)
            # bbCodeBlock--hide 내부 텍스트("To see this hidden content...")는 제외하고 싶지만,
            # 구조상 섞여 있을 수 있음. 일단 전체 가져오고 Hidden 여부 표시
            
            content_parts = []
            for node in content_div.css("*::text").getall():
                text = node.strip()
                if text:
                    content_parts.append(text)
            
            dirty_content = "\n".join(content_parts)
            
            # Telegram/Contact 추출 (Hidden 밖의 정보가 중요)
            # a tag의 href나 텍스트에서 텔레그램 링크 찾기
            contacts = []
            links = content_div.css("a::attr(href)").getall()
            for link in links:
                if "t.me" in link or "telegram" in link:
                    contacts.append(link)
            
            # Hidden일 경우 경고 문구 추가
            if is_hidden:
                dirty_content = f"🔒 [Hidden Content] (Requires Reaction)\n\n" + dirty_content
                if contacts:
                    dirty_content += f"\n\n📞 Found Contacts:\n" + "\n".join(contacts)

            item["content"] = dirty_content[:5000] # 길이 제한
            
            # 작성자 (fallback)
            if not meta_author or meta_author == "Unknown":
                item["author"] = first_post.css(".message-name .username::text").get() or \
                                 first_post.css(".message-userDetails .username::text").get() or \
                                 "Unknown"
            else:
                item["author"] = meta_author
                
            # 시간 (목록 페이지에서 가져온 값 우선 사용 - 필터링 기준)
            # 상세 페이지의 시간은 다를 수 있음 (게시물 수정 시간 등)
            item["timestamp"] = meta_time

            # 카테고리 추출 (Breadcrumbs)
            # .p-breadcrumbs -> li -> a -> span
            # 보통 마지막에서 2번째가 게시판 이름 (마지막은 현재 글 제목일 수 있음)
            # 여기서는 안전하게 breadcrumbs 텍스트 전체를 가져오거나 특정 위치를 파싱
            breadcrumbs = response.css(".p-breadcrumbs li a span::text").getall()
            if breadcrumbs:
                # "Home > Forums > Cat > Board" 형태
                # 보통 맨 뒤가 게시판 이름
                item["category"] = breadcrumbs[-1]
            else:
                 item["category"] = "Unknown"
                
        else:
            # 구조가 다를 경우 전체 텍스트 fallback
            item["content"] = " ".join(response.css("body *::text").getall()).strip()[:1000]
            item["author"] = meta_author or "Unknown"
            item["timestamp"] = meta_time
            item["category"] = "Unknown"
        
        # 데이터 클리닝
        if item["author"]:
            item["author"] = item["author"].strip()
            
        yield item




