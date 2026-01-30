"""
Scrapy 설정 파일

핵심 요약:
- Tor 프록시 및 .onion 대응 미들웨어 설정
- 파이프라인 순서 및 키워드 필터/알림 동작 기준
- .env 값이 우선 (운영 환경에서 값 변경 권장)
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# 프로젝트 루트 경로
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# .env 로드 (환경변수가 설정 파일보다 우선 적용됨)
load_dotenv(PROJECT_ROOT / ".env")

BOT_NAME = "tricrawl"
SPIDER_MODULES = ["tricrawl.spiders"]
NEWSPIDER_MODULE = "tricrawl.spiders"

# 크롤링 정책 (속도/동시성은 Tor 안정성을 고려해 보수적으로 설정)
ROBOTSTXT_OBEY = False  # 다크웹은 robots.txt 무시함
CONCURRENT_REQUESTS = int(os.getenv("CONCURRENT_REQUESTS", 2))
DOWNLOAD_DELAY = int(os.getenv("CRAWL_DELAY", 5))
RANDOMIZE_DOWNLOAD_DELAY = True

# 요청 제한(CONCURRENT_REQUESTS_PER_IP 썼다가 Scrapy 최신 버전 비호환으로 삭제)
CONCURRENT_REQUESTS_PER_DOMAIN = 1

# Tor 프록시 (socks5h를 사용하면 DNS 해석도 Tor에서 처리)
TOR_PROXY_HOST = os.getenv("TOR_PROXY_HOST", "127.0.0.1")
TOR_PROXY_PORT = os.getenv("TOR_PROXY_PORT", "9050")
TOR_PROXY_SCHEME = os.getenv("TOR_PROXY_SCHEME", "socks5h")
TOR_PROXY = f"{TOR_PROXY_SCHEME}://{TOR_PROXY_HOST}:{TOR_PROXY_PORT}"

# 미들웨어
# - .onion 요청은 RequestsDownloaderMiddleware로 처리
# - TorProxyMiddleware는 .onion에 프록시 적용
DOWNLOADER_MIDDLEWARES = {
    # .onion 요청은 requests 기반 다운로드로 처리
    "tricrawl.middlewares.darknet_requests.RequestsDownloaderMiddleware": 900,
    "tricrawl.middlewares.TorProxyMiddleware": 740, 
    "scrapy.downloadermiddlewares.httpproxy.HttpProxyMiddleware": 750, 
}

# 파이프라인 (숫자가 낮을수록 먼저 실행)
ITEM_PIPELINES = {
    # "tricrawl.pipelines.ArchivePipeline": 10,            # 전체 데이터 아카이브(로컬 파일 생성 X, supabase에 백업됨 필요 시 주석 해제)
    "tricrawl.pipelines.DeduplicationPipeline": 50,      # 중복 필터링
    "tricrawl.pipelines.KeywordFilterPipeline": 100,     # 키워드 필터링
    "tricrawl.pipelines.supabase.SupabasePipeline": 200, # Supabase 저장
    "tricrawl.pipelines.DiscordNotifyPipeline": 300,     # 디스코드 알림
}

# 디스코드 설정 (.env에 DISCORD_WEBHOOK_URL 필요)
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

# 키워드 설정 (targets/conditional/critical 등)
# 사용처:
# - `tricrawl/pipelines/keyword_filter.py:KeywordFilterPipeline`
# - `tricrawl/pipelines/archive.py:ArchivePipeline` (contacts 패턴)
KEYWORDS_CONFIG = PROJECT_ROOT / "config" / "keywords.yaml"

# 로깅
LOG_LEVEL = "DEBUG"  # 파일에는 모든 로그(DEBUG) 기록
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
LOG_DATEFORMAT = "%H:%M:%S"

# 커스텀 LogFormatter (DropItem 시 item 전체 출력 억제)
LOG_FORMATTER = "tricrawl.log_formatter.QuietLogFormatter"

# Structlog 설정 (Scrapy 로거와 연동)
# Structlog 설정 (Scrapy 로거와 연동)
import structlog
import logging
import sys

# Scrapy의 기본 로깅 비활성화 (우리가 직접 핸들러 제어)
# Scrapy의 기본 로깅 비활성화 (우리가 직접 핸들러 제어)
LOG_ENABLED = True  # Scrapy가 로그를 생성하도록 함
LOG_FILE = os.getenv("TRICRAWL_LOG_FILE")  # Scrapy가 이 파일에 DEBUG 로그를 쓰고, Console output은 중단함

# 로깅 설정 초기화
def setup_custom_logging():
    # Scrapy가 LOG_FILE 설정을 보고 FileLogObserver를 이미 부착했으므로,
    # 우리는 Console에 보여줄 "요약 정보(WARNING/INFO)"용 StreamHandler만 추가하면 됨.
    
    root_logger = logging.getLogger()
    # Scrapy가 Root Logger Level을 LOG_LEVEL(DEBUG)로 설정함.
    
    # 1. Console Handler (WARNING - Progress Bar 보호)
    has_stream = any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in root_logger.handlers)
    
    if not has_stream:
        # 진행률 표시줄(Rich)은 stdout을 쓰므로, 여기서는 stderr나 stdout을 쓰되 
        # ERROR 이상만 출력하여 진행률 표시줄을 망치지 않게 함.
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.ERROR)  # WARNING도 숨김
        console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
        root_logger.addHandler(console_handler)
    else:
        # 기존 핸들러가 있다면 레벨만 강제 조정
        for h in root_logger.handlers:
            if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
                h.setLevel(logging.ERROR)  # WARNING도 숨김

    # 2. File Handler -> Scrapy가 LOG_FILE 설정에 따라 자동으로 처리함 (DEBUG)
    # 따라서 별도로 추가할 필요 없음 (중복 방지)

setup_custom_logging()


# 확장 기능 활성화
EXTENSIONS = {
    "tricrawl.rich_progress.RichProgress": 500,
}

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False),
        # Scrapy 호환성을 위해 stdlib logger로 전달
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

# 재시도
RETRY_ENABLED = True
RETRY_TIMES = 3
RETRY_HTTP_CODES = [500, 502, 503, 504, 408, 429]

# 타임아웃
DOWNLOAD_TIMEOUT = 60
VERIFY_SSL = os.getenv("VERIFY_SSL", "true").lower() in ("1", "true", "yes")

# Dedup 캐시 상한 (0 이하로 설정하면 비활성)
# JSON 캐시가 무한히 커지는 것을 방지(0 이하로 설정하면 비활성)
DEDUP_MAX_ENTRIES = int(os.getenv("DEDUP_MAX_ENTRIES", 20000))
DEDUP_MAX_DAYS = int(os.getenv("DEDUP_MAX_DAYS", 30))
DEDUP_PRUNE_UNSEEN = os.getenv("DEDUP_PRUNE_UNSEEN", "false").lower() in ("1", "true", "yes")

# User-Agent (필요 시 환경변수로 교체 가능)
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/115.0"
