"""
크롤링 아이템 정의
"""
import scrapy


class LeakItem(scrapy.Item):
    # 다크웹 유출 정보 아이템
    
    # 기본 정보
    source = scrapy.Field()          # 사이트 이름
    url = scrapy.Field()             # 원본 URL
    title = scrapy.Field()           # 제목
    content = scrapy.Field()         # 본문(일부)
    
    # 메타 정보
    author = scrapy.Field()
    timestamp = scrapy.Field()
    category = scrapy.Field()        # 게시판 카테고리 정보
    
    # 처리용 메타데이터
    matched_keywords = scrapy.Field()  # 매칭된 키워드
    matched_targets = scrapy.Field()   # 매칭된 타겟(기업명 등)
    author_contacts = scrapy.Field()   # 본문에서 추출된 연락처 정보
    risk_level = scrapy.Field()        # 위험도(HIGH/MEDIUM/LOW)
    dedup_id = scrapy.Field()          # 스파이더별 유니크 ID(중복 제거용)
