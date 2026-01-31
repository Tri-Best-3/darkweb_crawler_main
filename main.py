#!/usr/bin/env python
"""
TriCrawl Admin Console
다크웹 크롤러 관리 CLI(Rich UI 사용했음)
"""
import subprocess
import os
import sys
import io
import socks
import argparse
import re
import shutil
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

def _configure_utf8_output():
    """콘솔 출력 인코딩을 UTF-8로 고정해 한글 출력 깨짐을 방지."""
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUTF8", "1")
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
            continue
        except Exception:
            pass
        try:
            buffer = stream.buffer
        except Exception:
            continue
        try:
            wrapped = io.TextIOWrapper(
                buffer,
                encoding="utf-8",
                errors="replace",
                line_buffering=True,
                write_through=True,
            )
            setattr(sys, name, wrapped)
        except Exception:
            pass


_configure_utf8_output()

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.columns import Columns
    from rich import box
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

plain_mode = os.getenv("TRICRAWL_PLAIN", "").lower() in ("1", "true", "yes")
if HAS_RICH and not plain_mode:
    no_color = os.getenv("NO_COLOR") is not None or os.getenv("TRICRAWL_NO_COLOR", "").lower() in (
        "1",
        "true",
        "yes",
    )
    console = Console(
        soft_wrap=True,
        emoji=False,
        highlight=False,
        no_color=no_color,
        color_system=None if no_color else "standard",
    )
else:
    HAS_RICH = False
    console = None
# Global State
DISCORD_ENABLED = os.getenv("DISCORD_ENABLED", "true").lower() in ("true", "1", "yes")

PROJECT_ROOT = Path(__file__).parent
TRICRAWL_DIR = PROJECT_ROOT / "tricrawl"
LOG_DIR = TRICRAWL_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

try:
    from scrapy.utils.project import get_project_settings
    from scrapy.spiderloader import SpiderLoader
    HAS_SCRAPY = True
except Exception:
    HAS_SCRAPY = False

# Exporter Import
try:
    from tricrawl.exporter import DataExporter
    exporter = DataExporter()
except Exception:
    exporter = None

# Middleware
from tricrawl.middlewares import SupersetDashboardMiddleware

def format_duration(seconds):
    """초 단위를 사람이 읽기 쉬운 mm:ss 또는 hh:mm:ss로 변환."""
    try:
        seconds = int(seconds)
    except Exception:
        return "n/a"
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _extract_stats_from_log(log_file):
    """
    Scrapy 로그 파일에서 주요 통계를 추출.

    - 로그가 dictionary 형태로 출력된 라인에서 숫자만 파싱
    - 없으면 빈 dict 반환
    """
    try:
        text = log_file.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return {}

    keys = [
        "item_scraped_count",
        "item_dropped_count",
        "discord_notify/sent",
        "downloader/request_count",
        "downloader/response_count",
        "log_count/ERROR",
        "log_count/WARNING",
    ]
    
    stats = {}
    for key in keys:
        match = re.search(rf"'{re.escape(key)}':\s*(\d+)", text)
        if match:
            stats[key] = int(match.group(1))
    return stats


 
def get_docker_status():
    """Docker 컨테이너 상태 확인 (Superset, Tor, Worker, DB 등)."""
    target_services = {
        "tricrawl-tor": "Tor Proxy",
        "superset-app": "Superset",
        "superset-db": "Meta DB",
        "superset-cache": "Redis"
    }
    
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}:{{.Status}}"],
            capture_output=True, text=True, timeout=5, encoding="utf-8"
        )
        if result.returncode != 0:
            return False, {}
            
        running_containers = {}
        for line in result.stdout.splitlines():
            if ":" in line:
                name, status = line.split(":", 1)
                running_containers[name] = status.strip()
        
        core_services = ["tricrawl-tor", "superset-app", "superset-db"]
        all_up = all(s in running_containers for s in core_services)
        
        status_map = {}
        for svc, label in target_services.items():
            is_running = svc in running_containers
            status_text = running_containers.get(svc, "Stopped")
            if is_running:
                if "Up" in status_text:
                    status_text = "Running"
            status_map[label] = status_text
            
        return all_up, status_map
    except Exception:
        return False, {}


