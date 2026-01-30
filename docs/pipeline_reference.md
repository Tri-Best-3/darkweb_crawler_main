# TriCrawl 파이프라인 참조

> 마지막 업데이트: 2026-01-26

이 문서는 TriCrawl의 각 파이프라인 역할과 설정을 상세히 설명합니다.

---

## 파이프라인 실행 순서

```python
# tricrawl/settings.py
ITEM_PIPELINES = {
    # "tricrawl.pipelines.ArchivePipeline": 10,  # 로컬 아카이빙 (현재 비활성)
    "tricrawl.pipelines.DeduplicationPipeline": 50,
    "tricrawl.pipelines.KeywordFilterPipeline": 100,
    "tricrawl.pipelines.supabase.SupabasePipeline": 200, # Supabase 저장
    "tricrawl.pipelines.DiscordNotifyPipeline": 300,
}
```

숫자가 낮을수록 먼저 실행됩니다.

---

## 1. ArchivePipeline (Priority: 10)

**파일**: `tricrawl/pipelines/archive.py`

**상태**: **비활성화 (Legacy)** -> `SupabasePipeline`으로 기능 통합됨

**역할**: 모든 크롤링 데이터를 JSON으로 저장 (필터링 여부 무관)

**저장 위치**: `data/archive_{spider_name}.jsonl` (스파이더별 자동 격리)

**저장 필드**:
| 필드 | 설명 |
|------|------|
| `spider` | 스파이더 이름 |
| `category` | 게시판 카테고리 |
| `title` | 게시글 제목 (접두어 없음) |
| `timestamp` | 작성 시간 (없을 시 크롤링 시각) |
| `author` | 작성자 |
| `author_contacts` | 추출된 연락처 (Telegram, Email, Discord) |
| `url` | 원본 URL |
| `matched_keywords` | targets/critical_keywords 매칭 결과 (patterns.* 제외) |
| `dedup_id` | 스파이더별 유니크 ID |
| `crawled_at` | 크롤링 시간 |

**연락처 추출 패턴**:
```python
CONTACT_PATTERNS = {
    "telegram": [r"@(\w{5,32})", r"t\.me/(\w+)"],
    "email": [r"\S+@\S+\.\S+"],
    "discord": [r"discord\.gg/(\w+)"],
}
```

---

## 2. DeduplicationPipeline (Priority: 50)

**파일**: `tricrawl/pipelines/dedup.py`

**역할**: 이미 알림 보낸 게시물 중복 방지

**저장 위치**: `Supabase DB` (darkweb_leaks 테이블) / `메모리`(Pre-filtering)

**동작**:
1. **Initial Load**: 스파이더 시작 시 DB에서 최근 `dedup_id`를 가져와 스파이더에게 주입 (`spider.seen_ids`).
2. **Pre-filtering**: 스파이더는 URL 해시를 `seen_ids`와 비교하여, 중복이면 **크롤링 요청 자체를 스킵** (Tor 대역폭 절약).
3. **Pipeline Check**: 혹시 뚫고 들어온 아이템은 파이프라인 단계에서 다시 `seen_hashes`와 비교하여 `DropItem`.

**캐시**: 메모리에 유지하며, DB는 동기화 용도.

---

## 3. KeywordFilterPipeline (Priority: 100)

**파일**: `tricrawl/pipelines/keyword_filter.py`

**역할**: 키워드 기반 필터링 (조건부 로직 포함)

### 키워드 로드

`config/keywords.yaml`에서 모든 키워드 로드

### 키워드 로드

`config/keywords.yaml`의 `patterns.conditional` 섹션에 정의됨:

```yaml
patterns:
  conditional:
    - combolist
    - leak
    # ...
```

### 키워드 분류

| 분류 | 정의 위치 | 로직 |
|------|----------|----------|
| **타겟 키워드** | `keywords.yaml` → `targets:` | ✅ 매칭 시 알림 및 CRITICAL 부여 |
| **조건부 키워드** | `keywords.yaml` → `patterns.conditional` | ❌ 타겟과 함께 있을 때만 알림 |


