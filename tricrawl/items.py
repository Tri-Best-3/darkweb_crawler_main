"""
Data Contract (Items)
Defines the structure for crawled items.
"""
import scrapy


class LeakItem(scrapy.Item):
    """
    Common Data Item for all Spiders.

    Required Fields:
    - source, url, title, author, timestamp

    Process Fields (Injected by Pipelines):
    - matched_keywords, matched_targets, risk_level, dedup_id
    """

    # Required Fields
    source = scrapy.Field()  # e.g., "Abyss", "LockBit"
    url = scrapy.Field()     # Full URL
    title = scrapy.Field()
    author = scrapy.Field()
    timestamp = scrapy.Field() # ISO-8601 UTC
    views = scrapy.Field()

    # Optional/Content Fields
    content = scrapy.Field()
    category = scrapy.Field()
    site_type = scrapy.Field() # e.g., "Ransomware", "Forum"

    # Pipeline Injected Fields
    matched_keywords = scrapy.Field()
    matched_targets = scrapy.Field()
    author_contacts = scrapy.Field()
    risk_level = scrapy.Field()
    dedup_id = scrapy.Field()