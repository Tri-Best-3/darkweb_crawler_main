"""
Requests-based Downloader Middleware
Handles .onion requests via Tor proxy (SOCKS5h) using the 'requests' library
to bypass Scrapy's DNS/Twisted limitations for hidden services.
"""
import asyncio
import requests
import urllib3
import structlog
from scrapy.http import HtmlResponse
# from scrapy.downloadermiddlewares.retry import RetryMiddleware
from scrapy.utils.python import to_bytes

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = structlog.get_logger(__name__)

class RequestsDownloaderMiddleware:
    """
    Intercepts .onion requests and performs them using `requests` with SOCKS5 proxy.
    """
    def __init__(self, tor_proxy, settings):
        self.tor_proxy = tor_proxy
        self.settings = settings
        self.proxies = {
            'http': f"socks5h://{tor_proxy}",
            'https': f"socks5h://{tor_proxy}"
        } if tor_proxy else None

    @classmethod
    def from_crawler(cls, crawler):
        host = crawler.settings.get("TOR_PROXY_HOST", "127.0.0.1")
        port = crawler.settings.get("TOR_PROXY_PORT", "9050")
        tor_proxy = f"{host}:{port}"
        return cls(tor_proxy, crawler.settings)

    async def process_request(self, request, spider=None):
        if ".onion" not in request.url:
             return None 

        logger.info("Using Requests Downloader (Async)", url=request.url)
        return await asyncio.to_thread(self._download, request, spider)

    def _download(self, request, spider):
        settings = spider.settings if spider is not None else self.settings
        
        req_headers = {}
        if request.headers:
            for k, v in request.headers.items():
                key_str = to_bytes(k).decode('latin1')
                val_str = to_bytes(v[0]).decode('latin1')
                req_headers[key_str] = val_str

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
            error_str = str(e)
            if "RemoteDisconnected" in error_str or "closed connection" in error_str:
                msg = "🔄 Tor Connection Dropped (Will Retry)"
            elif "timed out" in error_str.lower() or "timeout" in error_str.lower():
                msg = "⏱️ Connection Timeout (Will Retry)"
            elif "refused" in error_str.lower():
                msg = "🚫 Connection Refused"
            else:
                msg = f"❌ Request Failed: {error_str[:50]}"
            
            logger.error(msg, url=request.url[:60])
            raise e
