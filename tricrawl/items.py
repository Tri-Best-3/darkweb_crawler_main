"""
크롤링 아이템 정의 (Data Contract)

팀원에게 중요:
- 모든 스파이더는 최소 필수 필드 5개를 채워야 합니다.
  source, title, url, author, timestamp
- timestamp는 가능하면 UTC ISO-8601 문자열로 넣어주세요.
  예: datetime.now(timezone.utc).isoformat()
- content가 없으면 빈 문자열("")로 채워주세요.
- 아래 확장 필드는 파이프라인에서 채워지므로 spider에서 미리 비워둬도 됩니다.
  matched_keywords, matched_targets, author_contacts, risk_level, dedup_id
"""
import scrapy


class LeakItem(scrapy.Item):
    """
    LeakItem: 스파이더 → 파이프라인까지 이어지는 공용 데이터 구조.

    기본 규칙:
    - "필수" 필드는 spider에서 반드시 채웁니다.
    - 파이프라인이 참조하는 필드는 타입을 지켜야 합니다.

    Data lineage (대표 예시):
    - source/title/url/author/timestamp/site_type/category:
      `tricrawl/spiders/abyss.py:AbyssSpider.parse_data_js`,
      `tricrawl/spiders/darknet_army.py:DarkNetArmySpider.parse_post`
    - dedup_id:
      `tricrawl/spiders/abyss.py:AbyssSpider.parse_data_js`에서 생성,
      없으면 `tricrawl/pipelines/dedup.py:DeduplicationPipeline.get_hash`에서 생성
    - matched_keywords/matched_targets/risk_level:
      `tricrawl/pipelines/keyword_filter.py:KeywordFilterPipeline.process_item`
    - author_contacts:
      `tricrawl/pipelines/archive.py:ArchivePipeline.process_item`
    """

    # 필수 필드(Spider에서 반드시 채움)
    source = scrapy.Field()  # 사이트/그룹 이름 (예: "Abyss Ransomware")
    url = scrapy.Field()     # 원본 URL (onion 포함)
    title = scrapy.Field()   # 게시글/유출 제목
    author = scrapy.Field()  # 작성자/작성 그룹 (dedup에 사용)
    timestamp = scrapy.Field()  # ISO-8601 문자열 권장(UTC)
    views = scrapy.Field()      # 조회수 (정수 또는 문자열)

    # 권장 필드(없으면 빈 값으로 보정 권장)
    content = scrapy.Field()   # 본문(요약 가능)
    category = scrapy.Field()  # 게시판/분류명 (예: "Leaked Databases")
    site_type = scrapy.Field() # 사이트 유형 (예: "Ransomware", "Forum")

    # 파이프라인이 채우거나 참조하는 필드
    matched_keywords = scrapy.Field()  # 조건부 키워드 매칭 결과(list[str])
    matched_targets = scrapy.Field()   # 타겟 키워드 매칭 결과(list[str])
    author_contacts = scrapy.Field()   # 본문에서 추출된 연락처(dict)
    risk_level = scrapy.Field()        # 위험도(CRITICAL/HIGH/MEDIUM/LOW)
    dedup_id = scrapy.Field()          # 스파이더 전용 유니크 ID(있으면 우선 사용)