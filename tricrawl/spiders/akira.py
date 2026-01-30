import scrapy
import json
import hashlib
from datetime import datetime, timezone
from tricrawl.items import LeakItem


class AkiraSpider(scrapy.Spider):
    """
    Akira Ransomware Group Crawler
    
    Lineage:
    - Target: Akira ransomware victim list
    - Structure: JSON API based (/l endpoint)
    - site_type: "Ransomware"
    """
    
    name = "akira"
    # Note: verify=False is often needed for onion HTTPS, handled by middleware or scrapy settings if configured
    # Using the URL from crawl_akira_full.py
    allowed_domains = ["akiral2iz6a7qgd3ayp3l6yub7xx2uep76idk3u2kollpj5z3z636bad.onion"]
    
    # Custom settings to ensure proper Tor connection and headers
    custom_settings = {
        "DOWNLOADER_MIDDLEWARES": {
            "tricrawl.middlewares.darknet_requests.RequestsDownloaderMiddleware": 543,
            "tricrawl.middlewares.TorProxyMiddleware": None,
            "scrapy.downloadermiddlewares.httpproxy.HttpProxyMiddleware": None,
        },
        "DOWNLOAD_DELAY": 2,
        "DEFAULT_REQUEST_HEADERS": {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0',
            'Accept': '*/*',
            'X-Requested-With': 'XMLHttpRequest',
        }
    }

    def start_requests(self):
        # Get URL from config or use default
        target_url = self.settings.get("CRAWLER_CONFIG", {}).get("spiders", {}).get("akira", {}).get("target_url")
        if not target_url:
            target_url = "https://akiral2iz6a7qgd3ayp3l6yub7xx2uep76idk3u2kollpj5z3z636bad.onion"
            
        self.base_url = target_url.rstrip('/')
        
        # Start with page 1
        yield self._make_api_request(page=1)

    def _make_api_request(self, page):
        url = f"{self.base_url}/l?page={page}&sort=name:asc"
        self.logger.info(f"[Akira] Requesting page {page}: {url}")
        return scrapy.Request(
            url=url,
            callback=self.parse,
            meta={'page': page},
            dont_filter=True 
        )

    def parse(self, response):
        page = response.meta['page']
        
        try:
            data = response.json()
        except json.JSONDecodeError:
            self.logger.error(f"[Akira] Failed to parse JSON on page {page}. Content: {response.text[:100]}...")
            return

        victims = data.get('objects', [])
        if not victims:
            self.logger.info(f"[Akira] No more victims found on page {page}. Stopping.")
            return

        self.logger.info(f"[Akira] Found {len(victims)} victims on page {page}")
        
        for v in victims:
            name = v.get('name', '').strip()
            desc = v.get('desc', '').strip()
            progress = v.get('progress', '')
            
            # Combine content
            content = f"{desc}\n\nProgress: {progress}"
            
            # Use name and partial content for dedup key
            dedup_key = f"{name}|{self.name}"
            dedup_id = hashlib.md5(dedup_key.encode()).hexdigest()
            
            yield LeakItem(
                source="Akira Ransomware",
                title=name,
                url=response.url, # As this is a single page application/list, we just point to the site or construct a fake url? 
                                  # response.url is the API url. Ideally we want the visible page.
                                  # We'll stick to response.url or base_url for now.
                author="Akira Group",
                timestamp=datetime.now(timezone.utc).isoformat(),
                content=content,
                category="Ransomware",
                site_type="Ransomware",
                dedup_id=dedup_id
            )
            
        # Pagination: Go to next page
        yield self._make_api_request(page=page + 1)
