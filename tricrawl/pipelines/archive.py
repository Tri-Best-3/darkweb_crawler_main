"""
전체 데이터 아카이브 파이프라인
- 필터링 여부와 관계없이 모든 크롤링 데이터를 저장
- 메모리 누수 방지를 위해 수집 즉시 파일에 기록(Stream Write)
- JSON Array 대신 JSON Lines(NDJSON) 포맷 사용해서 대용량 처리 유리하도록 함
"""
import json
import re
import structlog
from pathlib import Path
from datetime import datetime

logger = structlog.get_logger(__name__)


class ArchivePipeline:
    
    def __init__(self, data_dir: Path, keywords_config: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.file_handle = None  # 파일 핸들
        self._crawler = None
        self._spider = None
        
        # 키워드 설정 로드
        self.config = self._load_yaml(keywords_config)
        
        # 키워드 세트 로드(저장용 매칭)
        self.all_keywords = self._extract_keywords(self.config)
        
        # 연락처 패턴 로드(없으면 빈 딕셔너리)
        self.contact_patterns = self.config.get("patterns", {}).get("contacts", {})

    @classmethod
    def from_crawler(cls, crawler):
        data_dir = Path("data")
        keywords_config = crawler.settings.get("KEYWORDS_CONFIG")
        pipeline = cls(data_dir, keywords_config)
        pipeline._crawler = crawler
        return pipeline
        
    def open_spider(self, spider=None):
        # 스파이더 시작 시 전용 아카이브 파일 오픈
        spider_obj = self._resolve_spider(spider)
        spider_name = spider_obj.name if spider_obj else "unknown"
        filename = f"archive_{spider_name}.jsonl" # JSON Lines 포맷 권장 (.jsonl)
        self.archive_path = self.data_dir / filename
        
        try:
            # utf-8 인코딩으로 append 모드 열기. 버퍼링은 라인 단위(1)
            self.file_handle = open(self.archive_path, "a", encoding="utf-8", buffering=1)
            logger.info(f"[{spider_name}] 전용 아카이브 오픈 (Stream): {self.archive_path}")
        except Exception as e:
            logger.error(f"아카이브 파일 오픈 실패: {e}")
            self.file_handle = None

    def close_spider(self, spider=None):
        # 스파이더 종료 시 파일 닫기
        if self.file_handle:
            self.file_handle.close()
            spider_obj = self._resolve_spider(spider)
            spider_name = spider_obj.name if spider_obj else "unknown"
            logger.info(f"[{spider_name}] 아카이브 파일 닫음")

    def _load_yaml(self, path: Path) -> dict:
        try:
            import yaml
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"설정 로드 실패: {e}")
            return {}

    def _extract_keywords(self, config: dict) -> set:
        # 설정 딕셔너리에서 키워드 추출
        all_kw = set()
        for key, val in config.items():
            if key == "patterns": continue
            if isinstance(val, list):
                all_kw.update(kw.lower() for kw in val if isinstance(kw, str))
            elif isinstance(val, dict):
                all_kw.update(self._extract_keywords(val))
        return all_kw
    
    def _extract_contacts(self, text: str) -> dict:
        # 텍스트에서 연락처 정보 추출
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
        # 아이템 처리 및 즉시 저장
        if not self.file_handle:
            return item

        spider_obj = self._resolve_spider(spider)
        spider_name = spider_obj.name if spider_obj else "unknown"
            
        # 본문에서 연락처 추출
        content = item.get("content", "")
        author_contacts = self._extract_contacts(content)
        item["author_contacts"] = author_contacts # 다운스트림을 위해 아이템에 주입
        
        # 키워드 매칭
        text = f"{item.get('title', '')} {content}".lower()
        matched_keywords = [kw for kw in self.all_keywords if kw in text]
        
        # 정제된 아카이브 데이터
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
            # Dedup ID가 있다면 기록(디버깅용)
            "dedup_id": item.get("dedup_id")
        }
        
        try:
            # JSON Line 쓰기
            line = json.dumps(archive_entry, ensure_ascii=False)
            self.file_handle.write(line + "\n")
        except Exception as e:
            logger.error(f"아카이브 저장 실패: {e}", title=item.get("title"))
        
        return item

    def _resolve_spider(self, spider):
        # 스파이더 객체 안전 확보(Scrapy deprecation 대응)
        if spider is not None:
            self._spider = spider
            return spider
        if self._spider is not None:
            return self._spider
        if self._crawler is not None:
            return getattr(self._crawler, "spider", None)
        return None
