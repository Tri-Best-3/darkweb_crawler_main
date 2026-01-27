# TriCrawl Atomic Specifications

> 마지막 업데이트: 2026-01-26

프로젝트의 모든 기능을 **최소 단위(Atomic Unit)**로 분해하여 정의한 명세서입니다.
각 항목은 독립적으로 테스트 및 검증 가능해야 합니다.

---

## 1. Core & Infrastructure (CORE)

| ID | 구분 | 기능 정의 | 세부 요구사항 |
|----|----|-----------|---------------|
| `CORE-001` | Network | **Tor 프록시 연결** | 로컬 Docker 컨테이너의 9050 포트를 통해 SOCKS5 프로토콜로 연결되어야 한다. |
| `CORE-002` | Network | **.onion DNS 해석** | 일반 DNS가 아닌 Tor 네트워크를 통해 `.onion` 도메인을 해석(Remote DNS Resolution)해야 한다. |
| `CORE-003` | Network | **User-Agent 로테이션** | (선택) 요청 시마다 또는 세션마다 User-Agent가 변경되어야 한다. (현재 고정값 사용 중, 향후 확장) |
| `CORE-004` | Config | **YAML 설정 로드** | `crawler_config.yaml`과 `keywords.yaml`을 파싱하여 메모리에 로드해야 한다. |
| `CORE-005` | Config | **Env 오버라이드** | `.env` 파일의 환경변수가 기본 설정보다 우선순위를 가져야 한다. (예: Webhook URL) |

## 2. Spider Modules (SPD)

### 2.1. Common (SPD-COM)
| ID | 구분 | 기능 정의 | 세부 요구사항 |
|----|----|-----------|---------------|
| `SPD-COM-001` | Input | **Start URLs** | 스파이더 시작 시 `start_urls` 리스트를 순차적으로 로드해야 한다. |
| `SPD-COM-002` | Output | **Item 생성** | 모든 파싱 결과는 `LeakItem` 표준 스키마(title, url, source, **site_type**, **category** 등)를 준수해야 한다. |

### 2.2. Abyss Spider (SPD-ABY)
| ID | 구분 | 기능 정의 | 세부 요구사항 |
|----|----|-----------|---------------|
| `SPD-ABY-001` | Parser | **JS Data Parsing** | `data.js` 파일 내의 `window.data = [...]` 구조를 파싱하여 Python 객체로 변환해야 한다. |
| `SPD-ABY-002` | Logic | **비표준 JSON 처리** | Key에 따옴표가 없는 등 비표준 JS 객체를 `ast` 또는 `Regex`로 최대한 파싱(Best Effort)해야 한다. |

### 2.3. DarkNetArmy Spider (SPD-DNA)
| ID | 구분 | 기능 정의 | 세부 요구사항 |
|----|----|-----------|---------------|
| `SPD-DNA-001` | Net | **Requests Middleware** | Scrapy 기본 엔진 대신 `requests` + `PySocks`를 사용하며, **우선순위 900**으로 미뤄 쿠키(CookiesMiddleware)를 포함해야 한다. |
| `SPD-DNA-002` | Parser | **XenForo List** | 게시판 리스트 페이지에서 제목, 링크, 작성자, 작성일을 추출해야 한다. |
| `SPD-DNA-003` | Parser | **Hidden Content** | "Reply to see" 등의 숨겨진 콘텐츠가 있을 경우, 이를 별도 표시하거나 감지해야 한다. |
| `SPD-DNA-004` | Filter | **Date Cutoff** | 설정된 날짜(`days_to_crawl`)보다 오래된 게시물은 파싱 단계에서 드롭해야 한다. |

## 3. Data Pipelines (PL)

