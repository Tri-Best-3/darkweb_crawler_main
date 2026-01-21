"""
중복 게시물 필터링 파이프라인
이미 알림을 보낸 게시물은 다시 보내지 않음
"""
import json
import hashlib
import time
import requests
from collections import OrderedDict
from pathlib import Path
from scrapy.exceptions import DropItem
import structlog

logger = structlog.get_logger(__name__)


class DeduplicationPipeline:
    """
    제목 해시 기반 중복 필터링
    - JSON 캐시를 사용하되, 개수/기간 상한으로 무한 누적 방지
    - 오래된 항목은 순서 기준으로 제거(OrderedDict)
    """

    def __init__(self, data_dir: Path, max_entries: int, max_days: int):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 상한 설정(0 이하면 비활성)
        self.max_entries = max_entries
        self.max_days = max_days

        # 삽입 순서 유지(왼쪽이 가장 오래된 항목)
        self.seen_hashes = OrderedDict()
        self.cache_file = None

        # 스파이더/크롤러 참조(Scrapy deprecation 대응)
        self._crawler = None
        self._spider = None

        # 알림 설정(Webhook 미설정이면 알림 스킵)
        self._webhook_url = None
        self._notify_on_no_new = True

        # 실행 요약 카운터
        self.total_items = 0
        self.new_items = 0
        self.duplicate_items = 0

        # 실행 중 확인된 해시(중복 포함)
        self._seen_this_run = set()

        # 실행 중 보이지 않은 캐시 제거 옵션
        self._prune_unseen = False

    @classmethod
    def from_crawler(cls, crawler):
        # 프로젝트 루트의 data/ 폴더
        data_dir = Path("data")
        # MVP 단계 기본값(필요 시 settings.py에서 조정)
        max_entries = crawler.settings.getint("DEDUP_MAX_ENTRIES", 20000)
        max_days = crawler.settings.getint("DEDUP_MAX_DAYS", 30)

        pipeline = cls(data_dir, max_entries, max_days)
        pipeline._crawler = crawler
        pipeline._webhook_url = crawler.settings.get("DISCORD_WEBHOOK_URL")
        pipeline._notify_on_no_new = crawler.settings.getbool("NOTIFY_ON_NO_NEW_DATA", True)
        pipeline._prune_unseen = crawler.settings.getbool("DEDUP_PRUNE_UNSEEN", False)
        return pipeline

    def open_spider(self, spider=None):
        # 스파이더 시작 시 전용 중복 캐시 로드
        spider_obj = self._resolve_spider(spider)
        spider_name = spider_obj.name if spider_obj else "unknown"

        # 실행별 카운터 초기화
        self.total_items = 0
        self.new_items = 0
        self.duplicate_items = 0
        self._seen_this_run = set()

        self.cache_file = self.data_dir / f"dedup_{spider_name}.json"
        self.load_cache(spider_name)
        self._prune_cache()

    def get_hash(self, item):
        """
        게시물 고유 해시 생성
        1. item['dedup_id'] 존재 시 최우선 사용(스파이더 정의 유니크 키)
        2. 없을 경우 제목 + 작성자
        3. 스파이더에서 지정한 ID가 있으면 우선 사용
        """
        custom_id = item.get("dedup_id")
        if custom_id:
            return custom_id

        title = item.get("title", "")
        author = item.get("author", "")
        key = f"{title}|{author}"
        gen_hash = hashlib.md5(key.encode()).hexdigest()
        
        # 생성된 해시를 아이템에 기록(후속 파이프라인 참조용)
        item["dedup_id"] = gen_hash
        return gen_hash

    def process_item(self, item, spider=None):
        """중복 검사 후 통과 또는 드롭"""
        item_hash = self.get_hash(item)
        self.total_items += 1
        self._seen_this_run.add(item_hash)

        if self._hash_exists(item_hash):
            # 이미 본 게시물 -> 스킵
            self.duplicate_items += 1
            raise DropItem(f"Duplicate: {item.get('title', '')[:30]}")

        # 새 게시물 -> 캐시에 추가
        self.new_items += 1
        self._add_hash(item_hash)
        return item

    def close_spider(self, spider=None):
        # 스파이더 종료 시 캐시 저장 + 요약 로그/알림
        spider_obj = self._resolve_spider(spider)
        spider_name = spider_obj.name if spider_obj else "unknown"

        if self._prune_unseen and self._seen_this_run:
            self._prune_unseen_entries()

        self.save_cache(spider_name)
        self._log_summary(spider_name)
        self._notify_no_new(spider_name)

    def load_cache(self, spider_name):
        try:
            if self.cache_file and self.cache_file.exists():
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f) or {}

                now = time.time()

                # 해시 포맷: entries = [{"hash": "...", "ts": 1700000000}, ...]
                entries = data.get("entries")
                if isinstance(entries, list):
                    for entry in entries:
                        if not isinstance(entry, dict):
                            continue
                        entry_hash = entry.get("hash")
                        ts = entry.get("ts")
                        if entry_hash:
                            # ts 없으면 로드 시점으로 대체(기존 캐시 보존)
                            self.seen_hashes[str(entry_hash)] = float(ts) if ts else now
                else:
                    # 초기 단계 레거시 포맷: hashes = ["...", "..."], 추후 필요 없으면 제거
                    for entry_hash in data.get("hashes", []):
                        if entry_hash:
                            self.seen_hashes[str(entry_hash)] = now

                logger.info(
                    f"[{spider_name}] Dedup Cache loaded: {len(self.seen_hashes)} entries"
                )
        except Exception as e:
            logger.warning(f"Cache load failed: {e}")
            self.seen_hashes = OrderedDict()

    def save_cache(self, spider_name):
        # 캐시 파일에 해시 저장(JSON + 상한 유지)
        if not self.cache_file:
            return

        # 저장 직전에 상한을 다시 적용
        self._prune_cache()

        try:
            entries = [
                {"hash": entry_hash, "ts": int(ts)}
                for entry_hash, ts in self.seen_hashes.items()
            ]
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump({"version": 2, "entries": entries}, f, indent=2)
            logger.info(
                f"[{spider_name}] Dedup Cache saved",
                cache_total=len(self.seen_hashes),
                seen_this_run=len(self._seen_this_run),
            )
        except Exception as e:
            logger.warning(f"Cache save failed: {e}")

    def _hash_exists(self, item_hash: str) -> bool:
        return item_hash in self.seen_hashes

    def _add_hash(self, item_hash: str):
        # 삽입 시각 기록(순서 유지)
        self.seen_hashes[item_hash] = time.time()
        self._prune_cache()

    def _prune_cache(self):
        # 상한 조건에 따라 오래된 해시 제거
        if not self.seen_hashes:
            return

        now = time.time()

        # 기간 기준 정리
        if self.max_days and self.max_days > 0:
            cutoff = now - (self.max_days * 86400)
            while self.seen_hashes:
                _, ts = next(iter(self.seen_hashes.items()))
                if ts >= cutoff:
                    break
                self.seen_hashes.popitem(last=False)

        # 개수 기준 정리
        if self.max_entries and self.max_entries > 0:
            while len(self.seen_hashes) > self.max_entries:
                self.seen_hashes.popitem(last=False)

    def _prune_unseen_entries(self):
        # 이번 실행에서 보이지 않은 캐시를 제거
        for entry_hash in list(self.seen_hashes.keys()):
            if entry_hash not in self._seen_this_run:
                self.seen_hashes.pop(entry_hash, None)

    def _log_summary(self, spider_name):
        # 실행 요약을 로그에 남김
        logger.info(
            f"[{spider_name}] Dedup summary",
            total=self.total_items,
            new=self.new_items,
            duplicates=self.duplicate_items,
        )

    def _notify_no_new(self, spider_name):
        # 중복으로 인해 새 데이터가 없을 때 알림 전송
        if not self._notify_on_no_new:
            return

        # 실제 데이터가 하나도 없었던 경우는 제외
        if self.total_items == 0:
            return

        # 새 데이터가 없고, 중복만 발생했을 때만 알림
        if self.new_items != 0 or self.duplicate_items == 0:
            return

        if not self._webhook_url:
            logger.info(f"[{spider_name}] Webhook 미설정, 중복 알림 스킵")
            return

        payload = {
            "content": (
                f"🕷️ {spider_name}: 신규 데이터 없음 (중복 {self.duplicate_items}건)."
            )
        }

        try:
            response = requests.post(
                self._webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            if response.status_code in (200, 204):
                logger.info(f"[{spider_name}] 신규 데이터 없음 알림 전송")
            else:
                logger.warning(
                    f"[{spider_name}] 신규 데이터 없음 알림 실패",
                    status=response.status_code,
                )
        except Exception as e:
            logger.warning(f"[{spider_name}] 신규 데이터 없음 알림 에러: {e}")

    def _resolve_spider(self, spider):
        if spider is not None:
            self._spider = spider
            return spider
        if self._spider is not None:
            return self._spider
        if self._crawler is not None:
            return getattr(self._crawler, "spider", None)
        return None
