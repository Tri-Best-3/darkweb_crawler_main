"""
Keyword Filter Pipeline
Filters items based on configured keywords and assigns Risk Levels.
"""
import re
import yaml
import structlog
from pathlib import Path
from scrapy.exceptions import DropItem

logger = structlog.get_logger(__name__)


class KeywordFilterPipeline:
    """
    Keyword-based Filtering.
    - Assigns Risk Level (CRITICAL/HIGH/MEDIUM/LOW).
    - Checks for 'targets' (always CRITICAL).
    """

    def __init__(self, keywords_config: Path):
        self.config = self._load_keywords(keywords_config)
        self.keywords = self.config

        rules = self.config.get("rules", {})
        self.require_target = bool(rules.get("require_target", True))
        self.high_risk_keywords = set(kw.lower() for kw in self.keywords.get("critical_keywords", []))

        # Conditional Keywords
        patterns = self.config.get("patterns", {})
        conditional_raw = patterns.get("conditional", [])
        self.conditional_keywords = [k.lower() for k in conditional_raw if isinstance(k, str)]
        self.conditional_patterns = self._compile_keyword_patterns(self.conditional_keywords)

        # Target Keywords
        target_list = self.keywords.get("targets", [])
        self.target_keywords = [kw.lower() for kw in target_list if isinstance(kw, str)]
        self.target_patterns = self._compile_keyword_patterns(self.target_keywords)

    def _load_keywords(self, keywords_config: Path) -> dict:
        if not keywords_config:
            logger.warning("KEYWORDS_CONFIG missing. Filter inactive.")
            return {}

        try:
            with open(keywords_config, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"Failed to load keywords config: {e}")
            return {}

    def _keyword_pattern(self, keyword: str) -> re.Pattern:
        """Create regex for whole-word matching."""
        escaped = re.escape(keyword)
        pattern = rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])"
        return re.compile(pattern)

    def _compile_keyword_patterns(self, keywords) -> dict:
        patterns = {}
        for keyword in keywords:
            if not isinstance(keyword, str): continue
            key = keyword.strip().lower()
            if not key: continue
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
        text = self._normalize_text(f"{item.get('title', '')} {item.get('content', '')}")

        matched = []
        for keyword, pattern in self.conditional_patterns.items():
            if pattern.search(text):
                matched.append(keyword)

        target_matched = [
            keyword for keyword, pattern in self.target_patterns.items() if pattern.search(text)
        ]

        item["matched_keywords"] = matched
        if target_matched:
            item["matched_targets"] = target_matched

        high_risk_matches = [kw for kw in matched if kw in self.high_risk_keywords]
        
        # Risk Level Calculation
        if self.require_target and not target_matched:
            item["risk_level"] = "NONE"
        else:
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

        if item["risk_level"] != "NONE":
            logger.info(
                "Keyword Match",
                title=item.get("title", "")[:30],
                risk=item["risk_level"],
                targets=target_matched,
            )
        else:
            logger.debug("No Keyword Match", title=item.get("title", "")[:30])

        return item
