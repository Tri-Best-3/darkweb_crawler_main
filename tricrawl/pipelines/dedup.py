"""
Deduplication Pipeline (Supabase Based)
Checks `dedup_id` against Supabase DB to skip duplicates.
"""
import hashlib
import os
import requests
from scrapy.exceptions import DropItem
from supabase import create_client, Client
import structlog
from dotenv import load_dotenv

load_dotenv()
logger = structlog.get_logger(__name__)


class DeduplicationPipeline:
    """
    Supabase-based Deduplication.
    1. Initial Load: Fetches recent IDs from DB to memory.
    2. Process Item: Checks memory cache; adds new items to cache.
    """

    def __init__(self, max_entries: int):
        self.max_entries = max_entries
        self.seen_hashes = set()
        self.supabase: Client = None
        self._crawler = None
        self._spider = None
        self._webhook_url = None
        self._notify_on_no_new = True
        
        # Stats
        self.total_items = 0
        self.new_items = 0
        self.duplicate_items = 0

    @classmethod
    def from_crawler(cls, crawler):
        max_entries = crawler.settings.getint("DEDUP_MAX_ENTRIES", 20000)
        pipeline = cls(max_entries)
        pipeline._crawler = crawler
        pipeline._webhook_url = crawler.settings.get("DISCORD_WEBHOOK_URL")
        pipeline._notify_on_no_new = crawler.settings.getbool("NOTIFY_ON_NO_NEW_DATA", True)
        return pipeline

    def open_spider(self, spider=None):
        spider_obj = self._resolve_spider(spider)
        spider_name = spider_obj.name if spider_obj else "unknown"

        self.total_items = 0
        self.new_items = 0
        self.duplicate_items = 0
        self.seen_hashes = set()

        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")

        if not url or not key:
            logger.warning("Supabase credentials missing. Running in Memory-Only mode.")
            return

        try:
            self.supabase = create_client(url, key)
            logger.info(f"[{spider_name}] Supabase connected. Syncing IDs...")
            
            page_size = 1000
            offset = 0
            total_loaded = 0
            
            while total_loaded < self.max_entries:
                res = self.supabase.table("darkweb_leaks")\
                    .select("dedup_id")\
                    .order("crawled_at", desc=True)\
                    .range(offset, offset + page_size - 1)\
                    .execute()
                
                if not res.data:
                    break
                    
                for row in res.data:
                    did = row.get("dedup_id")
                    if did:
                        self.seen_hashes.add(did)
                        total_loaded += 1
                
                if len(res.data) < page_size:
                    break
                    
                offset += page_size
            
            if self._crawler:
                self._crawler.stats.set_value("dedup/loaded_ids", total_loaded)
            
            logger.info(f"[{spider_name}] Loaded {total_loaded} IDs from Supabase.")

        except Exception as e:
            logger.error(f"Supabase sync failed: {e}")

        # Inject into spider for pre-filtering
        if spider_obj:
            spider_obj.seen_ids = self.seen_hashes
            logger.info(f"[{spider_name}] Pre-filtering Enabled: {len(self.seen_hashes)} IDs injected.")

    def get_hash(self, item):
        custom_id = item.get("dedup_id")
        if custom_id:
            return custom_id

        title = item.get("title", "")
        author = item.get("author", "")
        key = f"{title}|{author}"
        gen_hash = hashlib.md5(key.encode()).hexdigest()
        
        item["dedup_id"] = gen_hash
        return gen_hash

    def process_item(self, item, spider=None):
        item_hash = self.get_hash(item)
        self.total_items += 1

        if item_hash in self.seen_hashes:
            self.duplicate_items += 1
            logger.debug(f"Duplicate (DB): {item.get('title', '')[:30]}")
            raise DropItem(f"Duplicate (DB): {item.get('title', '')[:30]}")

        self.new_items += 1
        self.seen_hashes.add(item_hash)
        return item

    def close_spider(self, spider=None):
        spider_obj = self._resolve_spider(spider)
        spider_name = spider_obj.name if spider_obj else "unknown"

        self._log_summary(spider_name)
        self._notify_no_new(spider_name)

    def _log_summary(self, spider_name):
        logger.info(
            f"[{spider_name}] Dedup Summary",
            total=self.total_items,
            new=self.new_items,
            duplicates=self.duplicate_items,
        )

    def _notify_no_new(self, spider_name):
        if not self._notify_on_no_new:
            return
        
        if self.total_items == 0:
            return
        
        if self.new_items != 0:
            return
            
        if not self._webhook_url:
            return

        payload = {
            "content": f"🕷️ **{spider_name}**: No new data found ({self.duplicate_items} duplicates)."
        }

        try:
            requests.post(
                self._webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=5
            )
        except Exception:
            pass

    def _resolve_spider(self, spider):
        if spider is not None:
            self._spider = spider
            return spider
        if self._spider is not None:
            return self._spider
        if self._crawler is not None:
            return getattr(self._crawler, "spider", None)
        return None
