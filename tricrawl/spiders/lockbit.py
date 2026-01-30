import scrapy
from datetime import datetime, timezone
from tricrawl.items import LeakItem

class LockBitSpider(scrapy.Spider):
    name = "lockbit"
    allowed_domains = ["lockbit3olp7oetlc4tl5zydnoluphh7fvdt5oa6arcp2757r7xkutid.onion"]
    start_urls = [
        "http://lockbit3olp7oetlc4tl5zydnoluphh7fvdt5oa6arcp2757r7xkutid.onion/"
    ]
    
    custom_settings = {
        "DOWNLOADER_MIDDLEWARES": {
            "tricrawl.middlewares.darknet_requests.RequestsDownloaderMiddleware": 543,
            "tricrawl.middlewares.TorProxyMiddleware": None,
            "scrapy.downloadermiddlewares.httpproxy.HttpProxyMiddleware": None,
        },
        "DOWNLOAD_DELAY": 3,
        "CLOSESPIDER_PAGECOUNT": 1,
    }

    def parse(self, response):
        self.logger.info(f"[LockBit] Status: {response.status}")
        
        # LockBit 3.0은 div.post-block 구조를 많이 사용
        posts = response.css('div.post-block, a.post-block')
        
        for post in posts:
            title = post.css('div.post-title::text, h3::text').get()
            if not title:
                continue
                
            link = post.attrib.get('href')
            url = response.urljoin(link) if link else response.url
            
            # 설명/본문
            desc = post.css('div.post-block-text::text, p::text').getall()
            content = " ".join([d.strip() for d in desc if d.strip()])
            
            # 날짜 (Deadline 등)
            date_str = post.css('div.post-timer::text').get('')
            
            yield LeakItem(
                source="LockBit",
                title=title.strip(),
                url=url,
                author="LockBit 3.0",
                timestamp=datetime.now(timezone.utc).isoformat(),
                content=f"Deadline: {date_str}\n\n{content}",
                category="Ransomware",
                site_type="Ransomware",  # ⭐
                dedup_id=None
            )
