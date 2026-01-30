"""
Discord 알림 파이프라인
- Queue와 Thread를 사용해 순차적으로, 천천히 전송 (Rate Limit 회피)
"""
import time
import requests
import structlog
import threading
import queue
from datetime import datetime, timezone, timedelta

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
    """
    Discord 웹훅 알림 파이프라인 (Rate Limit Safe Version).
    
    구조:
    - process_item: 큐에 아이템 적재 (Non-blocking)
    - Worker Thread: 큐에서 하나씩 꺼내 전송 후 2초 대기 (Throttling)
    
    이점:
    - 429 에러를 사전에 방지 (Token Bucket 스타일)
    - 메인 크롤링 속도에 영향 주지 않음
    """
    
    def __init__(self, webhook_url: str, stats=None):
        self.webhook_url = webhook_url
        self._stats = stats
        
        # 전송 큐 및 워커 스레드 관리
        self.queue = queue.Queue()
        self.worker_thread = None
        self.interval = 1.0  # 메시지 간 안전 간격 (초)
        
    @classmethod
    def from_crawler(cls, crawler):
        webhook_url = crawler.settings.get("DISCORD_WEBHOOK_URL")
        if not webhook_url:
            logger.warning("DISCORD_WEBHOOK_URL 미설정, 알림 비활성화")
            # URL이 없어도 파이프라인은 생성되나 기능은 동작 안 함
            return cls(None, crawler.stats)
        return cls(webhook_url, crawler.stats)

    def open_spider(self, spider=None):
        """스파이더 시작 시 워커 스레드 가동."""
        if self.webhook_url:
            self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self.worker_thread.start()
            logger.info("Discord 알림 워커 시작 (Interval: 2.0s)")

        if self._stats:
            self._stats.set_value("discord_notify/sent", 0)
    
    def process_item(self, item, spider=None):
        """아이템을 큐에 넣고 즉시 반환."""
        # NONE 등급은 알림 발송 제외 (Archive Only)
        if item.get("risk_level") == "NONE":
            return item
            
        if self.webhook_url:
            self.queue.put(item)
        return item

    def close_spider(self, spider=None):
        """남은 큐를 모두 처리하고 종료."""
        if self.worker_thread and self.worker_thread.is_alive():
            # 종료 시그널(None) 전송
            self.queue.put(None)
            
            # 남은 알림이 많으면 시간이 걸릴 수 있음을 알림
            q_size = self.queue.qsize()
            if q_size > 0:
                logger.info(f"남은 알림 {q_size}개 전송 대기 중... (예상 소요: {q_size * self.interval}초)")
            
            # 스레드 종료 대기
            self.worker_thread.join()
            logger.info("Discord 알림 워커 종료")

    def _worker_loop(self):
        """백그라운드에서 큐를 소비하며 알림 전송."""
        while True:
            item = self.queue.get()
            
            # 종료 시그널
            if item is None:
                self.queue.task_done()
                break
            
            try:
                self._send_discord_webhook(item)
            except Exception as e:
                logger.error(f"알림 전송 중 예외 발생: {e}")
            finally:
                self.queue.task_done()
                
            # Rate Limit 방지를 위한 강제 휴식
            time.sleep(self.interval)

    def _send_discord_webhook(self, item):
        """단일 메시지 전송 로직 (Retry 로직 포함)."""
        payload = self._build_embed(item)
        max_attempts = 3
        backoff = 1

        for attempt in range(max_attempts):
            try:
                response = requests.post(
                    self.webhook_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=10
                )
            except Exception as e:
                logger.warning(f"전송 에러(Attempt {attempt+1}): {e}")
                time.sleep(backoff)
                backoff *= 2
                continue

            if response.status_code == 204:
                logger.info(f"Discord 전송 완료: {item.get('title', '')[:20]}")
                if self._stats:
                    self._stats.inc_value("discord_notify/sent")
                return
            
            if response.status_code == 429:
                retry_after = self._get_retry_after(response)
                logger.warning(f"Rate Limit 429! Sleeping {retry_after}s")
                time.sleep(retry_after)
                # 429는 횟수 차감 없이 재시도하려면 continue 전에 attempt 조작 필요하지만,
                # 현재 구조(2초 텀)에서는 429가 거의 안 뜸. 
                # 만약 뜨면 재시도 로직을 타거나, 아예 429 전용 루프를 넣어도 됨.
                # 여기서는 2초 텀이 있으므로 단순 재시도로 충분함.
                continue

            # 기타 서버 에러
            if 500 <= response.status_code < 600:
                time.sleep(backoff)
                backoff *= 2
                continue

            # 4xx 에러 등 복구 불가능
            logger.error(f"전송 실패 (Status {response.status_code})")
            return

    def _get_retry_after(self, response) -> float:
        try:
            val = response.headers.get("Retry-After")
            if val: return float(val)
            return response.json().get("retry_after", 1.0)
        except:
            return 1.0

    def _convert_to_kst(self, timestamp_str: str) -> str:
        if not timestamp_str or timestamp_str == "Unknown":
            return "Unknown"
        try:
            dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dt_kst = dt + timedelta(hours=9)
            return dt_kst.strftime("%Y-%m-%d %H:%M:%S (KST)")
        except:
            return timestamp_str

    def _build_embed(self, item) -> dict:
        # 기존 로직과 동일
        keywords = item.get("matched_keywords", [])
        risk_level = item.get("risk_level", "HIGH")
        
        if risk_level == "CRITICAL":
            color = 0xff0000; risk_emoji = "🔴"
        elif risk_level == "HIGH":
            color = 0xe74c3c; risk_emoji = "🟠"
        elif risk_level == "MEDIUM":
            color = 0xf39c12; risk_emoji = "🟡"
        else:
            color = 0x2ecc71; risk_emoji = "🟢"
        
        url = item.get("url", "")
        raw_content = item.get("content", "")
        lines = [line.strip() for line in raw_content.splitlines() if line.strip()]
        clean_content = "\n".join(lines)[:800] 
        if len(clean_content) >= 800: clean_content += "..."
        if not clean_content: clean_content = "(내용 없음)"

        matched_targets = item.get("matched_targets", [])
        if isinstance(matched_targets, str): matched_targets = [matched_targets]
        elif not isinstance(matched_targets, list): matched_targets = list(matched_targets) if matched_targets else []

        matched_keywords_val = ", ".join(keywords) if keywords else "(없음)"
        targets_val = ", ".join(matched_targets) if matched_targets else "(없음)"
        
        description = (
            f"🎯 **Target**: {item.get('source', 'Unknown')}\n"
            f"📅 **Date**: {self._convert_to_kst(item.get('timestamp'))}\n"
            f"🏷️ **Type**: {item.get('site_type', 'Unknown')} / {item.get('category', 'Generic')}\n\n"
            f"```{clean_content}```"
        )

        return {
            "embeds": [{
                "title": f"🚨 {item.get('title', 'No Title')}",
                "description": description,
                "color": color,
                "fields": [
                    {"name": "🔑 Keywords", "value": f"{risk_emoji} {risk_level}\n{matched_keywords_val}", "inline": True},
                    {"name": "🎯 Targets", "value": targets_val, "inline": True},
                    {"name": "🔗 Source", "value": f"`{url}`", "inline": False}
                ],
                "footer": {"text": "TriCrawl"},
                "timestamp": datetime.now(timezone.utc).isoformat()
            }]
        }