def get_tor_status():
    """Tor 프록시 연결 상태 확인 (SOCKS5 연결 테스트)."""
    host = os.getenv("TOR_PROXY_HOST", "127.0.0.1")
    port = int(os.getenv("TOR_PROXY_PORT", "9050"))
    
    try:
        sock = socks.socksocket()
        sock.set_proxy(socks.SOCKS5, host, port)
        sock.settimeout(3)
        sock.connect(("check.torproject.org", 80))
        sock.close()
        return True, f"{host}:{port}"
    except:
        return False, f"{host}:{port}"


def get_available_spiders():
    """사용 가능한 스파이더 목록 가져오기 (Scrapy 로더 → subprocess fallback)."""
    if HAS_SCRAPY:
        try:
            os.environ.setdefault("SCRAPY_SETTINGS_MODULE", "tricrawl.settings")
            settings = get_project_settings()
            loader = SpiderLoader.from_settings(settings)
            return sorted(loader.list())
        except Exception:
            pass

    try:
        result = subprocess.run(
            ["scrapy", "list"],
            cwd=str(TRICRAWL_DIR),
            capture_output=True,
            text=True,
            timeout=5,
            encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        if result.returncode == 0:
            return [s.strip() for s in result.stdout.splitlines() if s.strip()]
    except Exception:
        return []
    return []


def get_webhook_status():
    """Discord 웹훅 설정 상태 확인 (.env 및 활성화 여부)."""
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")
    is_set = bool(webhook_url and "discord.com/api/webhooks" in webhook_url)
    
    if not is_set:
        return False, "미설정"
    
    if DISCORD_ENABLED:
        return True, "ON (설정됨)"
    else:
        return False, "OFF (중지됨)"


def build_stage_panel(title, subtitle, icon_emoji, status_ok, status_text, action_hint):
    """Rich Panel 형태의 상태 박스를 생성."""
    status_icon = "[green]✅[/green]" if status_ok else "[red]❌[/red]"
    color = "green" if status_ok else "red"
    
    content = f"{status_icon} {status_text}"
    if not status_ok:
        content += f"\n[dim]→ {action_hint}[/dim]"
    
    return Panel(
        content,
        title=f"[bold]{icon_emoji} {title}[/bold]",
        subtitle=subtitle,
        border_style=color,
        width=28,
        padding=(0, 1)
    )


def print_header():
    """콘솔 상단 헤더/타이틀 출력."""
    clear_screen()
    if HAS_RICH:
        console.print()
        console.print(Panel.fit(
            "🕷️ TriCrawl Admin Console\n[dim]다크웹 정보 유출 탐지 크롤러[/dim]", 
            border_style="cyan"
        ))
        console.print()
    else:
        print("\n=== TriCrawl Admin Console ===\n")


def print_guide():
    """사전 준비 및 빠른 시작 안내 패널 출력."""
    if not HAS_RICH:
        return
    
    prereq_content = (
        "[bold]1. Docker Desktop[/bold]\n"
        "   실행 상태여야 합니다.\n\n"
        "[bold]2. .env 설정[/bold]\n"
        "   [cyan].env.example[/cyan]을 복사해서\n"
        "   [cyan].env[/cyan]를 만드세요."
    )

    quickstart_content = (
        "[bold green]Step 1[/bold green]: [bold]System On (5)[/bold]\n"
        "   인프라(DB, Tor)를 켭니다.\n\n"
        "[bold green]Step 2[/bold green]: [bold]Action (1 or 2)[/bold]\n"
        "   크롤링을 하거나 대시보드를 엽니다."
    )

    console.print(Columns([
        Panel(prereq_content, title="📋 사전 체크 (Prerequisites)", border_style="dim", width=40),
        Panel(quickstart_content, title="🚀 워크플로우 (Workflow)", border_style="blue", width=40)
    ], expand=False))
    console.print()


def status():
    """Docker/Tor/Webhook의 전체 상태를 한 화면에 표시."""
    print_header()
    
    if not HAS_RICH:
        print("[!] Install rich for better display: pip install rich")
        return
    
    print_guide()
    
    docker_ok, status_map = get_docker_status()
    tor_ok, tor_addr = get_tor_status()
    webhook_ok, webhook_text = get_webhook_status()

    grid = Table.grid(padding=(1, 2))
    grid.add_column("Section", justify="center")
    grid.add_column("Content")

    # 1. Docker Cluster Status
    docker_table = Table(box=None, show_header=False, padding=(0, 1))
    docker_table.add_column("Service")
    docker_table.add_column("Status")
    
    if status_map:
        for label, state in status_map.items():
            icon = "🟢" if state == "Running" else "⚪"
            style = "bold green" if state == "Running" else "dim"
            docker_table.add_row(label, f"[{style}]{icon} {state}[/{style}]")
    else:
        docker_table.add_row("Docker", "[red]❌ Stopped[/red]")

    docker_panel = Panel(
        docker_table,
        title="[bold]🐳 Infrastructure[/bold]",
        border_style="green" if docker_ok else "red",
        width=35
    )

    # 2. Network & Alert Status
    net_table = Table(box=None, show_header=False, padding=(0, 1))
    net_table.add_column("Label")
    net_table.add_column("Value")
    
    # Tor
    tor_icon = "🟢" if tor_ok else "🔴"
    tor_status = f"[bold green]Connected[/bold green]" if tor_ok else "[red]Disconnected[/red]"
    net_table.add_row(f"{tor_icon} Tor Proxy", tor_status)
    
    # Webhook
    web_icon = "🔔" if webhook_ok else "🔕"
    web_status = f"[green]{webhook_text}[/green]" if webhook_ok else f"[yellow]{webhook_text}[/yellow]"
    net_table.add_row(f"{web_icon} Webhook", web_status)

    net_panel = Panel(
        net_table,
        title="[bold]🌐 Network & Alert[/bold]",
        border_style="blue",
        width=35
    )

    # 배치
    console.print(Columns([docker_panel, net_panel], expand=False))
    console.print()


def check_docker_daemon():
    """Docker 데몬 실행 여부 확인 (docker info)."""
    # Docker 데몬 실행 여부 확인
    try:
        # docker info 명령어로 데몬 접속 확인
        subprocess.run(
            ["docker", "info"],
            capture_output=True, 
            check=True,
            timeout=3
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return False


def start_docker():
    """Docker 컨테이너 시작 + Tor 연결 대기."""
    if not check_docker_daemon():
        if HAS_RICH:
            console.print(Panel(
                "[bold red]Docker Desktop이 실행되지 않았습니다![/bold red]\n\n"
                "Docker Desktop을 먼저 실행해주세요.\n"
                "실행 후 잠시 기다렸다가 다시 시도해주세요.",
                title="❌ Docker Error",
                border_style="red"
            ))
        else:
            print("\n❌ Docker Desktop is NOT running. Please start it first.")
        return

    import time
    
    # Rich Status Spinner로 실행 및 대기
    if HAS_RICH:
        with console.status("[bold green]🐳 Docker 컨테이너를 시작하고 있습니다...[/bold green]") as status:
            try:
                result = subprocess.run(
                    ["docker-compose", "up", "-d"],
                    cwd=str(PROJECT_ROOT),
                    capture_output=True, text=True,
                    encoding="utf-8",
                    errors="replace"
                )

                # Conflict 발생 시 자동 복구 시도
                if result.returncode != 0 and "Conflict" in result.stderr:
                    if status:
                        status.update("[bold yellow]⚠️ 좀비 컨테이너 발견! 강제 정리 중...[/bold yellow]")
                    
                    subprocess.run(
                        ["docker", "rm", "-f", "tricrawl-tor"],
                        capture_output=True, text=True,
                        encoding="utf-8",
                        errors="replace"
                    )
                    
                    subprocess.run(
                        ["docker-compose", "down"],
                        cwd=str(PROJECT_ROOT),
                        capture_output=True, text=True
                    )
                    
                    time.sleep(2)
                    
                    result = subprocess.run(
                        ["docker-compose", "up", "-d"],
                        cwd=str(PROJECT_ROOT),
                        capture_output=True, text=True
                    )
                
                if result.returncode != 0:
                    console.print(f"[bold red]❌ 실행 실패:[/bold red]\n{result.stderr}")
                    return
                
                # Tor 연결 대기 루프
                max_retries = 30 # 60초 (2초 * 30회)
                for i in range(max_retries):
                    tor_ok, tor_addr = get_tor_status()
                    if tor_ok:
                        console.print(f"\n[bold green]✅ Docker 및 Tor 프록시 준비 완료![/bold green] ({tor_addr})")
                        return
                    
                    status.update(f"[bold cyan]⏳ Tor 프록시 연결 대기 중... ({i*2}s)[/bold cyan]\n[dim]Docker는 실행되었으나 Tor 회로 구성 중입니다.[/dim]")
                    time.sleep(2)
                
                console.print(f"\n[bold yellow]⚠️ Tor 연결 시간 초과.[/bold yellow]\nDocker는 실행되었으나 프록시 응답이 늦습니다. 잠시 후 Status를 확인하세요.")
                
            except Exception as e:
                console.print(f"[bold red]❌ 오류 발생:[/bold red] {e}")
    
    else:
        # Non-Rich Fallback
        print("\n🐳 Starting Docker containers...")
        try:
            subprocess.run(["docker-compose", "up", "-d"], cwd=str(PROJECT_ROOT), check=True)
            print("✅ Docker containers started.")
            print("⏳ Waiting for Tor connection (may take 10-20s)...")
            time.sleep(10) # 단순 대기
            print("Done.")
        except Exception as e:
            print(f"❌ Error: {e}")


def stop_docker():
    """Docker 컨테이너 종료."""
    print("\n🐳 Stopping Docker containers...")
    try:
        result = subprocess.run(
            ["docker-compose", "down"],
            cwd=str(PROJECT_ROOT),
            capture_output=True, text=True,
            encoding="utf-8",
            errors="replace"
        )
        if result.returncode == 0:
            print("✅ Docker containers stopped")
        else:
            print(f"❌ Error: {result.stderr}")
    except Exception as e:
        print(f"❌ Error: {e}")


def view_logs(lines=20):
    """로그 파일을 OS 기본 프로그램으로 연다."""
    log_file = LOG_DIR / "last_run.log"
    if not log_file.exists():
        print("\n로그 파일이 없습니다. 먼저 크롤러를 실행하세요.")
        return

    try:
        print(f"\n로그 파일을 엽니다: {log_file}")
        if os.name == "nt":
            os.startfile(log_file)
        elif sys.platform == "darwin":
            subprocess.run(["open", str(log_file)])
        else:
            subprocess.run(["xdg-open", str(log_file)])
    except Exception as e:
        print(f"로그 파일 열기 실패: {e}")


def run_crawler(spider="test", limit=None):
    """
    Scrapy 크롤러 실행 래퍼.

    - config/crawler_config.yaml에서 days_to_crawl을 로드
    - 실행 로그는 tricrawl/logs/last_run.log에 저장
    - 스파이더는 LeakItem 데이터 컨트랙트를 지켜야 함
    """
    # 크롤러 실행
    log_file = LOG_DIR / "last_run.log"
    # 스파이더별 표시 이름
    display_name = {
        "test": "Test Integration (Mockup Crawl + Webhook)",
        "darknet_army": "DarkNetArmy (Dark Web Forum)",
        "abyss": "Abyss (Ransomware Site)",
    }

    config_path = PROJECT_ROOT / "config" / "crawler_config.yaml"
    days_limit = 3

    if config_path.exists():
        import yaml
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                conf = yaml.safe_load(f) or {}
                # 전역 설정만 로드(스파이더별 설정은 스파이더가 직접 로드)
                days_limit = conf.get("global", {}).get("days_to_crawl", 3)
        except Exception as e:
            print(f"??  Config Load Error: {e}")
    else:
        print("??  Config file not found. Using defaults.")

    # 시작 정보는 Rich Progress Panel에서 출력함 (중복 제거)
    print()  # 빈 줄

    if shutil.which("scrapy") is None:
        print("scrapy 명령을 찾을 수 없습니다. venv를 활성화하세요.")
        return

    start_time = time.time()
    original_cwd = Path.cwd()
    os.chdir(TRICRAWL_DIR) 
    
    try:
        log_file_rel = f"tricrawl/logs/last_run.log"
        
        # 1. 로그 파일 초기화 (호스트에서)
        try:
            log_file.write_text("", encoding="utf-8")
        except Exception:
            pass
            
        # 2. Docker Command 구성
        cmd = [
            "docker-compose", 
            "run", 
            "--rm",
            "crawler", 
            "scrapy", 
            "crawl", 
            spider,
            "-a", 
            f"days_limit={days_limit}"
        ]
        
        if not DISCORD_ENABLED:
            cmd.extend(["-s", "DISCORD_WEBHOOK_URL="])
            
        docker_log_path = "/app/tricrawl/logs/last_run.log"
        
        # 환경변수 전달 (-e)
        env_args = [
            "-e", f"TRICRAWL_LOG_FILE={docker_log_path}",
            "-e", "TERM=xterm-256color",
            "-e", "PYTHONIOENCODING=utf-8"
        ]
        
        final_cmd = cmd[:3] + env_args + cmd[3:]

        if HAS_RICH:
             console.print(f"[dim]Command: {' '.join(final_cmd)}[/dim]")
             
        if HAS_RICH:
            console.print(f"[bold cyan]🚀 Spider '{spider}' 실행 중...[/bold cyan]")
            console.print("[dim]Docker 컨테이너를 생성하고 크롤링을 수행합니다. (Detailed logs enabled)[/dim]")
            
        result = subprocess.run(
            final_cmd, 
            cwd=str(PROJECT_ROOT)
        )


            
        exit_code = result.returncode

        print()
        elapsed = format_duration(time.time() - start_time)
        summary_lines = []
        summary_lines.append("=" * 60)
        if exit_code == 0:
            summary_lines.append("크롤링 완료 (Docker Worker)")
        else:
            summary_lines.append(f"크롤링 종료 (코드: {exit_code})")
        summary_lines.append(f"소요 시간: {elapsed}")
        
        # 3. 로그 분석 (호스트에 공유된 파일을 읽음)
        stats = _extract_stats_from_log(log_file)
        if stats:
            if "item_scraped_count" in stats:
                summary_lines.append(f"수집: {stats['item_scraped_count']}")
            if "item_dropped_count" in stats:
                summary_lines.append(f"필터/중복 제외: {stats['item_dropped_count']}")
            if "discord_notify/sent" in stats:
                summary_lines.append(f"알림 전송: {stats['discord_notify/sent']}")
            if "log_count/ERROR" in stats or "log_count/WARNING" in stats:
                errors = stats.get("log_count/ERROR", 0)
                warnings = stats.get("log_count/WARNING", 0)
                summary_lines.append(f"에러/경고: {errors}/{warnings}")
        summary_lines.append(f"로그 파일: {log_file}")
        summary_lines.append("=" * 60)

        # 로그 파일에 요약 추가
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write("\n")
                for line in summary_lines:
                    f.write(f"{line}\n")
        except Exception:
            pass
            
    except KeyboardInterrupt:
        print()
        print("중단됨")
    except Exception as e:
        print()
        print(f"실행 오류: {e}")
    finally:
        os.chdir(original_cwd)


def clear_screen():
    """콘솔 화면 지우기."""
    # 화면 지우기
    os.system('cls' if os.name == 'nt' else 'clear')


def print_menu():
    """메인 메뉴 출력 (Rich/Plain 모드 자동 선택)."""
    # 메뉴 출력
    if HAS_RICH:
        # 메인 레이아웃 테이블
        grid = Table.grid(padding=(0, 4))
        grid.add_column("Left", justify="left")
        grid.add_column("Right", justify="left")

        # 왼쪽: 핵심 작업 (Core Actions)
        table_left = Table(box=box.SIMPLE, show_header=True, header_style="bold magenta")
        table_left.add_column("🚀 Core Actions")

        table_left.add_row("[bold magenta]1[/bold magenta]. 🌑 Start Crawl [dim](Run Worker)[/dim]")
        mode = os.getenv("TRICRAWL_SUPERSET_MODE", "cloud").lower()
        table_left.add_row(f"[bold magenta]2[/bold magenta]. 🔬 Open Dashboard [dim]({mode.upper()})[/dim]")
        table_left.add_row("[bold magenta]3[/bold magenta]. 📄 View Logs [dim](Notepad)[/dim]")
        table_left.add_row("[bold magenta]4[/bold magenta]. 💾 Export DB [dim](JSONL/CSV)[/dim]")

        # 오른쪽: 시스템 관리 (System & Config)
        table_right = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
        table_right.add_column("⚙️  System & Config")

        table_right.add_row("[bold cyan]5[/bold cyan]. 🐳 Start Docker [dim](System Up)[/dim]")
        table_right.add_row("[bold cyan]6[/bold cyan]. 🛑 Stop Docker [dim](System Down)[/dim]")
        table_right.add_row("[dim]──────────────────────────────[/dim]")
        table_right.add_row(f"[bold cyan]7[/bold cyan]. 🔔 Toggle Discord [dim]({'ON' if DISCORD_ENABLED else 'OFF'})[/dim]")

        # Grid에 추가
        grid.add_row(table_left, table_right)
        
        # 하단 종료 메뉴
        console.print(grid)
        console.print("\n[dim]Press [bold]q[/bold] to Quit[/dim]")
        console.print()
    else:
        print("╭────┬────────────────────────────────┬────┬────────────────────────────────╮")
        print("│ 1  │ 🌑 Start Crawl                 │ 5  │ � Start Docker                │")
        print("│ 2  │ � Open Dashboard              │ 6  │ � Stop Docker                 │")
        print("│ 3  │ 📄 View Logs                   │ 7  │ � Toggle Discord              │")
        print("│ 4  │ 💾 Export DB to CSV            │    │                                │")
        print("│ q  │ 👋 Quit                        │    │                                │")
        print("╰────┴────────────────────────────────┴────┴────────────────────────────────╯")


def interactive_mode():
    """메뉴 기반 인터랙티브 모드."""
    global DISCORD_ENABLED
    # 인터랙티브 모드 실행
    while True:
        status()
        print_menu()
        
        try:
            cmd = input("  > Command: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            break
        
        if cmd in ['q', 'quit', 'exit']:
            print("\nBye!")
            break
        elif cmd == 'r':
            continue
        
        elif cmd == '1':
            # Dark Web Crawl (Moved to 1)
            tor_ok, _ = get_tor_status()
            if not tor_ok:
                print("\n⚠️  Warning: Tor Proxy is NOT connected!")
                print("   Docker started? Please wait for Tor circuit.")
                confirm = input("   Retry connection? (y/N): ").lower()
                if confirm == 'y': continue
                else:
                    input("\n  [Enter] Continue...")
                    continue
            
            print("\n⚠️  [CAUTION] Starting Dark Web Crawling...")
            
            # 스파이더 목록 조회 및 선택
            spiders = get_available_spiders()
            
            if not spiders:
                print("❌ No spiders found. Please check 'scrapy list'.")
                input("\n  [Enter] Continue...")
                continue

            if HAS_RICH:
                spider_table = Table(title="🕷️  Available Spiders", box=box.ROUNDED, border_style="green", title_style="bold cyan")
                spider_table.add_column("No.", style="cyan", justify="center")
                spider_table.add_column("Spider Name", style="bold white")
                
                for idx, s in enumerate(spiders, 1):
                    spider_table.add_row(str(idx), s)
                
                # Cancel row (Styled)
                spider_table.add_row("0", "[dim]Cancel (Return to Menu)[/dim]")
                
                console.print()
                console.print(spider_table)
            else:
                print("\n🕷️  Available Spiders:")
                for idx, s in enumerate(spiders, 1):
                    print(f"  [{idx}] {s}")
                print(f"  [0] Cancel")

            selected_spider = None
            while True:
                choice = input("\n  Select Spider (Index or Name): ").strip()
                if choice == '0':
                    selected_spider = None # Explicitly set None
                    break
                
                # 인덱스 선택
                if choice.isdigit() and 1 <= int(choice) <= len(spiders):
                    selected_spider = spiders[int(choice)-1]
                    break
                
                # 이름 직접 입력
                if choice in spiders:
                    selected_spider = choice
                    break
                    
                print("❌ Invalid selection.")

            if selected_spider:
                run_crawler(selected_spider)
                input("\n  [Enter] Continue...")
        
        elif cmd == '2':
            # Superset Dashboard (Moved to 2)
            try:
                client = SupersetDashboardMiddleware()
                url = client.get_url()
                print(f"\n🔬 Superset Dashboard: {url}")
                ok = client.open_dashboard()
                if not ok:
                    print("❌ 자동으로 브라우저를 열지 못했습니다. 위 URL을 직접 여세요.")
            except (ValueError, NameError) as e:
                # Middleware가 없거나 에러 발생 시 Fallback
                mode = os.getenv("TRICRAWL_SUPERSET_MODE", "cloud").lower()
                if mode == 'local':
                    print("\n[Local Mode] Superset URL: http://localhost:8088")
                else:
                     print(f"\n[{mode.upper()} Mode] Dashboard URL: (Check your cloud provider)")
            except Exception as e:
                print(f"❌ Error: {e}")
            input("\n  [Enter] Continue...")

        elif cmd == '3':
            # View Logs (Moved to 3)
            view_logs(50)
            input("\n  [Enter] Continue...")

        elif cmd == '4':
            # Export (Moved to 4)
            if not exporter:
                print("⚠️  Exporter module not loaded. Check dependencies.")
                continue
            
            jsonl_path = exporter.export_to_jsonl()
            
            if jsonl_path:
                print("\n엑셀(CSV)로도 변환하시겠습니까?")
                convert = input("  Convert to CSV? (Y/n): ").strip().lower()
                if convert in ('', 'y', 'yes'):
                    exporter.convert_to_csv(jsonl_path)
            
            input("\n  [Enter] Continue...")
            
        elif cmd == '5':
            # Start Docker (Moved to 5)
            start_docker()
            input("\n  [Enter] Continue...")
            
        elif cmd == '6':
            # Stop Docker (Moved to 6)
            stop_docker()
            input("\n  [Enter] Continue...")
            
        elif cmd == '7':
             # Toggle Discord (Moved to 7)
            DISCORD_ENABLED = not DISCORD_ENABLED
            
            try:
                env_path = PROJECT_ROOT / ".env"
                if env_path.exists():
                    lines = env_path.read_text(encoding="utf-8").splitlines()
                    new_lines = []
                    found = False
                    for line in lines:
                        if line.startswith("DISCORD_ENABLED="):
                            new_lines.append(f"DISCORD_ENABLED={str(DISCORD_ENABLED).lower()}")
                            found = True
                        else:
                            new_lines.append(line)
                    
                    if not found:
                        new_lines.append(f"DISCORD_ENABLED={str(DISCORD_ENABLED).lower()}")
                        
                    env_path.write_text("\n".join(new_lines), encoding="utf-8")
            except Exception as e:
                pass


        else:
            pass 


def main():
    """CLI 진입점. 서브커맨드에 따라 실행 흐름 분기."""
    parser = argparse.ArgumentParser(description="TriCrawl Admin CLI")
    subparsers = parser.add_subparsers(dest="command")
    
    subparsers.add_parser("interactive", aliases=["i"])
    subparsers.add_parser("status")
    
    # Docker
    docker = subparsers.add_parser("docker")
    docker.add_argument("action", choices=["start", "stop"])
    
    # Tools
    subparsers.add_parser("tor")
    subparsers.add_parser("webhook")
    subparsers.add_parser("logs")
    
    # Crawl
    crawl = subparsers.add_parser("crawl")
    crawl.add_argument("--spider", "-s", default="test")
    
    args = parser.parse_args()
    
    if args.command in [None, "interactive", "i"]:
        interactive_mode()
    elif args.command == "status":
        status()
    elif args.command == "docker":
        if args.action == "start": start_docker()
        elif args.action == "stop": stop_docker()
    elif args.command == "logs":
        view_logs(50)
    elif args.command == "crawl":
        run_crawler(args.spider)

if __name__ == "__main__":
    main()
