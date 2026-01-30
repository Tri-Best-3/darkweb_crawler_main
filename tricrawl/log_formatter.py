"""
커스텀 Scrapy 로그 포매터

Scrapy 기본 동작 중 DropItem 발생 시 item 전체를 출력하는 동작을 억제함.
콘솔 UI(Rich Progress Bar)와 충돌하는 장황한 item dict 출력을 제거.
"""
import logging
from scrapy.logformatter import LogFormatter
from scrapy import Item


class QuietLogFormatter(LogFormatter):
    """DropItem 시 item 내용을 출력하지 않는 LogFormatter."""

    def dropped(self, item, exception, response, spider):
        """
        기본 LogFormatter는 item 전체를 pformat으로 출력함.
        여기서는 간단한 메시지만 반환하여 콘솔 노이즈 제거.
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
        기본 LogFormatter는 scraped item도 DEBUG로 전체 출력함.
        여기서는 간단한 메시지만 반환.
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
