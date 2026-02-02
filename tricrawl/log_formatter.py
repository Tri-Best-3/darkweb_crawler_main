"""
Custom Scrapy Log Formatter
Suppress verbose item dumps on DropItem events to avoid console noise with Rich.
"""
import logging
from scrapy.logformatter import LogFormatter
from scrapy import Item


class QuietLogFormatter(LogFormatter):
    """DropItem 시 item 내용을 출력하지 않는 LogFormatter."""

    def dropped(self, item, exception, response, spider):
        """
        Suppresses full item dump on drop.
        Returns a simple message to reduce console noise.
        """
        return {
            "level": logging.DEBUG,  # 정수 타입 필수
            "msg": "Dropped: %(exception)s",
            "args": {
                "exception": exception,
            }
        }

    def scraped(self, item, response, spider):
        """
        Suppresses full item dump on scrape.
        Returns a simple message.
        """
        if isinstance(item, Item):
            title = item.get("title", "")[:30] if hasattr(item, "get") else str(item)[:30]
        else:
            title = str(item)[:30]
            
        return {
            "level": logging.DEBUG,  # 정수 타입 필수
            "msg": "Scraped: %(title)s",
            "args": {
                "title": title,
            }
        }
