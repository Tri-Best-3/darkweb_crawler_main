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
    """
    키워드 기반 필터링 파이프라인.

    핵심 규칙:
    - targets 매칭 시 통과 + CRITICAL
    - conditional 키워드는 targets와 함께 있을 때만 유효
    - matched_keywords에는 conditional만 기록, matched_targets에는 targets만 기록
    """

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
        """키워드 설정 파일을 로드한다 (실패 시 빈 설정)."""
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
        """단어 경계를 고려한 정규식을 만든다 (영숫자 경계 보호)."""
        escaped = re.escape(keyword)
        pattern = rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])"
        return re.compile(pattern)

    def _compile_keyword_patterns(self, keywords) -> dict:
        """키워드 리스트를 정규식 패턴 딕셔너리로 컴파일."""
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
        """공백 정규화 + 소문자화."""
        return re.sub(r"\s+", " ", text).lower()

    @classmethod
    def from_crawler(cls, crawler):
        """Scrapy settings에서 KEYWORDS_CONFIG 경로를 받아 생성."""
        keywords_config = crawler.settings.get("KEYWORDS_CONFIG")
        return cls(keywords_config)
    
    def process_item(self, item, spider=None):
        """
        아이템 필터링 및 위험도 산정.

        주의:
        - item["matched_keywords"], item["matched_targets"], item["risk_level"]을 여기서 채움
        - 다음 파이프라인(Discord)에서 이 값을 사용함:
          `tricrawl/pipelines/discord_notify.py:DiscordNotifyPipeline._build_embed`
        - 키워드 설정 출처:
          `config/keywords.yaml` (targets/critical/conditional)
        """
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

        # require_target 옵션이 켜져있는데 타겟 매칭이 없으면 드롭하지 않고 NONE 태그
        # (기존: DropItem -> 변경: risk_level="NONE")
        
        item["matched_keywords"] = matched
        if target_matched:
            item["matched_targets"] = target_matched

        high_risk_matches = [kw for kw in matched if kw in self.high_risk_keywords]
        
        # Risk Level 산정
        if self.require_target and not target_matched:
            # require_target=True인데 타겟이 없으면 -> 알림 발송 X (Archive Only)
            # 조건부 키워드가 아무리 많아도 타겟 연관성 없으면 무시
            item["risk_level"] = "NONE"
        else:
            # 타겟이 있거나, require_target=False인 경우 -> 키워드 기반 위험도 산정
            if target_matched:
                item["risk_level"] = "CRITICAL"
            elif high_risk_matches:
                item["risk_level"] = "CRITICAL"
            elif len(matched) >= 3:
                item["risk_level"] = "HIGH"
            elif len(matched) >= 2:
                item["risk_level"] = "MEDIUM"
            elif len(matched) == 1:
                item["risk_level"] = "LOW"
            else:
                item["risk_level"] = "NONE"

        # 로깅 (매칭된 경우만 INFO, 아니면 DEBUG)
        if item["risk_level"] != "NONE":
            logger.info(
                "키워드 매칭",
                title=item.get("title", "")[:30],
                keywords=matched,
                risk=item["risk_level"],
                targets=target_matched,
            )
        else:
            logger.debug("키워드 미매칭 (Archive Only)", title=item.get("title", "")[:30])

        return item
