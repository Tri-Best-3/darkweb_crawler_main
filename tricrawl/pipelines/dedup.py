"""
중복 게시물 필터링 파이프라인 (Supabase 기반)
로컬 파일 대신 Supabase DB에 있는 dedup_id를 조회하여 중복을 판단함.
분산 환경(팀 프로젝트)에서 여러 크롤러가 상태를 공유하기 위함.
"""
import hashlib
import time
import os
import requests
from pathlib import Path
from scrapy.exceptions import DropItem
from supabase import create_client, Client
import structlog
from dotenv import load_dotenv

# 환경변수 로드 (Scrapy 단독 실행 시 대비)
load_dotenv()

logger = structlog.get_logger(__name__)


class DeduplicationPipeline:
    """
    Supabase 기반 중복 필터링
    1. 스파이더 시작 시: DB에서 최근 N개의 dedup_id를 가져와 메모리에 적재 (Initial Load)
    2. 아이템 처리 시: 메모리에 있으면 Drop, 없으면 통과
    (메모리 추가는 process_item 성공 시)
    """

    def __init__(self, max_entries: int):
        self.max_entries = max_entries
        
        # 메모리 상의 중복 체크용 Set
        self.seen_hashes = set()
        
        # Supabase 클라이언트
        self.supabase: Client = None
        
        # 스파이더/크롤러 참조
        self._crawler = None
        self._spider = None

        # 알림 설정
        self._webhook_url = None
        self._notify_on_no_new = True

        # 통계
        self.total_items = 0
        self.new_items = 0
        self.duplicate_items = 0

    @classmethod
    def from_crawler(cls, crawler):
        """Scrapy 설정값을 읽어 파이프라인 초기화."""
        max_entries = crawler.settings.getint("DEDUP_MAX_ENTRIES", 20000)
        
        pipeline = cls(max_entries)
        pipeline._crawler = crawler
        pipeline._webhook_url = crawler.settings.get("DISCORD_WEBHOOK_URL")
        pipeline._notify_on_no_new = crawler.settings.getbool("NOTIFY_ON_NO_NEW_DATA", True)
        return pipeline

    def open_spider(self, spider=None):
        """스파이더 시작 시 DB 동기화."""
        spider_obj = self._resolve_spider(spider)
        spider_name = spider_obj.name if spider_obj else "unknown"

        # 통계 초기화
        self.total_items = 0
        self.new_items = 0
        self.duplicate_items = 0
        self.seen_hashes = set()

        # Supabase 연결
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")

        if not url or not key:
            logger.warning("⚠️ Supabase 자격증명이 없어 중복 체크가 '메모리 전용(이번 실행만)'으로 동작합니다.")
            return

        try:
            self.supabase = create_client(url, key)
            logger.info(f"[{spider_name}] Supabase 연결 성공. 중복 ID 동기화 중...")
            
            # 최근 저장된 데이터의 dedup_id만 가져옴 (가벼운 쿼리)
            # limit을 설정하여 메모리 과부하 방지
            res = self.supabase.table("darkweb_leaks")\
                .select("dedup_id")\
                .order("crawled_at", desc=True)\
                .limit(self.max_entries)\
                .execute()
            
            if res.data:
                count = 0
                for row in res.data:
                    did = row.get("dedup_id")
                    if did:
                        self.seen_hashes.add(did)
                        count += 1
                
                # Stats에 저장 (RichProgress에서 읽을 수 있도록)
                if self._crawler:
                    self._crawler.stats.set_value("dedup/loaded_ids", count)
                
                logger.info(f"[{spider_name}] ✅ Supabase에서 {count}개의 중복 ID 로드 완료.")
            else:
                if self._crawler:
                    self._crawler.stats.set_value("dedup/loaded_ids", 0)
                logger.info(f"[{spider_name}] DB가 비어있거나 초기 상태입니다.")

        except Exception as e:
            logger.error(f"❌ Supabase 초기 로드 실패: {e}")

        # [Optimization] 스파이더에게 중복 ID 세트 주입 (Pre-request Filtering용)
        # 스파이더가 요청을 보내기 전에 이 세트를 확인하여 불필요한 IO를 줄일 수 있음
        if spider_obj:
            spider_obj.seen_ids = self.seen_hashes
            logger.info(f"[{spider_name}] 🚀 Pre-filtering Activated: {len(self.seen_hashes)} IDs injected into spider.")

    def get_hash(self, item):
        """게시물 고유 해시 생성 (또는 기존 ID 사용)"""
        custom_id = item.get("dedup_id")
        if custom_id:
            return custom_id

        title = item.get("title", "")
        author = item.get("author", "")
        key = f"{title}|{author}"
        gen_hash = hashlib.md5(key.encode()).hexdigest()
        
        # 생성된 해시를 아이템에 기록 (다음 파이프라인인 SupabasePipeline 등에서 사용)
        item["dedup_id"] = gen_hash
        return gen_hash

    def process_item(self, item, spider=None):
        """중복 검사"""
        item_hash = self.get_hash(item)
        self.total_items += 1

        if item_hash in self.seen_hashes:
            self.duplicate_items += 1
            # 로그 레벨 조정 (너무 시끄러우면 debug로 변경)
            logger.debug(f"Duplicate (DB): {item.get('title', '')[:30]}")
            raise DropItem(f"Duplicate (DB): {item.get('title', '')[:30]}")

        # 새로운 아이템 -> 메모리에 추가 (DB 저장은 후속 SupabasePipeline이 담당)
        self.new_items += 1
        self.seen_hashes.add(item_hash)
        return item

    def close_spider(self, spider=None):
        """종료 시 알림."""
        spider_obj = self._resolve_spider(spider)
        spider_name = spider_obj.name if spider_obj else "unknown"

        self._log_summary(spider_name)
        self._notify_no_new(spider_name)

    def _log_summary(self, spider_name):
        logger.info(
            f"[{spider_name}] Dedup summary (Supabase Sync)",
            total=self.total_items,
            new=self.new_items,
            duplicates=self.duplicate_items,
        )

    def _notify_no_new(self, spider_name):
        """신규 데이터가 없을 때 알림."""
        if not self._notify_on_no_new:
            return
        
        # 전체 아이템이 0개면(크롤링 실패 등) 알림 안 함
        if self.total_items == 0:
            return

        # 신규 데이터가 하나라도 있으면 알림 안 함 (DiscordNotifyPipeline이 개별 알림 보내므로)
        if self.new_items != 0:
            return
            
        # 중복만 100%일 때 알림
        if not self._webhook_url:
            return

        payload = {
            "content": (
                f"🕷️ **{spider_name}**: 신규 데이터 없음 (DB 중복 {self.duplicate_items}건 확인)."
            )
        }

        try:
            # 타임아웃 짧게 설정
            requests.post(
                self._webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=5
            )
            # logger.info(f"[{spider_name}] '신규 없음' 알림 전송 완료")
        except Exception:
            pass # 알림 실패는 조용히 넘어감

    def _resolve_spider(self, spider):
        if spider is not None:
            self._spider = spider
            return spider
        if self._spider is not None:
            return self._spider
        if self._crawler is not None:
            return getattr(self._crawler, "spider", None)
        return None
