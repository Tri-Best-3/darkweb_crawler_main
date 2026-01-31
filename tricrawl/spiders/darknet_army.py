"""
DarkNetArmy Forum Spider (XenForo)
Target: http://dna777qhcrxy5sbvk7rkdd2phhxbftpdtxvwibih26nr275cdazx4uyd.onion/
"""
import scrapy
import structlog
import yaml
from pathlib import Path
from tricrawl.items import LeakItem
from datetime import datetime, timedelta, timezone
import hashlib

logger = structlog.get_logger(__name__)


class DarkNetArmySpider(scrapy.Spider):
    """
    Crawls the DarkNetArmy forum (XenForo based).

    Data Contract:
    - Populates LeakItem required fields: source, title, url, author, timestamp.
    - Content is cleaned text; hidden content blocks are noted.
    - Category is derived from forum breadcrumbs.
    """
    
    name = "darknet_army"
    start_urls = []
    
    custom_settings = {
        'ROBOTSTXT_OBEY': False,
        'DOWNLOAD_TIMEOUT': 120,
        'USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/115.0',
        'COOKIES_ENABLED': True,
        'DOWNLOADER_MIDDLEWARES': {
            'tricrawl.middlewares.darknet_requests.RequestsDownloaderMiddleware': 543,
            'tricrawl.middlewares.TorProxyMiddleware': None,
            'scrapy.downloadermiddlewares.httpproxy.HttpProxyMiddleware': None,
        }
    }
    
    def __init__(self, *args, **kwargs):
        """Loads configuration and executes initial setup."""
        super().__init__(*args, **kwargs)
        
        self.config = {}
        try:
            project_root = Path(__file__).resolve().parents[2]
            config_path = project_root / "config" / "crawler_config.yaml"
            
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    self.config = yaml.safe_load(f) or {}
                logger.info(f"Config loaded from {config_path}")
            else:
                logger.warning("Config file not found, using defaults")
                
        except Exception as e:
            logger.error(f"Config load failed: {e}")
            
        global_conf = self.config.get('global', {})
        self.days_limit = global_conf.get('days_to_crawl', 3)
        override_days = kwargs.get("days_limit")
        if override_days is not None:
            try:
                self.days_limit = int(override_days)
            except ValueError:
                logger.warning("Invalid days_limit override", value=override_days)
        
        spider_conf = self.config.get('spiders', {}).get('darknet_army', {})
        self.target_url = spider_conf.get('target_url')
        self.endpoints = spider_conf.get('endpoints', {})
        self.board_limits = spider_conf.get('boards', {})
        
        if self.target_url and self.endpoints:
            base = self.target_url.rstrip('/')
            for key, path in self.endpoints.items():
                clean_path = path.lstrip('/')
                full_url = f"{base}/{clean_path}"
                self.start_urls.append(full_url)
                logger.debug(f"Added start URL: {full_url}")
        else:
            logger.error("Target URL or Endpoints NOT found in config.")

        self.default_max_pages = 5
        logger.info(f"Loaded Config - Global Days: {self.days_limit}, URLs: {len(self.start_urls)}")

    def get_max_pages_for_url(self, url):
        """Returns page limit for the specific board URL."""
        for key, path in self.endpoints.items():
            if path.lstrip('/') in url:
                return self.board_limits.get(key, self.default_max_pages)
        return self.default_max_pages

    def parse(self, response):
        """Parses XenForo thread list view."""
        page_count = response.meta.get('page_count', 1)
        current_max_pages = self.get_max_pages_for_url(response.url)
        
        logger.info(f"Scanning Page {page_count}/{current_max_pages}", url=response.url)
        
        threads = response.css(".structItem")
        if not threads:
            logger.warning("No threads found (check structure or auth).")
            return

        found_recent_on_this_page = False
        found_old_normal_post = False
        
        for thread in threads:
            is_sticky = "structItem--status--sticky" in (thread.attrib.get("class") or "")
            
            # Title & Link extraction
            title_el = thread.css(".structItem-title a") or thread.css(".structItem-cell--title a")
            if not title_el:
                title_el = thread.css("a[data-preview-url]")

            link = title_el.css("::attr(href)").get()
            title = (title_el.css("::text").get() or "").strip()
            
            # Metadata
            author = thread.css(".structItem-parts .username::text").get() or \
                     thread.css(".structItem-cell--avatar img::attr(alt)").get() or "Unknown"
            
            # Timestamp Logic (Unix preferred)
            timestamp_candidates = []
            for raw_ts in thread.css("time::attr(data-time)").getall():
                try:
                    ts = int(raw_ts)
                except (TypeError, ValueError):
                    continue
                if ts > 10**12: # Handle ms timestamps
                    ts = ts // 1000
                timestamp_candidates.append(ts)

            timestamp_unix = max(timestamp_candidates) if timestamp_candidates else None
            date_str_candidates = []
            if not timestamp_unix:
                date_str_candidates = thread.css("time::attr(datetime)").getall()

            date_time = None
            is_recent = False
            
            try:
                dt = None
                if timestamp_unix:
                    dt = datetime.fromtimestamp(int(timestamp_unix), tz=timezone.utc)
                elif date_str_candidates:
                    parsed = []
                    for date_str in date_str_candidates:
                        try:
                            d = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                            if d.tzinfo is None:
                                d = d.replace(tzinfo=timezone.utc)
                            parsed.append(d)
                        except Exception:
                            continue
                    if parsed:
                        dt = max(parsed)
                
                if dt:
                    date_time = dt.isoformat()
                    cutoff_date = datetime.now(timezone.utc) - timedelta(days=self.days_limit)
                    
                    if dt >= cutoff_date:
                        is_recent = True
                        found_recent_on_this_page = True
                    else:
                        if not is_sticky:
                            found_old_normal_post = True
                else:
                    # Fallback if date parsing fails
                    is_recent = True
                    found_recent_on_this_page = True
                    
            except Exception:
                is_recent = True
                found_recent_on_this_page = True
            
            meta_data = {
                'title': title,
                'author': author,
                'timestamp': date_time,
                'views': self.parse_views(thread.css(".structItem-cell--meta dl.structItem-minor dd::text").get())
            }

            if link and is_recent:
                # Pre-Request Deduplication
                abs_link = response.urljoin(link)
                pre_calc_id = hashlib.md5(abs_link.encode()).hexdigest()
                
                if hasattr(self, "seen_ids") and pre_calc_id in self.seen_ids:
                    logger.debug(f"Skipping duplicate: {title[:20]}...")
                    self.crawler.stats.inc_value('pre_dedup/skipped')
                    continue

                yield response.follow(link, callback=self.parse_post, meta=meta_data)

        # Pagination Logic
        if not found_recent_on_this_page and found_old_normal_post:
            logger.info("Pagination stopped: No recent posts found.")
            return

        if current_max_pages > 0 and page_count >= current_max_pages:
            logger.info(f"Pagination stopped: Max pages ({current_max_pages}) reached.")
            return

        next_page = response.css("a.pageNav-jump--next::attr(href)").get()
        if next_page:
            yield response.follow(next_page, callback=self.parse, meta={'page_count': page_count + 1})

    def parse_views(self, views_str):
        if not views_str:
            return None
        try:
            s = views_str.lower().strip()
            if 'k' in s:
                return int(float(s.replace('k', '')) * 1000)
            elif 'm' in s:
                return int(float(s.replace('m', '')) * 1000000)
            else:
                return int(s.replace(',', ''))
        except:
            return None

    def parse_post(self, response):
        """Parses thread detail view (XenForo)."""
        item = LeakItem()
        item["source"] = "DarkNetArmy"
        item["url"] = response.url
        item["dedup_id"] = hashlib.md5(response.url.encode()).hexdigest()
        
        meta_title = response.meta.get('title')
        meta_author = response.meta.get('author')
        meta_time = response.meta.get('timestamp')
        meta_views = response.meta.get('views')
        
        item["title"] = (
            response.css("h1.p-title-value::text").get() or 
            meta_title or
            response.css("title::text").get()
        ).strip()
        
        posts = response.css("article.message--post") or response.css("article.message")
        
        if posts:
            first_post = posts[0]
            content_div = first_post.css(".message-content .bbWrapper")
            
            # Check for hidden content
            is_hidden = bool(content_div.css(".bbCodeBlock--hide"))
            
            content_parts = []
            for node in content_div.css("*::text").getall():
                text = node.strip()
                if text:
                    content_parts.append(text)
            
            dirty_content = "\n".join(content_parts)
            
            # Extract contacts
            contacts = []
            links = content_div.css("a::attr(href)").getall()
            for link in links:
                if "t.me" in link or "telegram" in link:
                    contacts.append(link)
            
            if is_hidden:
                dirty_content = f"🔒 [Hidden Content] (Requires Reaction)\n\n" + dirty_content
                if contacts:
                    dirty_content += f"\n\n📞 Found Contacts:\n" + "\n".join(contacts)

            item["content"] = dirty_content[:5000]
            
            # Author fallback
            if not meta_author or meta_author == "Unknown":
                item["author"] = first_post.css(".message-name .username::text").get() or \
                                 first_post.css(".message-userDetails .username::text").get() or \
                                 "Unknown"
            else:
                item["author"] = meta_author
                
            item["timestamp"] = meta_time
            item["site_type"] = "Forum"
            
            breadcrumbs = response.css(".p-breadcrumbs li a span::text").getall()
            if breadcrumbs:
                item["category"] = breadcrumbs[-1].strip()
            else:
                 item["category"] = "General"
            
            if meta_views is not None:
                item["views"] = meta_views
            else:
                try:
                    views_val = response.xpath("//dt[contains(translate(., 'VIEWS', 'views'), 'views')]/following-sibling::dd[1]/text()").get()
                    item["views"] = self.parse_views(views_val) if views_val else None
                except Exception:
                    item["views"] = None
                
        else:
            # Fallback layout
            item["content"] = " ".join(response.css("body *::text").getall()).strip()[:1000]
            item["author"] = meta_author or "Unknown"
            item["timestamp"] = meta_time
            item["site_type"] = "Forum"
            item["category"] = "Unknown"
            item["views"] = meta_views
        
        if item["author"]:
            item["author"] = item["author"].strip()
            
        yield item
