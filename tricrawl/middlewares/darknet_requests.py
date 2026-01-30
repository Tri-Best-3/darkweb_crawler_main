"""
Scrapy의 Twisted Reactor 대신 requests 라이브러리를 사용하여 다운로드
포럼 구조에서 SOCKS5 프록시 연결에 문제가 있어서 대체 구현
"""
import asyncio
import requests
import structlog
from scrapy.http import HtmlResponse
# from scrapy.downloadermiddlewares.retry import RetryMiddleware
from scrapy.utils.python import to_bytes

logger = structlog.get_logger(__name__)

class RequestsDownloaderMiddleware:
    """
    .onion 요청을 requests + socks5h로 처리하는 대체 다운로드 미들웨어.

    목적:
    - Scrapy 기본 다운로더의 socks 미지원/불안정 문제 회피
    - .onion만 가로채고 나머지는 Scrapy 기본 흐름 유지
    """
    def __init__(self, tor_proxy, settings):
        self.tor_proxy = tor_proxy
        self.settings = settings
        # requests용 프록시 딕셔너리 (socks5h는 DNS 해석도 Tor에서 수행)
        self.proxies = {
            'http': f"socks5h://{tor_proxy}",
            'https': f"socks5h://{tor_proxy}"
        } if tor_proxy else None

    @classmethod
    def from_crawler(cls, crawler):
        """TOR_PROXY_HOST/PORT를 합쳐 requests 프록시 문자열을 구성."""
        # TOR_PROXYHOST, TOR_PROXYPORT 가져오기
        host = crawler.settings.get("TOR_PROXY_HOST", "127.0.0.1")
        port = crawler.settings.get("TOR_PROXY_PORT", "9050")
        tor_proxy = f"{host}:{port}"
        return cls(tor_proxy, crawler.settings)

    async def process_request(self, request, spider=None):
        """요청을 가로채 .onion이면 async thread로 다운로드."""
        # .onion 주소에 대해서만 custom downloader 사용
        if ".onion" not in request.url:
             return None # Scrapy 기본 처리

        logger.info("Requests 다운로더 사용(Async)", url=request.url)

        # asyncio thread로 실행해 Deferred 반환 문제 피함
        return await asyncio.to_thread(self._download, request, spider)

    def _download(self, request, spider):
        """실제 다운로드 로직(Thread 실행)."""
        settings = spider.settings if spider is not None else self.settings
        
        # 1. Scrapy Request Header -> requests Header 변환
        # (CookiesMiddleware가 채워준 Cookie 헤더도 여기서 넘어감)
        # requests.headers는 dict를 기대함
        req_headers = {}
        if request.headers:
            for k, v in request.headers.items():
                # Scrapy 헤더는 bytes 리스트 형태
                key_str = to_bytes(k).decode('latin1')
                val_str = to_bytes(v[0]).decode('latin1')
                req_headers[key_str] = val_str

        # User-Agent 보강
        if "User-Agent" not in req_headers:
             req_headers["User-Agent"] = settings.get("USER_AGENT")

        try:
            resp = requests.get(
                request.url,
                proxies=self.proxies,
                timeout=int(settings.get('DOWNLOAD_TIMEOUT', 60)),
                verify=settings.getbool("VERIFY_SSL", True),
                headers=req_headers
            )

            # 2. requests Header -> Scrapy Response Header 변환
            # (Set-Cookie 등 응답 헤더를 Scrapy로 전달)
            # 주의: requests는 이미 content를 디코딩했으므로, 
            # 'Content-Encoding: gzip' 헤더가 남아있으면 Scrapy가 또 디코딩을 시도하다 에러남(Not a gzipped file).
            # 따라서 Content-Encoding, Content-Length는 제거하고 넘겨야 함.
            resp_headers = {}
            for k, v in resp.headers.items():
                if k.lower() in ['content-encoding', 'content-length']:
                    continue
                resp_headers[k] = v
            
            return HtmlResponse(
                url=request.url,
                status=resp.status_code,
                body=resp.content,
                encoding=resp.encoding or 'utf-8',
                request=request,
                headers=resp_headers
            )

        except Exception as e:
            # 에러 메시지를 사람이 읽기 쉽게 변환
            error_str = str(e)
            if "RemoteDisconnected" in error_str or "closed connection" in error_str:
                friendly_msg = "🔄 Tor 연결 끊김 (재시도 예정)"
            elif "timed out" in error_str.lower() or "timeout" in error_str.lower():
                friendly_msg = "⏱️ 연결 시간 초과 (재시도 예정)"
            elif "refused" in error_str.lower():
                friendly_msg = "🚫 연결 거부됨"
            elif "reset" in error_str.lower():
                friendly_msg = "🔄 연결 리셋됨 (재시도 예정)"
            else:
                friendly_msg = f"❌ 연결 실패: {error_str[:50]}"
            
            logger.error(friendly_msg, url=request.url[:60])
            """
            에러 발생 시 여기서 None을 리턴하면 안 되고(Thread 안이므로),
            예외를 발생시키거나 Scrapy Response 객체를 만들어야 하는데,
            일반적으로는 예외를 던져서 Scrapy 엔진이 에러 처리(Retry 등)를 하게 둠
            """
            raise e
