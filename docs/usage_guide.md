# TriCrawl Usage Guide (사용자 가이드)

This document provides a detailed guide on how to use the TriCrawl CLI and its features.
(이 문서는 TriCrawl CLI 및 주요 기능의 상세 사용법을 안내합니다.)

## CLI Main Menu (메인 메뉴)

Run `python main.py` to enter the interactive CLI.

### 1. 🌑 Start Crawl
- **Function**: Runs a one-time crawl job.
- **Process**: 
    1. Checks Tor connection.
    2. Asks for the target spider (or 'ALL').
    3. Executes `scrapy crawl` inside a Docker container.
    4. Shows execution summary and stats after completion.
- **설명**: 일회성 크롤링 작업을 실행합니다. Tor 연결을 확인하고, 타겟 스파이더를 선택하여 Docker 컨테이너 내에서 크롤러를 구동합니다. 완료 후 요약 통계를 보여줍니다.

### 2. 📡 Monitoring Mode
- **Function**: Runs an automated scheduler loop with a real-time dashboard.
- **Features**:
    - **Countdown**: Visual countdown to the next run.
    - **Status Panel**: Shows current interval, target, and log file path.
    - **Live Logs**: Displays the current status of the scheduler.
- **Configuration**:
    - You can set the Interval (1h~24h), Target, and Reference Start Time via the sub-menu.
    - **Defaults**: The initial settings are loaded from `config/scheduler_state.json`.
        - Note: This file is **read-only** by default. To change startup defaults, edit this file manually.
- **설명**: 실시간 대시보드와 함께 자동 스케줄러를 실행합니다.
    - **기능**: 다음 실행까지 남은 시간을 카운트다운하고, 현재 설정 상태와 로그를 실시간으로 보여줍니다.
    - **설정**: 서브 메뉴에서 실행 주기(1시간~24시간), 타겟, 시작 기준 시간을 설정할 수 있습니다.
    - **초기값**: 프로그램 시작 시 `config/scheduler_state.json` 파일에서 기본 설정을 불러옵니다. 이 파일은 기본적으로 **읽기 전용**이며, 초기값을 영구적으로 바꾸고 싶을 때만 직접 수정하세요.

### 3. 🔬 Open Dashboard
- Opens the Apache Superset dashboard in your default browser.
- Requires `SUPERSET_CLOUD_URL` or local Superset setup.
- **설명**: 기본 웹 브라우저에서 Apache Superset 대시보드를 엽니다. `.env`에 `SUPERSET_CLOUD_URL`이 설정되어 있어야 합니다.

### 4. 📄 View Logs
- Opens the log file of the *last run* (`tricrawl/logs/last_run.log`) using the system's default text editor (Notepad, etc.).
- **설명**: 가장 최근에 실행된 로그 파일(`tricrawl/logs/last_run.log`)을 시스템 기본 텍스트 편집기(메모장 등)로 엽니다.

### 5. 🐳 Start Docker
- Runs `docker-compose up -d` to start the Tor Proxy and Superset/Supabase containers.
- **Must be run before crawling.**
- **설명**: `docker-compose up -d` 명령을 실행하여 Tor 프록시와 DB 컨테이너를 시작합니다. **크롤링 전에 반드시 실행해야 합니다.**

### 6. 🛑 Stop Docker
- Runs `docker-compose down` to stop all containers and free resources.
- **설명**: 모든 Docker 컨테이너를 중지하고 리소스를 해제합니다.

### 7. 💾 Export DB
- Exports data from Supabase to local JSONL and CSV files in `tricrawl/data/`.
- **설명**: Supabase DB에 저장된 데이터를 로컬의 `tricrawl/data/` 폴더로 내보냅니다 (JSONL/CSV 형식).

### 8. 🔔 Toggle Discord
- Toggles the `DISCORD_ENABLED` setting in `.env`.
- Useful for silencing notifications during testing.
- **설명**: `.env` 파일의 `DISCORD_ENABLED` 설정을 켜거나 끕니다. 테스트 중에 알림을 잠시 끄고 싶을 때 유용합니다.

---

## Configuration Files (설정 파일)

### 1. `config/scheduler_state.json`
Defines the **default settings** for Monitoring Mode.
(모니터링 모드 진입 시 사용될 기본값을 정의합니다.)

```json
{
  "interval_hours": 1,        // Execution interval (hours) / 실행 주기 (시간)
  "target": "ALL",            // Target spider name or "ALL" / 실행 대상
  "ref_start_time": null,     // Optional start time (YYYY-MM-DD HH:MM) / 시작 기준 시간 (옵션)
  "cycle_count": 0            // (Unused) / 미사용
}
```

### 2. `config/crawler_config.yaml`
Defines global crawling behavior (timeouts, retries).
(크롤링 타임아웃, 재시도 횟수 등 동작을 정의합니다.)

```yaml
global:
  days_to_crawl: 3        # Crawl posts from the last N days / 최근 N일치 게시물만 수집
  timeout_seconds: 60     # Request timeout / 요청 타임아웃 (초)
  max_retries: 2          # Max retries on failure / 실패 시 최대 재시도 횟수

spiders:
  lockbit:
    timeout_seconds: 120  # Spider-specific override / 특정 스파이더 개별 설정
```

---

## Troubleshooting (트러블슈팅)

- **Tor Connection Failed**:
    - Ensure Docker is running (Menu 5).
    - Wait 1-2 minutes for Tor to build circuits.
    - Check logs: `docker logs tricrawl-tor`.
    - **Tor 연결 실패**: Docker가 실행 중인지 확인하세요(5번 메뉴). Tor 회로 구성에 1~2분이 걸릴 수 있습니다.

- **Dashboard Not Opening**:
    - Check if `SUPERSET_CLOUD_URL` is set in `.env`.
    - If running locally, ensure the Superset container is up.
    - **대시보드 안 열림**: `.env` 파일에 `SUPERSET_CLOUD_URL`이 설정되었는지 확인하세요.
