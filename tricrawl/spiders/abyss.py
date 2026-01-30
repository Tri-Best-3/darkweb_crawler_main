"""
Abyss Ransomware Spider
Target: (See crawler_config.yaml)
Type: Bootstrap Card Layout
"""
import scrapy
import structlog
import yaml
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from tricrawl.items import LeakItem
import re
import ast

logger = structlog.get_logger(__name__)


class AbyssSpider(scrapy.Spider):
    """
    Abyss 랜섬웨어 유출 사이트 크롤러.

    데이터 컨트랙트:
    - LeakItem의 필수 필드(source/title/url/author/timestamp)를 반드시 채움
    - dedup_id는 "제목+본문" 기반으로 안정적으로 생성
    - content는 요약/링크 포함 가능 (파이프라인에서 키워드 매칭 대상)
    """
    
    name = "abyss"
    
    custom_settings = {
        'ROBOTSTXT_OBEY': False,
        'DOWNLOAD_TIMEOUT': 120,
        # Abyss는 단일 페이지 또는 단순 구조이므로 동시성 낮춤
        'CONCURRENT_REQUESTS': 1,
        # Abyss는 전체 목록을 매번 가져오므로, 실행에서 보이지 않은 캐시는 정리
        'DEDUP_PRUNE_UNSEEN': True,
        # .onion 요청은 requests 기반 다운로드로 처리 (Scrapy 기본 다운로더의 socks 미지원 회피)
        'DOWNLOADER_MIDDLEWARES': {
            'tricrawl.middlewares.darknet_requests.RequestsDownloaderMiddleware': 900,
            'tricrawl.middlewares.TorProxyMiddleware': None,
            'scrapy.downloadermiddlewares.httpproxy.HttpProxyMiddleware': None,
        }
    }
    
    def __init__(self, *args, **kwargs):
        """YAML 설정 로드 후 start_urls를 구성한다."""
        super(AbyssSpider, self).__init__(*args, **kwargs)
        
        # 설정 파일 로드 (Namespaced)
        self.config = {}
        try:
            # __file__ 기준으로 프로젝트 루트 찾기 (tricrawl/spiders/abyss.py -> ../../)
            self.project_root = Path(__file__).resolve().parent.parent.parent
            config_path = self.project_root / "config" / "crawler_config.yaml"
            
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    full_conf = yaml.safe_load(f) or {}
                    self.config = full_conf.get('spiders', {}).get('abyss', {})
                logger.info(f"Abyss Config loaded", path=str(config_path))
            else:
                logger.warning(f"Config file not found at: {config_path}")
        except Exception as e:
            logger.error(f"Config load failed: {e}")
            
        # URL 설정
        target = self.config.get('target_url')
        if target:
            self.start_urls = [target]
        else:
            self.start_urls = []
            logger.error("Abyss Config: 'target_url' is missing. start_urls is empty.")

    def parse(self, response):
        """Abyss 메인 페이지 파싱 -> data.js 요청."""
        # 정적 페이지가 비어있으므로 data.js를 찾아 요청
        logger.info(f"Abyss 메인 페이지 접근: {response.url}")
        
        # data.js URL 유추 (HTML 내 <script src="static/data.js">)
        # 상대 경로 처리
        data_js_url = response.urljoin("static/data.js")
        yield scrapy.Request(data_js_url, callback=self.parse_data_js, errback=self.errback_data_js)

    def parse_data_js(self, response):
        """
        data.js 파싱 (JSON 데이터 추출).

        - JS 배열을 Python 객체로 변환한 뒤 LeakItem으로 매핑
        - Spider 단계에서 필수 필드를 채우고, 파이프라인에서 후속 처리
        - 생성 데이터의 소비처:
          - dedup_id → `tricrawl/pipelines/dedup.py:DeduplicationPipeline.get_hash`
          - title/content → `tricrawl/pipelines/keyword_filter.py:KeywordFilterPipeline.process_item`
          - content → `tricrawl/pipelines/archive.py:ArchivePipeline._extract_contacts`
          - timestamp/category → `tricrawl/pipelines/discord_notify.py:DiscordNotifyPipeline._build_embed`
        """
        logger.info(f"data.js 로드 성공: {len(response.text)} bytes")
        
        # 디버그용 저장
        try:
            debug_path = self.project_root / "debug_data.js"
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(response.text)
        except Exception:
            pass

        try:
            # 1. Capture the array [ ... ]
            match = re.search(r'=\s*(\[.*\])', response.text, re.DOTALL)
            if match:
                js_str = match.group(1)
                
                # 2. Fix JS String Concatenation used in 'full' field
                # Pattern: 'text' + \n 'more text' -> 'textmore text'
                # Remove ' + ' and surrounding whitespace/newlines to merge strings
                # This makes it a valid Python string literal
                cleaned_str = re.sub(r"'\s*\+\s*(?:[\r\n]+)?\s*'", "", js_str)
                
                # 3. Parse using Python AST or Fallback
                data = None
                try:
                    data = ast.literal_eval(cleaned_str)
                except Exception as e_ast:
                    logger.warning(f"AST parsing failed: {e_ast}. Trying generic regex fallback...")
                    
                    # Fallback: 정규식으로 '객체' 패턴을 찾아 하나씩 파싱 시도
                    # { 'header': ..., 'text': ... } 패턴 추정
                    # 완벽하지 않으나, 일부라도 건지기 위함
                    try:
                        # Find all dict-like structures (very basic regex)
                        # This assumes keys are quoted or unquoted standard keys
                        # Note: This is a last resort. Abyss data usually valid JS array.
                        # Simple regex to extract title/header/name and description/text/full
                        # This avoids full JSON parsing issues
                        data = []
                        entries_raw = re.findall(r"\{.*?\}", cleaned_str, re.DOTALL)
                        for raw in entries_raw:
                            # Extract Title
                            t_match = re.search(r"'(?:title|name|header)'\s*:\s*'(.*?)'", raw)
                            # Extract Body
                            b_match = re.search(r"'(?:description|text|body|full)'\s*:\s*'(.*?)'", raw, re.DOTALL)
                            
                            if t_match:
                                entry = {
                                    'title': t_match.group(1),
                                    'description': b_match.group(1) if b_match else ""
                                }
                                data.append(entry)
                    except Exception as e_regex:
                        logger.error(f"Regex fallback checks failed: {e_regex}")
                        return

                if not data:
                    logger.error("Parsing returned no data")
                    return

                logger.info(f"데이터 항목 수(Parsed): {len(data)}")
                # UTC Current Time
                current_time = datetime.now(timezone.utc).isoformat()
                
                for entry in data:
                    if not isinstance(entry, dict):
                        continue
                        
                    title = entry.get('title') or entry.get('name') or entry.get('header')
                    description = entry.get('description') or entry.get('text') or entry.get('body') or entry.get('full') or ""
                    links = entry.get('links') or []
                    
                    if not title:
                        continue
                        
                    # 중복 체크는 DeduplicationPipeline에서 수행하므로 여기서는 패스
                        
                    item = LeakItem()
                    # 필수 필드: source/title/url/author/timestamp
                    item["source"] = "Abyss Ransomware"
                    item["url"] = self.start_urls[0]
                    # 제목 접두어 제거 (Discord Target 필드로 이동)
                    item["title"] = str(title).strip()
                    item["author"] = "Abyss"
                    item["timestamp"] = current_time
                    item["site_type"] = "Ransomware"
                    item["category"] = "Ransomware" # 랜섬웨어는 보통 단일 페이지라 General로 통일
                    item["views"] = None

                    # 내용 기반 ID로 업데이트 감지
                    # Title + Description Hash
                    dedup_key = f"{item['title']}|{description}"
                    item["dedup_id"] = hashlib.md5(dedup_key.encode()).hexdigest()
                    
                    content_parts = [str(description)]
                    if isinstance(links, list):
                        links_str = "\n".join(str(l) for l in links)
                        content_parts.append(f"\n[Links]\n{links_str}")
                    elif isinstance(links, str):
                        content_parts.append(f"\n[Links]\n{links}")
                    
                    # Original 'short' description if available
                    short_desc = entry.get('short')
                    if short_desc:
                         content_parts.insert(0, f"[Short] {short_desc}\n")
                        

                    item["content"] = "\n".join(content_parts)
                    
                    yield item
                    
            else:
                logger.warning("data.js에서 JSON 배열 패턴을 찾지 못했습니다.")
        
        except Exception as e:
            logger.error(f"data.js 파싱 실패: {e}")
            
    def errback_data_js(self, failure):
        """data.js 요청 실패 시 호출되는 errback."""
        logger.error(f"data.js 요청 실패: {failure.value}")

