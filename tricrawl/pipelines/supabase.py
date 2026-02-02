"""
Supabase Integration Pipeline
Saves filtered items to the database.
"""
import os
import re
import yaml
import structlog
from pathlib import Path
from dotenv import load_dotenv

from supabase import create_client, Client
from scrapy.exceptions import NotConfigured

logger = structlog.get_logger(__name__)

class SupabasePipeline:
    """
    Saves items to Supabase 'darkweb_leaks' table.
    Performs UPSERT based on dedup_id.
    """

    def __init__(self, supabase_url, supabase_key, contact_patterns=None):
        self.supabase_url = supabase_url
        self.supabase_key = supabase_key
        self.client: Client = None
        self.contact_patterns = contact_patterns or {}

    @classmethod
    def from_crawler(cls, crawler):
        load_dotenv()
        
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")

        if not url or not key:
            raise NotConfigured("Supabase URL or Key not found")
        
        project_root = Path(__file__).parent.parent.parent
        keywords_path = project_root / "config" / "keywords.yaml"
        contact_patterns = {}
        
        try:
            with open(keywords_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
                contact_patterns = config.get("patterns", {}).get("contacts", {})
        except Exception as e:
            logger.warning(f"Failed to load contact patterns: {e}")
        
        return cls(supabase_url=url, supabase_key=key, contact_patterns=contact_patterns)

    def open_spider(self, spider):
        self.client = create_client(self.supabase_url, self.supabase_key)
        logger.info("Supabase Connected")

    def _extract_contacts(self, text: str) -> dict:
        contacts = {}
        if not text:
            return contacts
        
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

    def process_item(self, item, spider):
        try:
            content = item.get("content", "")
            author_contacts = self._extract_contacts(content)
            
            keywords = item.get("matched_keywords", []) + item.get("matched_targets", [])
            
            data = {
                "dedup_id": item.get("dedup_id"),
                "source": item.get("source"),
                "title": item.get("title"),
                "content": item.get("content"),
                "url": item.get("url"),
                "author": item.get("author"),
                "category": item.get("category"),
                "posted_at": item.get("timestamp"),
                "matched_keywords": keywords,
                "risk_level": item.get("risk_level", "NONE"),
                "author_contacts": author_contacts,
                "crawled_at": "now()",
                "site_type": item.get("site_type", "Unknown"),
                "views": item.get("views")
            }

            self.client.table("darkweb_leaks").upsert(data, on_conflict="dedup_id").execute()
            
        except Exception as e:
            logger.error(f"Supabase Save Error: {e}")
            
        return item