### 3.1. Archive Pipeline (PL-ARC)
| ID | 구분 | 기능 정의 | 세부 요구사항 |
|----|----|-----------|---------------|
| `PL-ARC-001` | Storage | **Stream Save** | 아이템 수신 즉시 파일에 써야 한다(메모리 적재 금지). |
| `PL-ARC-002` | Storage | **Isolation** | 스파이더 이름별로 별도의 파일(`archive_{spider}.jsonl`)에 저장해야 한다. |
| `PL-ARC-003` | Logic | **Contact Extraction** | 본문 텍스트에서 정규식으로 Telegram, Email, Discord 포맷을 추출해야 한다. |

### 3.2. Deduplication Pipeline (PL-DED)
| ID | 구분 | 기능 정의 | 세부 요구사항 |
|----|----|-----------|---------------|
| `PL-DED-001` | Logic | **ID Logic** | `dedup_id` 필드는 스파이더가(특히 URL 기반) 우선 생성해야 하며, 없으면 파이프라인이 생성한다. |
| `PL-DED-002` | Storage | **Persistence** | 프로그램 시작 시 **Supabase**에서 기존 ID를 로드하여 **스파이더에게 주입(Injection)** 해야 한다. |
| `PL-DED-003` | Logic | **Pre-filtering** | 주입된 ID 목록을 기반으로 스파이더는 중복 URL에 대한 **요청 전송을 사전에 차단**해야 한다. |

### 3.3. Keyword Filter Pipeline (PL-KWD)
| ID | 구분 | 기능 정의 | 세부 요구사항 |
|----|----|-----------|---------------|
| `PL-KWD-001` | Logic | **Target Matching** | `targets` 목록에 있는 키워드가 포함되면 무조건 매칭(Allow) 처리해야 한다. |
| `PL-KWD-002` | Logic | **Conditional Logic** | `conditional` 키워드(예: leak)는 단독으로 매칭되어도 알림을 보낼 수 있어야 한다 (`require_target: false` 기본값 적용). |
| `PL-KWD-003` | Logic | **Risk Scoring** | 매칭 결과에 따라 `CRITICAL`, `HIGH`, `MEDIUM`, `LOW` 등급을 부여해야 한다. |
| `PL-KWD-004` | Action | **Tagging** | 매칭되는 키워드가 없으면 `DropItem` 대신 `risk_level='NONE'`으로 태깅하여 통과시켜야 한다(Archive All). |

### 3.4. Discord Notify Pipeline (PL-NOT)
| ID | 구분 | 기능 정의 | 세부 요구사항 |
|----|----|-----------|---------------|
| `PL-NOT-001` | UI | **Embed Formatting** | 저장된 데이터 필드(Type, Category 포함)를 사용하여 보기 좋은 Discord Embed JSON을 생성해야 한다. |
| `PL-NOT-002` | UI | **Color Coding** | 위험도에 따라 측면 색상을 지정해야 한다. (CRITICAL: `0xff0000`/Red, HIGH: `0xe74c3c`/Orange, MEDIUM: `0xf39c12`/Yellow, LOW: `0x2ecc71`/Green) |
| `PL-NOT-003` | Net | **Rate Limiting** | Discord API의 Rate Limit 방지를 위해 **1.0초 간격**으로 순차 전송(Queueing)해야 한다. |
| `PL-NOT-004` | Logic | **Async Handling** | 알림 전송 로직이 메인 크롤링 루프(Blocking)를 방해하지 않도록 비동기/스레드로 처리해야 한다. |

## 4. Admin CLI (CLI)

| ID | 구분 | 기능 정의 | 세부 요구사항 |
|----|----|-----------|---------------|
| `CLI-001` | UX | **Numeric Menu** | 터미널에서 숫자 입력을 통해 메뉴를 선택하고 이동할 수 있어야 한다. |
| `CLI-002` | Function | **Docker Control** | Python 스크립트 내에서 `docker-compose` 명령어를 실행하여 컨테이너를 제어할 수 있어야 한다. |
| `CLI-003` | Function | **Spider Runner** | 사용자가 선택한 스파이더를 `scrapy crawl` 서브프로세스로 실행하고 출력을 보여줘야 한다. |
