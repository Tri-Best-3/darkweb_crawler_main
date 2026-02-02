"""
Tor Proxy Middleware
Routes .onion requests through Tor SOCKS5 proxy
"""
import structlog
from scrapy import signals
from scrapy.exceptions import NotConfigured

logger = structlog.get_logger(__name__)


class TorProxyMiddleware:
    """
    Routes requests through Tor SOCKS5 proxy.
    - Forces Tor for .onion addresses
    - Direct connection (or other proxy) for clear web
    """
    
    def __init__(self, tor_proxy: str):
        self.tor_proxy = tor_proxy
        self._spider = None
        
    @classmethod
    def from_crawler(cls, crawler):
        tor_proxy = crawler.settings.get("TOR_PROXY")
        if not tor_proxy:
            raise NotConfigured("TOR_PROXY setting required")
        
        middleware = cls(tor_proxy)
        crawler.signals.connect(middleware.spider_opened, signal=signals.spider_opened)
        return middleware
    
    def spider_opened(self, spider):
        self._spider = spider
        logger.info("Tor Proxy Enabled", proxy=self.tor_proxy, spider=spider.name)
    
    def process_request(self, request, spider=None):
        # Route based on URL (onion -> Tor)
        if spider is None:
            spider = self._spider
        url = request.url
        
        if ".onion" in url:
            request.meta["proxy"] = self.tor_proxy
            logger.debug("Routing via Tor", url=url[:50])
        else:
            logger.debug("Direct Connection", url=url[:50])
        
        return None
