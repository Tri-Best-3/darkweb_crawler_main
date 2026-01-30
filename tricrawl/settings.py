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
LOG_LEVEL = "WARNING"  # INFO 로그 숨김(깔끔한 출력)
# structlog는 INFO로 출력되도록 하려면 Scrapy Logger와 분리 필요하지만, 
# 기본적으로 Scrapy는 root logger를 잡으므로 WARNING으로 높여서 잡음 제거.
# 스파이더에서 print()나 logger.warning()을 사용하면 됨.
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
LOG_DATEFORMAT = "%H:%M:%S"

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
