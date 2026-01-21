"""
Discord 알림 파이프라인
- 키워드 매칭된 아이템들 Discord 웹훅으로 전송(비동기 처리)
"""
import time
import requests
import structlog
from datetime import datetime, timezone, timedelta
from twisted.internet import defer
from twisted.internet.threads import deferToThread

logger = structlog.get_logger(__name__)

# 위험도별 색상
RISK_COLORS = {
    "HIGH": 0xe74c3c,    # 빨강
    "MEDIUM": 0xf39c12,  # 주황
    "LOW": 0x2ecc71,     # 초록
}

# KST
KST = timezone(timedelta(hours=9))


class DiscordNotifyPipeline:
    # Discord 웹훅 알림
    
    def __init__(self, webhook_url: str, stats=None):
        self.webhook_url = webhook_url
        self._pending = set()
        self._stats = stats
        
    @classmethod
    def from_crawler(cls, crawler):
        webhook_url = crawler.settings.get("DISCORD_WEBHOOK_URL")
        if not webhook_url:
            logger.warning("DISCORD_WEBHOOK_URL 미설정, 알림 비활성화")
            return cls(None, crawler.stats)
        return cls(webhook_url, crawler.stats)

    def open_spider(self, spider=None):
        if self._stats:
            # 항상 로그에 남도록 기본값 설정
            self._stats.set_value("discord_notify/sent", 0)
    
    def process_item(self, item, spider=None):
        # Discord로 알림 전송(비동기)
        if not self.webhook_url:
            return item
        
        # deferToThread를 사용하여 메인 스레드 차단 방지
        d = deferToThread(self._send_discord_webhook, item)
        self._pending.add(d)
        d.addBoth(self._discard_pending, d)
        return item

    def close_spider(self, spider=None):
        if not self._pending:
            return None
        return defer.DeferredList(list(self._pending), consumeErrors=True)

    def _discard_pending(self, result, deferred_obj):
        self._pending.discard(deferred_obj)
        return result

    def _send_discord_webhook(self, item):
        # 실제 전송 로직(Thread 실행)
        payload = self._build_embed(item)
        max_attempts = 3
        backoff = 1

        for attempt in range(1, max_attempts + 1):
            try:
                response = requests.post(
                    self.webhook_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=10
                )
            except Exception as e:
                if attempt >= max_attempts:
                    logger.error("Discord 알림 에러", error=str(e))
                    return
                time.sleep(backoff)
                backoff *= 2
                continue

            if response.status_code == 204:
                logger.info("Discord 알림 전송 성공", title=item.get("title", "")[:30])
                if self._stats:
                    self._stats.inc_value("discord_notify/sent")
                return

            if response.status_code == 429:
                retry_after = self._get_retry_after(response)
                time.sleep(retry_after)
                continue

            if 500 <= response.status_code < 600 and attempt < max_attempts:
                time.sleep(backoff)
                backoff *= 2
                continue

            logger.warning("Discord 알림 실패", status=response.status_code)
            return

    def _get_retry_after(self, response) -> float:
        try:
            # 1. 헤더 확인 (우선순위)
            header_val = response.headers.get("Retry-After")
            if header_val:
                return float(header_val)
            
            # 2. 바디 확인 (JSON)
            data = response.json()
            retry_after = float(data.get("retry_after", 1))
            return max(retry_after, 0.5)
        except Exception:
            return 1

    def _convert_to_kst(self, timestamp_str: str) -> str:
        # UTC/ISO 문자열을 KST로 변환
        if not timestamp_str or timestamp_str == "Unknown":
            return "Unknown"
        
        try:
            # ISO 파싱(예: 2023-10-10T12:00:00 or with Z)
            dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            
            # KST로 변환
            if dt.tzinfo is None:
                # Naive time -> Assume UTC logic or just add 9h? 
                # 스파이더는 UTC 기준 저장 권장, 따라서 UTC로 가정 후 변환
                dt = dt.replace(tzinfo=timezone.utc)
            
            dt_kst = dt.astimezone(KST)
            return dt_kst.strftime("%Y-%m-%d %H:%M:%S (KST)")
            
        except Exception:
            return timestamp_str  # 변환 실패 시 원본 반환

    def _build_embed(self, item) -> dict:
        # Discord Embed 메시지 생성
        keywords = item.get("matched_keywords", [])
        risk_level = item.get("risk_level", "HIGH")
        
        # Color & Emoji
        if risk_level == "CRITICAL":
            color = 0xff0000 # Red
            risk_emoji = "🔴"
        elif risk_level == "HIGH":
            color = 0xe74c3c # High Risk Red/Orange
            risk_emoji = "🟠"
        elif risk_level == "MEDIUM":
            color = 0xf39c12 # Medium Yellow/Orange
            risk_emoji = "🟡"
        else:
            color = 0x2ecc71 # Low/Medium Green
            risk_emoji = "🟢"
        
        # URL Logic
        url = item.get("url", "")
        
        # Content Preview Cleanup
        raw_content = item.get("content", "")
        lines = [line.strip() for line in raw_content.splitlines() if line.strip()]
        clean_content = "\n".join(lines)[:800] 
        if len(clean_content) >= 800:
            clean_content += "..."
        if not clean_content:
            clean_content = "(내용 없음)"

        matched_targets = item.get("matched_targets", [])
        if isinstance(matched_targets, str):
            matched_targets = [matched_targets]
        elif not isinstance(matched_targets, list):
            matched_targets = list(matched_targets) if matched_targets else []

        matched_keywords_value = ", ".join(keywords) if keywords else "(없음)"
        targets_value = ", ".join(matched_targets) if matched_targets else "(없음)"
        risk_line = f"{risk_emoji} Risk: {risk_level}"

        # Fields Construction(간결하게)
        fields = [
            {
                "name": "🔑 Matched Keywords",
                "value": f"{risk_line}\n{matched_keywords_value}",
                "inline": True
            },
            {
                "name": "🎯 Targets",
                "value": targets_value,
                "inline": True
            },
            {
                "name": "🔗 Source",
                "value": f"`{url}`",
                "inline": False
            }
        ]

        # Date & Category & Target in description
        # KST 변환 적용
        raw_time = item.get('timestamp', 'Unknown')
        kst_time = self._convert_to_kst(raw_time)
        
        category = item.get('category', 'Generic') 
        source_name = item.get('source', 'Unknown')

        description_parts = [f"🎯 **Target**: {source_name}"]
        description_parts.append(f"📅 **Date**: {kst_time}")
        if category and category != "Unknown":
             description_parts.append(f"📂 **Category**: {category}")
        
        description_text = "\n".join(description_parts) + f"\n\n```{clean_content}```"

        return {
            "embeds": [
                {
                    "title": f"🚨 {item.get('title', 'No Title')}",
                    "description": description_text,
                    "color": color,
                    "fields": fields,
                    "image": {
                        "url": "https://dummyimage.com/650x1/2b2d31/2b2d31.png"
                    },
                    "footer": {
                        "text": f"TriCrawl • {item.get('source', 'Unknown')}"
                    },
                    "timestamp": datetime.now(timezone.utc).isoformat() # Embed 전송 시각
                }
            ]
        }
