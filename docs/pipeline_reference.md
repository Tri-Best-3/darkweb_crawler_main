# TriCrawl 파이프라인 참조

> 마지막 업데이트: 2026-01-20

이 문서는 TriCrawl의 각 파이프라인 역할과 설정을 상세히 설명합니다.

---

## 파이프라인 실행 순서

```python
# tricrawl/settings.py
ITEM_PIPELINES = {
    "tricrawl.pipelines.ArchivePipeline": 10,
    "tricrawl.pipelines.DeduplicationPipeline": 50,
    "tricrawl.pipelines.KeywordFilterPipeline": 100,
    "tricrawl.pipelines.DiscordNotifyPipeline": 300,
}
```

숫자가 낮을수록 먼저 실행됩니다.

---

## 1. ArchivePipeline (Priority: 10)

**파일**: `tricrawl/pipelines/archive.py`

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

**저장 위치**: `data/dedup_{spider_name}.json` (스파이더별 자동 격리)

**동작**:
1. `dedup_id` 확인 (없으면 `제목 + 작성자` 해시 생성 후 `item['dedup_id']`에 저장)
2. 캐시에 있으면 → `DropItem` (알림 안 감)
3. 캐시에 없으면 → 캐시에 추가 후 다음 파이프라인으로

**캐시 초기화**: `data/dedup_{spider_name}.json` 삭제

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
- `rules.require_target`가 `true`이면 타겟 미매칭 시 DropItem 됩니다.

### 필터링 예시

```
samsung 단독      → ✅ 알림 (CRITICAL, matched_keywords 없음)

leak 단독         → ❌ 드롭 (타겟 미매칭)
samsung leak      → ✅ 알림 (CRITICAL, matched_keywords: leak / matched_targets: samsung)
```

---

## 4. DiscordNotifyPipeline (Priority: 300)

**파일**: `tricrawl/pipelines/discord_notify.py`

**역할**: 필터 통과 아이템을 Discord Webhook으로 전송

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
