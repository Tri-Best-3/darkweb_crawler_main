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
    Abyss Ransomware Spider
    """
    
    name = "abyss"
    
    custom_settings = {
        'ROBOTSTXT_OBEY': False,
        'DOWNLOAD_TIMEOUT': 120,
        # Abyss는 단일 페이지 또는 단순 구조이므로 동시성 낮춤
        'CONCURRENT_REQUESTS': 1,
        'DEDUP_PRUNE_UNSEEN': True,
        'DOWNLOADER_MIDDLEWARES': {
            'tricrawl.middlewares.darknet_requests.RequestsDownloaderMiddleware': 543,
            'tricrawl.middlewares.TorProxyMiddleware': None,
            'scrapy.downloadermiddlewares.httpproxy.HttpProxyMiddleware': None,
        }
    }
    
    def __init__(self, *args, **kwargs):
        """YAML 설정 로드 후 start_urls를 구성한다."""
        super().__init__(*args, **kwargs)
        
        # Config load
        self.config = {}
        try:
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
            
        # Target URL
        target = self.config.get('target_url')
        if target:
            self.start_urls = [target]
        else:
            self.start_urls = []
            logger.error("Abyss Config: 'target_url' is missing. start_urls is empty.")

    def parse(self, response):
        """Abyss 메인 페이지 파싱 -> data.js 요청."""
        logger.info(f"Abyss Main Page: {response.url}")
        
        data_js_url = response.urljoin("static/data.js")
        yield scrapy.Request(data_js_url, callback=self.parse_data_js, errback=self.errback_data_js)

    def parse_data_js(self, response):
        """
        Parse data.js to extract JSON data.
        """
        logger.info(f"data.js loaded: {len(response.text)} bytes")
        


        try:
            # 1. Capture the array [ ... ]
            match = re.search(r'=\s*(\[.*\])', response.text, re.DOTALL)
            if match:
                js_str = match.group(1)
                
                # 2. Fix JS String Concatenation
                cleaned_str = re.sub(r"'\s*\+\s*(?:[\r\n]+)?\s*'", "", js_str)
                
                # 3. Parse using Python AST or Fallback
                data = None
                try:
                    data = ast.literal_eval(cleaned_str)
                except Exception as e_ast:
                    logger.warning(f"AST parsing failed: {e_ast}. Trying generic regex fallback...")
                    
                    # Fallback: Regex parsing for simple objects
                    try:
                        # Find all dict-like structures (very basic regex)
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
                    item["category"] = "Ransomware"
                    item["views"] = None

                    # 내용 기반 ID로 업데이트 감지
                    # Title + Description Hash
                    dedup_key = f"{item['title']}|{description}"
                    item["dedup_id"] = hashlib.md5(dedup_key.encode()).hexdigest()
                    
                    # [Pre-Request Dedup] 이미 DB에 있으면 스킵
                    if hasattr(self, 'seen_ids') and item["dedup_id"] in self.seen_ids:
                        logger.debug(f"[Abyss] Pre-skip: {title[:30]} (already in DB)")
                        self.crawler.stats.inc_value('pre_dedup/skipped')
                        continue
                    
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
                logger.warning("JSON array not found in data.js")
        
        except Exception as e:
            logger.error(f"data.js 파싱 실패: {e}")
            
    def errback_data_js(self, failure):
        """data.js 요청 실패 시 호출되는 errback."""
        logger.error(f"data.js 요청 실패: {failure.value}")

