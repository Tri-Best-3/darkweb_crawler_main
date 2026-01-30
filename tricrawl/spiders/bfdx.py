import scrapy
import hashlib
from datetime import datetime, timezone
from tricrawl.items import LeakItem
import structlog

logger = structlog.get_logger(__name__)

class BfdxSiteSpider(scrapy.Spider):
    """
    BFDX 포럼 크롤러 (.onion 사이트)

    필수 필드:
    - source, title, url, author, timestamp
    - dedup_id는 title+content 기반으로 생성
    """

    name = "bfdx_site"
    start_urls = [
        "http://bfdxjkv5e2z3ilrifzbnvxxvhbzsj67akjpj3zc6smzr4vv6oz565gyd.onion/"
    ]

    custom_settings = {
        "ROBOTSTXT_OBEY": False,
        "DOWNLOAD_TIMEOUT": 120,
        "CONCURRENT_REQUESTS": 1,
        "DOWNLOADER_MIDDLEWARES": {
            "tricrawl.middlewares.darknet_requests.RequestsDownloaderMiddleware": 543,
            "tricrawl.middlewares.TorProxyMiddleware": None,
            "scrapy.downloadermiddlewares.httpproxy.HttpProxyMiddleware": None,
        }
    }

    def parse(self, response):
        logger.info(f"BFDX 메인 페이지 접근: {response.url}")

        # 포럼 목록 크롤링
        for forum in response.css("div.node.node--forum"):
            title = forum.css("a.node-extra-title::text").get()
            url = response.urljoin(forum.css("a.node-extra-title::attr(href)").get())
            author = forum.css("div.node-extra-row .username::text").get() or "Unknown"
            timestamp = forum.css("div.node-extra-row time::attr(datetime)").get()

            if not title or not url:
                continue

            # 상세 페이지 요청
            yield scrapy.Request(
                url,
                callback=self.parse_thread,
                meta={
                    "title": title.strip(),
                    "author": author,
                    "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
                }
            )

    def parse_thread(self, response):
        """상세 글 페이지에서 본문(content) 추출 + 작성자 보강 + 본문 정제"""
        title = response.meta["title"]
        author = response.meta["author"]
        timestamp = response.meta["timestamp"]

        # 상세 페이지에서 작성자 다시 추출 (있으면 덮어쓰기)
        page_author = response.css("span.username::text").get() or response.css("a.username::text").get()
        if page_author:
            author = page_author.strip()

        # 여러 선택자를 순차적으로 시도
        selectors = [
            "div.bbWrapper *::text",
            "div.message-body *::text",
            "div.node-extra-row *::text",
            "article.message *::text",
            "article *::text"
        ]

        content = []
        for sel in selectors:
            content = response.css(sel).getall()
            if content:
                break

        if not content:
            content = response.css("*::text").getall()

        # 본문 정제 규칙
        skip_patterns = ["*** Hidden text", "Click to expand", "said:"]
        clean_lines = []
        for c in content:
            line = c.strip()
            if not line:
                continue
            if any(p in line for p in skip_patterns):
                continue
            if len(line) < 3:  # 너무 짧은 단어 제거
                continue
            clean_lines.append(line)

        content_text = "\n".join(clean_lines)

        item = LeakItem()
        item["source"] = "BFDX Forum"
        item["title"] = title
        item["url"] = response.url
        item["author"] = author
        item["timestamp"] = timestamp

        dedup_key = f"{title}|{content_text}"
        item["dedup_id"] = hashlib.md5(dedup_key.encode()).hexdigest()
        item["content"] = content_text or "[본문 추출 실패]"

        yield item