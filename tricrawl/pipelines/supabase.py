"""
Supabase Integration Pipeline
"""
import os
import re
import yaml
import structlog
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

from supabase import create_client, Client
from scrapy.exceptions import NotConfigured

logger = structlog.get_logger(__name__)

class SupabasePipeline:
    """
    Scrapy 아이템을 Supabase DB('darkweb_leaks' 테이블)에 저장.
    
    특징:
    - settings.py에서 설정된 순서에 따라 Dedup/Filter 이후 실행됨
    - dedup_id를 기준으로 UPSERT (기존 데이터가 있으면 업데이트하지 않거나 무시)
    - content에서 연락처(telegram, email 등) 자동 추출
    """

    def __init__(self, supabase_url, supabase_key, contact_patterns=None):
        self.supabase_url = supabase_url
        self.supabase_key = supabase_key
        self.client: Client = None
        self.contact_patterns = contact_patterns or {}

    @classmethod
    def from_crawler(cls, crawler):
        # 환경변수 로드
        load_dotenv()
        
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")

        if not url or not key:
            raise NotConfigured("Supabase URL or Key not found in environment variables")
        
        # keywords.yaml에서 연락처 패턴 로드
        project_root = Path(__file__).parent.parent.parent
        keywords_path = project_root / "config" / "keywords.yaml"
        contact_patterns = {}
        
        try:
            with open(keywords_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
                contact_patterns = config.get("patterns", {}).get("contacts", {})
                logger.info(f"연락처 패턴 로드: {list(contact_patterns.keys())}")
        except Exception as e:
            logger.warning(f"keywords.yaml 로드 실패: {e}")
        
        return cls(supabase_url=url, supabase_key=key, contact_patterns=contact_patterns)

    def open_spider(self, spider):
        self.client = create_client(self.supabase_url, self.supabase_key)
        logger.info("Supabase 연결 성공", url=self.supabase_url)

    def _extract_contacts(self, text: str) -> dict:
        """본문 텍스트에서 연락처(telegram/email/discord 등)를 정규식으로 추출."""
        contacts = {}
        if not text:
            return contacts
        
        for contact_type, patterns in self.contact_patterns.items():
            if not patterns:
                continue
            
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
            # 1. 본문에서 연락처 추출
            content = item.get("content", "")
            author_contacts = self._extract_contacts(content)
            
            # 2. Scrapy Item -> DB Schema 매핑
            # matched_targets는 matched_keywords(Array)에 병합하여 저장
            keywords = item.get("matched_keywords", []) + item.get("matched_targets", [])
            
            data = {
                "dedup_id": item.get("dedup_id"),
                "source": item.get("source"),
                "title": item.get("title"),
                "content": item.get("content"),
                "author": item.get("author"),
                "url": item.get("url"),
                "risk_level": item.get("risk_level", "LOW"),
                "matched_keywords": list(set(keywords)), # 중복 제거
                "crawled_at": datetime.now(timezone.utc).isoformat(),
                "posted_at": item.get("timestamp"), # 스파이더가 추출한 원본 시간
                "category": item.get("category"),   # "Leaked Databases" (게시판)
                "site_type": item.get("site_type"), # "Forum" vs "Ransomware"
                "views": item.get("views"),
                "author_contacts": author_contacts,  # 연락처 정보 (JSONB)
            }

            # 3. Upsert 실행 (dedup_id 충돌 시 무시 or 업데이트)
            response = self.client.table("darkweb_leaks").upsert(
                data, 
                on_conflict="dedup_id"
            ).execute()
            
            # 연락처가 있으면 로그에 표시
            if author_contacts:
                logger.debug("연락처 추출됨", contacts=list(author_contacts.keys()), title=item.get("title")[:20])
            else:
                logger.debug("Supabase 저장 완료", title=item.get("title")[:20])

        except Exception as e:
            logger.error("Supabase 저장 실패", error=str(e), title=item.get("title", "")[:20])
            # DB 에러가 나도 파이프라인은 계속 진행 (알림 등 후속 작업을 위해)
            
        return item
