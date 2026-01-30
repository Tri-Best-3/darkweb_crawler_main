"""
Supabase Integration Pipeline
"""
import os
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
    """

    def __init__(self, supabase_url, supabase_key):
        self.supabase_url = supabase_url
        self.supabase_key = supabase_key
        self.client: Client = None

    @classmethod
    def from_crawler(cls, crawler):
        # 환경변수 로드
        load_dotenv()
        
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")

        if not url or not key:
            raise NotConfigured("Supabase URL or Key not found in environment variables")
        
        return cls(supabase_url=url, supabase_key=key)

    def open_spider(self, spider):
        self.client = create_client(self.supabase_url, self.supabase_key)
        logger.info("Supabase 연결 성공", url=self.supabase_url)

    def process_item(self, item, spider):
        try:
            # 1. Scrapy Item -> DB Schema 매핑
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
            }

            # 2. Upsert 실행 (dedup_id 충돌 시 무시 or 업데이트)
            # ignore_duplicates=True와 유사한 효과를 위해 on_conflict 사용
            # 여기서는 "기존 데이터 유지" 정책을 사용 (수정이 거의 없는 포럼 특성)
            # 만약 "업데이트"가 필요하면 .upsert() 사용
            
            # upsert 옵션: on_conflict="dedup_id"
            response = self.client.table("darkweb_leaks").upsert(
                data, 
                on_conflict="dedup_id"
            ).execute()
            
            logger.debug("Supabase 저장 완료", title=item.get("title")[:20])

        except Exception as e:
            logger.error("Supabase 저장 실패", error=str(e), title=item.get("title", "")[:20])
            # DB 에러가 나도 파이프라인은 계속 진행 (알림 등 후속 작업을 위해)
            
        return item
