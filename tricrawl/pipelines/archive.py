"""
Data Archive Pipeline
- Saves all crawled items to JSONL immediately (stream write).
- Extracts contacts (email, telegram) for downstream usage.
"""
import json
import re
import structlog
from pathlib import Path
from datetime import datetime

logger = structlog.get_logger(__name__)


class ArchivePipeline:
    """
    ArchivePipeline

    Responsibilities:
    - Streams every item to a JSONL file immediately for safety.
    - Extracts author contacts/keywords and injects them into the item.
    """
    
    def __init__(self, data_dir: Path, keywords_config: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.file_handle = None
        self._crawler = None
        self._spider = None
        
        self.config = self._load_yaml(keywords_config)
        self.all_keywords = self._extract_keywords(self.config)
        self.contact_patterns = self.config.get("patterns", {}).get("contacts", {})

    @classmethod
    def from_crawler(cls, crawler):
        data_dir = Path("data")
        keywords_config = crawler.settings.get("KEYWORDS_CONFIG")
        pipeline = cls(data_dir, keywords_config)
        pipeline._crawler = crawler
        return pipeline
        
    def open_spider(self, spider=None):
        """Opens the spider-specific archive file."""
        spider_obj = self._resolve_spider(spider)
        spider_name = spider_obj.name if spider_obj else "unknown"
        filename = f"archive_{spider_name}.jsonl"
        self.archive_path = self.data_dir / filename
        
        try:
            self.file_handle = open(self.archive_path, "a", encoding="utf-8", buffering=1)
            logger.info(f"[{spider_name}] Archive Stream Opened: {self.archive_path}")
        except Exception as e:
            logger.error(f"Failed to open archive file: {e}")
            self.file_handle = None

    def close_spider(self, spider=None):
        if self.file_handle:
            self.file_handle.close()
            spider_obj = self._resolve_spider(spider)
            spider_name = spider_obj.name if spider_obj else "unknown"
            logger.info(f"[{spider_name}] Archive Closed")

    def _load_yaml(self, path: Path) -> dict:
        try:
            import yaml
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"Failed to load YAML config: {e}")
            return {}

    def _extract_keywords(self, config: dict) -> set:
        all_kw = set()
        for key, val in config.items():
            if key == "patterns": continue
            if isinstance(val, list):
                all_kw.update(kw.lower() for kw in val if isinstance(kw, str))
            elif isinstance(val, dict):
                all_kw.update(self._extract_keywords(val))
        return all_kw
    
    def _extract_contacts(self, text: str) -> dict:
        contacts = {}
        if not text: return contacts
        
        for contact_type, patterns in self.contact_patterns.items():
            if not patterns: continue
            
            found = set()
            for pattern in patterns:
                try:
                    matches = re.findall(pattern, text, re.IGNORECASE)
                    found.update(matches)
                except re.error:
                    continue
            
            if found:
                contacts[contact_type] = list(found)
        
        return contacts

    def process_item(self, item, spider=None):
        if not self.file_handle:
            return item

        spider_obj = self._resolve_spider(spider)
        spider_name = spider_obj.name if spider_obj else "unknown"
            
        content = item.get("content", "")
        author_contacts = self._extract_contacts(content)
        item["author_contacts"] = author_contacts
        
        text = f"{item.get('title', '')} {content}".lower()
        matched_keywords = [kw for kw in self.all_keywords if kw in text]
        
        archive_entry = {
            "spider": spider_name,
            "category": item.get("category", "Unknown"),
            "title": item.get("title", ""),
            "timestamp": item.get("timestamp"),
            "author": item.get("author", "Unknown"),
            "author_contacts": author_contacts,
            "url": item.get("url", ""),
            "matched_keywords": matched_keywords,
            "crawled_at": datetime.now().isoformat(),
            "dedup_id": item.get("dedup_id")
        }
        
        try:
            line = json.dumps(archive_entry, ensure_ascii=False)
            self.file_handle.write(line + "\n")
        except Exception as e:
            logger.error(f"Archive Write Failed: {e}", title=item.get("title"))
        
        return item

    def _resolve_spider(self, spider):
        if spider is not None:
            self._spider = spider
            return spider
        if self._spider is not None:
            return self._spider
        if self._crawler is not None:
            return getattr(self._crawler, "spider", None)
        return None