- `matched_keywords`는 조건부 키워드만 기록됩니다.
- `matched_targets`는 타겟 키워드만 기록됩니다.
- `rules.require_target`가 `false`로 설정되어 타겟 키워드가 없어도 조건부 키워드가 있으면 수집(알림)됩니다.
- **드롭 조건**: 타겟 키워드도 없고, 조건부 키워드도 없는 경우에만 DropItem 됩니다.

### 필터링 예시

```
samsung 단독      → ✅ 알림 (CRITICAL, matched_keywords 없음)

leak 단독         → ✅ 알림 (High/Medium, matched_keywords: leak)
samsung leak      → ✅ 알림 (CRITICAL, matched_keywords: leak / matched_targets: samsung)
```

---

## 4. SupabasePipeline (Priority: 200)

**파일**: `tricrawl/pipelines/supabase.py`

**역할**: 최종 데이터를 Supabase 데이터베이스에 영구 저장 (SSOT)

**주요 기능**:
1. **DB 저장**: `KeywordFilterPipeline`을 통과한 아이템 저장 (UPSERT)
2. **연락처 자동 추출**: 본문(`content`)에서 텔레그램, 이메일, 디스코드 등을 정규식으로 추출하여 `author_contacts` 컬럼(JSONB)에 저장
   - 패턴 출처: `config/keywords.yaml`

**스키마 매핑**:
- `author_contacts`: `metrics` (JSONB) - 예: `{"telegram": ["@admin"], "email": ["..."]}`
- `views`: `views` (Int)
- `dedup_id`: PK (String)

**동작**:
- `dedup_id`를 PK로 사용하여 **UPSERT** (On Conflict Do Update/Nothing) 처리합니다.
- 필드 매핑: `site_type`, `category`, `views`, `author_contacts` 등 메타데이터 포함.

---

## 5. DiscordNotifyPipeline (Priority: 300)

**파일**: `tricrawl/pipelines/discord_notify.py`

**역할**: 필터 통과 아이템을 Discord Webhook으로 전송

### 동작 방식 (Rate Limit Safe)
- **Queue & Worker**: 수집된 아이템은 즉시 큐에 쌓이고, 별도의 워커 스레드가 처리합니다.
- **Throttling**: 디스코드 Rate Limit(429 Error) 방지를 위해 **1.0초 간격**으로 순차 전송합니다.
- **Retry**: 전송 실패 시 최대 3회 재시도합니다.

### Embed 포맷

```
🚨 Title of the Leak
────────────────
🎯 Target: Abyss Ransomware
📅 Date: 2026-01-20T15:30:00
📂 Category: Ransomware

```본문 미리보기 (300자)```

🔑 Matched Keywords: leak (Risk: CRITICAL)
🎯 Targets: samsung
🔗 Source: http://...
────────────────
Footer: TriCrawl • Abyss Ransomware
```

### 위험도별 색상

| 위험도 | 색상 코드 | 색상 |
|--------|----------|------|
| CRITICAL | `0xff0000` | 빨강 (진함) |
| HIGH | `0xe74c3c` | 주황/빨강 |
| MEDIUM | `0xf39c12` | 노랑/주황 |
| LOW | `0x2ecc71` | 초록 |

---

## 파이프라인 추가하기

### 1. 파일 생성

```python
# tricrawl/pipelines/my_pipeline.py
from scrapy.exceptions import DropItem

class MyPipeline:
    def process_item(self, item, spider):
        # 처리 로직
        return item  # 또는 raise DropItem(...)
```

### 2. __init__.py에 추가

```python
# tricrawl/pipelines/__init__.py
from .my_pipeline import MyPipeline
__all__ = [..., "MyPipeline"]
```

### 3. settings.py에 등록

```python
ITEM_PIPELINES = {
    ...,
    "tricrawl.pipelines.MyPipeline": 150,  # 순서 지정
}
```
