"""
키워드 필터링 파이프라인
설정된 키워드와 매칭되는 아이템만 통과

[조건부 키워드]
- 'combolist'는 targets 카테고리 키워드와 함께 있어야 알림 발송
- 단독 'combolist' 매칭은 무시 (Combolists 게시판 스팸 방지)
"""
import re
import yaml
import structlog
from pathlib import Path
from scrapy.exceptions import DropItem

logger = structlog.get_logger(__name__)


class KeywordFilterPipeline:
    # 키워드 기반 필터링

    def __init__(self, keywords_config: Path):
        self.config = self._load_keywords(keywords_config)
        self.keywords = self.config

        rules = self.config.get("rules", {})
        self.require_target = bool(rules.get("require_target", True))
        self.high_risk_keywords = set(kw.lower() for kw in self.keywords.get("critical_keywords", []))

        # 조건부 키워드 로드(config > patterns > conditional)
        patterns = self.config.get("patterns", {})
        conditional_raw = patterns.get("conditional", [])
        self.conditional_keywords = [k.lower() for k in conditional_raw if isinstance(k, str)]
        self.conditional_patterns = self._compile_keyword_patterns(self.conditional_keywords)

        # 타겟 키워드(기업명, 국가 등)
        target_list = self.keywords.get("targets", [])
        self.target_keywords = [kw.lower() for kw in target_list if isinstance(kw, str)]
        self.target_patterns = self._compile_keyword_patterns(self.target_keywords)

    def _load_keywords(self, keywords_config: Path) -> dict:
        if not keywords_config:
            logger.warning("KEYWORDS_CONFIG 미설정, 키워드 필터 비활성")
            return {}

        try:
            with open(keywords_config, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"키워드 설정 로드 실패: {e}")
            return {}

    def _keyword_pattern(self, keyword: str) -> re.Pattern:
        escaped = re.escape(keyword)
        pattern = rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])"
        return re.compile(pattern)

    def _compile_keyword_patterns(self, keywords) -> dict:
        patterns = {}
        for keyword in keywords:
            if not isinstance(keyword, str):
                continue
            key = keyword.strip().lower()
            if not key:
                continue
            if key not in patterns:
                patterns[key] = self._keyword_pattern(key)
        return patterns

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text).lower()

    @classmethod
    def from_crawler(cls, crawler):
        keywords_config = crawler.settings.get("KEYWORDS_CONFIG")
        return cls(keywords_config)
    
    def process_item(self, item, spider=None):
        # 아이템 필터링
        # 제목 + 본문에서 키워드 검색
        text = self._normalize_text(f"{item.get('title', '')} {item.get('content', '')}")

        matched = []
        for keyword, pattern in self.conditional_patterns.items():
            if pattern.search(text):
                matched.append(keyword)

        # 타겟 키워드 매칭 확인
        target_matched = [
            keyword for keyword, pattern in self.target_patterns.items() if pattern.search(text)
        ]

        # require_target 옵션이 켜져있는데 타겟 매칭이 없으면 드롭
        # (단, 조건부 키워드가 있더라도 타겟이 없으면 드롭됨 - 설정에 따름)
        if self.require_target and not target_matched:
            raise DropItem(f"타겟 키워드 미매칭: {item.get('title', '')[:30]}")

        # 조건부와 타겟 둘 다 없으면 드롭
        if not matched and not target_matched:
            raise DropItem(f"키워드 매칭 없음: {item.get('title', '')[:30]}")

        item["matched_keywords"] = matched
        if target_matched:
            item["matched_targets"] = target_matched

        high_risk_matches = [kw for kw in matched if kw in self.high_risk_keywords]
        
        if target_matched:
            # 타겟(기업명) 매칭 시 최상위 위험도
            item["risk_level"] = "CRITICAL"
        elif high_risk_matches:
            item["risk_level"] = "CRITICAL"
        elif len(matched) >= 3:
            item["risk_level"] = "HIGH"
        elif len(matched) >= 2:
            item["risk_level"] = "MEDIUM"
        else:
            item["risk_level"] = "LOW"

        logger.info(
            "키워드 매칭",
            title=item.get("title", "")[:30],
            keywords=matched,
            risk=item["risk_level"],
            targets=target_matched,
        )

        return item
