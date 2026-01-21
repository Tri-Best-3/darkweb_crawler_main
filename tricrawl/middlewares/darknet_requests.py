"""
Scrapy의 Twisted Reactor 대신 requests 라이브러리를 사용하여 다운로드
포럼 구조에서 SOCKS5 프록시 연결에 문제가 있어서 대체 구현
"""
import asyncio
import requests
import structlog
from scrapy.http import HtmlResponse
from scrapy.downloadermiddlewares.retry import RetryMiddleware
from scrapy.utils.python import to_bytes

logger = structlog.get_logger(__name__)

class RequestsDownloaderMiddleware:
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
        # TOR_PROXYHOST, TOR_PROXYPORT 가져오기
        host = crawler.settings.get("TOR_PROXY_HOST", "127.0.0.1")
        port = crawler.settings.get("TOR_PROXY_PORT", "9050")
        tor_proxy = f"{host}:{port}"
        return cls(tor_proxy, crawler.settings)

    async def process_request(self, request, spider=None):
        # .onion 주소에 대해서만 custom downloader 사용
        if ".onion" not in request.url:
             return None # Scrapy 기본 처리

        logger.info("Requests 다운로더 사용(Async)", url=request.url)

        # asyncio thread로 실행해 Deferred 반환 문제 피함
        return await asyncio.to_thread(self._download, request, spider)

    def _download(self, request, spider):
        """실제 다운로드 로직(Thread 실행)"""
        settings = spider.settings if spider is not None else self.settings
        try:
            resp = requests.get(
                request.url,
                proxies=self.proxies,
                timeout=int(settings.get('DOWNLOAD_TIMEOUT', 60)),
                verify=settings.getbool("VERIFY_SSL", True),
                headers={
                    "User-Agent": settings.get("USER_AGENT")
                }
            )

            return HtmlResponse(
                url=request.url,
                status=resp.status_code,
                body=resp.content,
                encoding=resp.encoding or 'utf-8',
                request=request
            )

        except Exception as e:
            logger.error("다운로드 실패", url=request.url, error=str(e))
            """
            에러 발생 시 여기서 None을 리턴하면 안 되고(Thread 안이므로),
            예외를 발생시키거나 Scrapy Response 객체를 만들어야 하는데,
            일반적으로는 예외를 던져서 Scrapy 엔진이 에러 처리(Retry 등)를 하게 둠
            """
            raise e
