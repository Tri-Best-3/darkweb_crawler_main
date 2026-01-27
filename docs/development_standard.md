# TriCrawl 개발 표준 가이드

> 마지막 업데이트: 2026-01-21

TriCrawl의 코어 로직을 훼손하지 않고 새로운 기능을 안전하게 추가하기 위한 가이드입니다.

---

## 1. 아키텍처 원칙

TriCrawl은 Scrapy의 **파이프라인 패턴**을 따릅니다. 데이터는 물 흐르듯 다음 단계로 전달되며, 각 단계는 독립적이어야 합니다.

**[데이터 흐름]**
`Spider` (수집) → `Archive` (백업) → `Dedup` (중복제거) → `Filter` (데이터 가공) → `Notify` (외부 전송)

---

## 2. 데이터 컨트랙트 (Data Contracts)

각 모듈이 주고받는 데이터(`item`)의 필수 필드를 정의합니다. **뒷단 파이프라인이 정상 작동하려면 앞단에서 이 필드들을 반드시 보장해야 합니다.**

### 2.1. 기본 필드 (Spider가 생성)
모든 스파이더는 최소한 다음 필드를 포함해야 합니다.

| 필드명 | 타입 | 필수 | 설명 |
|--------|------|------|------|
| `source` | `str` | ✅ | 출처 식별자 (예: `Abyss`, `DarkNet`) |
| `title` | `str` | ✅ | 게시글 제목 |
| `url` | `str` | ✅ | 원본 URL (Onion 주소 포함) |
| `author` | `str` | ✅ | 작성자 (중복 제거 키로 사용됨) |
| `timestamp` | `str` | ✅ | 작성 시각 (부재 시 Spider가 현재 시각으로 채워야 함) |
| `content` | `str` | ❌ | 본문 내용 (없으면 빈 문자열) |

### 2.2. 확장 필드 (Pipeline이 주입)
필터링이나 분석 모듈을 새로 만들 때, 다음 필드들을 조작하여 알림 로직을 제어할 수 있습니다.

| 필드명 | 생성 주체 | 설명 | 알림 모듈(`discord_notify`) 영향 |
|--------|-----------|------|-----------------------------------|
| `risk_level` | Filter | 위험도 (`HIGH`, `MEDIUM`, `LOW`, `CRITICAL`) | 알림 색상 및 이모지 결정 (기본값: `HIGH`) |
| `matched_keywords` | Filter | 매칭된 키워드 리스트 (`list[str]`) | Embed 메시지의 "매칭 키워드" 필드에 표시됨 |
| `matched_targets` | Filter | 매칭된 타겟 키워드 리스트 (`list[str]`) | 타겟-온리 매칭 시 CRITICAL 판정에 필수적으로 사용됨 |
| `author_contacts` | Archive | 추출된 연락처 정보 (`dict`) | (현재는 알림에 미표시, 아카이브용) |

> **⚠️ 주의:** `risk_level`을 설정하지 않으면 알림 모듈은 무조건 **🔴 HIGH**로 간주합니다.

---

## 3. 모듈 개발 가이드라인

### 3.1. 파이프라인 개발 (Pipeline)

데이터를 정제하거나 외부 API(예: LLM 요약)를 붙이고 싶다면 파이프라인을 구현하면 됩니다.

**규칙:**
1. **리턴 필수:** 반드시 `return item`을 해야 다음 파이프라인으로 넘어갑니다.
2. **드롭 처리:** 필터링 대상이라면 `raise DropItem("사유")`를 발생시키세요.
3. **설정 주입:** 하드코딩하지 말고 `from_crawler`를 통해 `settings.py` 값을 받아오세요.

**예시 (LLM 요약 모듈):**
```python
class LLMSummaryPipeline:
    def process_item(self, item, spider):
        # 1. 본문이 너무 길면 요약
        if len(item.get("content", "")) > 1000:
            item["summary"] = call_llm_api(item["content"])
        
        # 2. 다음 단계로 전달
        return item 
```

### 3.2. 스파이더 개발 (Spider)

새로운 사이트를 크롤링해야 한다면 스파이더를 추가하세요.

**규칙:**
1. **Tor 미들웨어 사용 시:** `.onion` 사이트라면 `custom_settings` 확인이 필요할 수 있습니다. (현재 `darknet_army`는 독자 미들웨어 사용 중)
2. **날짜 파싱:** 가능한 UTC 표준 포맷으로 변환하여 `timestamp`에 넣으세요.

---

## 4. 설정(Config) 관리 원칙
- **값(Value) 수정 금지**: URL, 토큰, 임계값 등은 `settings.py`에 하드코딩하지 말고 환경 변수(`.env`)나 YAML을 이용하세요.
- **구조(Wiring) 수정 허용**: 새로운 파이프라인이나 미들웨어를 등록(`ITEM_PIPELINES` 추가)할 때는 `settings.py`를 수정해도 됩니다.
