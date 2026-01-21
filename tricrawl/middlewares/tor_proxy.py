"""
Tor 프록시 미들웨어
.onion 주소는 Tor 프록시를 통해 라우팅
"""
import structlog
from scrapy import signals
from scrapy.exceptions import NotConfigured

logger = structlog.get_logger(__name__)


class TorProxyMiddleware:
    # Tor SOCKS5 프록시를 통한 요청 라우팅
    
    def __init__(self, tor_proxy: str):
        self.tor_proxy = tor_proxy
        self._spider = None
        
    @classmethod
    def from_crawler(cls, crawler):
        tor_proxy = crawler.settings.get("TOR_PROXY")
        if not tor_proxy:
            raise NotConfigured("TOR_PROXY 설정이 필요합니다")
        
        middleware = cls(tor_proxy)
        crawler.signals.connect(middleware.spider_opened, signal=signals.spider_opened)
        return middleware
    
    def spider_opened(self, spider):
        self._spider = spider
        logger.info("Tor 프록시 활성화", proxy=self.tor_proxy, spider=spider.name)
    
    def process_request(self, request, spider=None):
        # URL에 따라 프록시 선택적 적용
        if spider is None:
            spider = self._spider
        url = request.url
        
        # .onion 주소 → Tor 프록시 필수
        if ".onion" in url:
            request.meta["proxy"] = self.tor_proxy
            logger.debug("Tor 프록시 적용", url=url[:50])
        else:
            # 표면웹은 직접 연결(또는 다른 프록시 사용 가능)
            logger.debug("직접 연결", url=url[:50])
        
        return None
