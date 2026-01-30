# TriCrawl 개발자 가이드

이 문서는 TriCrawl에 새 스파이더(크롤러)나 파이프라인을 추가할 때 따라야 하는 가이드입니다.

---

## 1. 시작하기

### 1.1 필수 준비

- Python 3.10+
- Docker Desktop(Tor 프록시 사용)
- `.env` 파일에 `DISCORD_WEBHOOK_URL` 설정

### 1.2 프로젝트 구조

```
00_tricrawl/
├── main.py
├── tricrawl/
│   ├── spiders/            # 스파이더
│   ├── pipelines/          # 파이프라인
│   ├── middlewares/        # Tor/Requests 미들웨어
│   ├── items.py            # 아이템 스키마
│   ├── settings.py         # Scrapy 설정
│   └── rich_progress.py    # UI/UX 확장 (신규)
├── config/
│   ├── crawler_config.yaml # 스파이더별 설정
│   └── keywords.yaml       # 키워드 정책
├── data/                   # archive_*, dedup_* 출력
└── docs/
```

---

## 2. 데이터 흐름 이해

```
Spider (Pre-Dedup) → ArchivePipeline(Legacy) → DeduplicationPipeline → KeywordFilterPipeline → SupabasePipeline(+Contacts) → DiscordNotifyPipeline
```

- Pre-Dedup: 스파이더 레벨에서 중복 ID 사전 체크 (요청 스킵)
- Dedup: 파이프라인 레벨 중복 체크
- Filter: 타겟 매칭 시 CRITICAL
- Supabase: DB 저장 및 **연락처 자동 추출** (`author_contacts`)
- Notify: Discord Embed 전송

---

## 3. 새로운 스파이더 추가

### 3.1 파일 생성

`tricrawl/spiders/`에 새 파일을 만듭니다. 예: `new_site.py`

### 3.2 기본 템플릿

```python
import scrapy
from datetime import datetime, timezone
from tricrawl.items import LeakItem

class NewSiteSpider(scrapy.Spider):
    name = "new_site"
    start_urls = ["http://example.onion/"]

    def parse(self, response):
            item = LeakItem()
            item["source"] = "NewSite"
            # ... 필드 설정 ...
            
            # [Pre-Request Dedup] 상세 요청 전 중복 체크
            if hasattr(self, 'seen_ids') and dedup_id in self.seen_ids:
                continue

            yield item
```

### 3.3 필수 필드 체크

- 필수 필드는 `development_standard.md` 기준을 따릅니다.
- 누락 시 파이프라인에서 오류가 납니다.

### 3.4 .onion 미들웨어 적용

`.onion` 사이트는 `RequestsDownloaderMiddleware`를 사용합니다.

```python
custom_settings = {
    "DOWNLOADER_MIDDLEWARES": {
        "tricrawl.middlewares.darknet_requests.RequestsDownloaderMiddleware": 900,
        "tricrawl.middlewares.TorProxyMiddleware": None,
        "scrapy.downloadermiddlewares.httpproxy.HttpProxyMiddleware": None,
    }
}
```

### 3.5 설정 파일 추가

`config/crawler_config.yaml`에 스파이더 섹션을 추가합니다.

```yaml
spiders:
  new_site:
    boards:
      "example-board": 3
```

### 3.6 로컬 테스트

```bash
python -m scrapy crawl new_site -s CLOSESPIDER_PAGECOUNT=1
```

체크 포인트:
- `data/archive_new_site.jsonl` 생성
- `data/dedup_new_site.json` 생성
- `tricrawl/logs/last_run.log`에 에러 없음

---

## 4. 새로운 파이프라인 추가

### 4.1 파일 생성

`tricrawl/pipelines/`에 새 파일을 만듭니다. 예: `spam_filter.py`

```python
from scrapy.exceptions import DropItem

class SpamFilterPipeline:
    def process_item(self, item, spider):
        if "spam" in item.get("title", "").lower():
            raise DropItem("Spam detected")
        return item
```

### 4.2 settings.py 등록

```python
ITEM_PIPELINES = {
    "tricrawl.pipelines.ArchivePipeline": 10,
    "tricrawl.pipelines.DeduplicationPipeline": 50,
    "tricrawl.pipelines.KeywordFilterPipeline": 100,
    "tricrawl.pipelines.spam_filter.SpamFilterPipeline": 150,
    "tricrawl.pipelines.DiscordNotifyPipeline": 300,
}
```

### 4.3 __init__.py 등록 (선택)

`tricrawl/pipelines/__init__.py`에서 내보낼 클래스를 추가합니다.

### 4.4 items.py 업데이트

- 새 필드를 추가하면 `tricrawl/items.py`에 정의합니다.
- 필수 필드 여부는 `items.py`의 주석이나 `LeakItem` 클래스 정의를 따릅니다.

---

## 5. 키워드 정책 수정

`config/keywords.yaml`만 수정하면 코드 변경 없이 즉시 반영됩니다.

- `targets`: 타겟 키워드 (단독 매칭 시 CRITICAL)
- `patterns.conditional`: 조건부 키워드 (단독 매칭 가능)
- `critical_keywords`: 매칭 시 CRITICAL 고정

---

## 6. 로그와 디버깅

- 로그 파일: `tricrawl/logs/last_run.log`
- 최종 요약에 `알림 전송` 개수가 표시됩니다.
- 테스트 시 `LOG_LEVEL=INFO`를 사용하면 원인 파악이 쉽습니다.

---

## 7. PR 전 체크리스트

- [ ] 필수 필드 누락 없음
- [ ] 새 스파이더/파이프라인 테스트 완료
- [ ] `development_standard.md` 반영
- [ ] `atomic_specs.md` 반영 (로직 변경 시)
