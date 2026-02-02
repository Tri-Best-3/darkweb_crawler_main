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
import json
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


def _extract_stats_from_log(log_file, last_run_only=False):
    """
    Scrapy 로그 파일에서 주요 통계를 추출.

    - 로그가 dictionary 형태로 출력된 라인에서 숫자만 파싱
    - 없으면 빈 dict 반환
    - last_run_only=True면 마지막 실행(Run: ...) 이후의 로그만 분석
    """
    try:
        text = log_file.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return {}

    if last_run_only:
        # 마지막 "Run:" 마커 이후만 자르기
        # 마커 예시: "==================== Run: spider_name at ... ===================="
        last_marker_idx = text.rfind("Run: ")
        if last_marker_idx != -1:
            # 마커가 있는 줄의 시작부터 자르지 않고, 그냥 마커 위치부터 끝까지 사용해도 통계 추출엔 문제 없음
            text = text[last_marker_idx:]

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


def run_all_spiders(confirm_promt=True, log_file=None):
    """등록된 모든 스파이더를 순차적으로 실행."""
    spiders = get_available_spiders()
    if not spiders:
        print("❌ 실행할 스파이더가 없습니다.")
        return

    print("\n" + "="*60)
    print(f"📢  [NOTICE] 전체 스파이더 실행 ({len(spiders)}개)")
    print("    예상 소요 시간: 매우 오래 걸릴 수 있습니다.")
    print("    중단하려면 Ctrl+C를, 강제 종료하려면 터미널을 닫으세요.")
    print("="*60 + "\n")
    
    if confirm_promt:
        confirm = input("정말 진행하시겠습니까? (y/N): ").lower()
        if confirm != 'y':
            print("취소되었습니다.")
            return

    total_start = time.time()
    
    # log_file이 있으면 append_log=True
    do_append = bool(log_file)
    
    for idx, spider in enumerate(spiders, 1):
        if HAS_RICH:
            console.rule(f"[bold magenta]({idx}/{len(spiders)}) Running Spider: {spider}[/bold magenta]")
        else:
            print(f"\n>>> ({idx}/{len(spiders)}) Running Spider: {spider} <<<\n")
        
        run_crawler(spider, log_file=log_file, append_log=do_append)
        time.sleep(2) # 쿨다운

    total_elapsed = format_duration(time.time() - total_start)
    print("\n" + "="*60)
    print(f"✅  모든 배치 작업 완료! (총 소요 시간: {total_elapsed})")
    print("="*60 + "\n")


def monitoring_menu():
    """2. 모니터링 모드 (구 스케줄러)"""
    config_path = PROJECT_ROOT / "config" / "scheduler_state.json"
    
    def load_config():
        default = {
            "interval_hours": 1, 
            "target": "ALL", 
            "ref_start_time": None, # "YYYY-MM-DD HH:MM"
            "cycle_count": 0
        }
        if not config_path.exists():
            return default
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return default

    def save_config(conf):
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(conf, f, indent=2)
        except Exception as e:
            print(f"❌ Config Save Error: {e}")

    config = load_config()
    
    # 기본값 보정
    if "interval_hours" not in config: config["interval_hours"] = 1
    if "target" not in config: config["target"] = "ALL"
    if "ref_start_time" not in config: config["ref_start_time"] = None
    
    # 오늘 오전 10시를 기본 기준시간으로 제안
    today_10am = time.strftime("%Y-%m-%d 10:00")

    while True:
        clear_screen()
        
        curr_interval = config["interval_hours"]
        curr_target = config["target"]
        curr_ref = config["ref_start_time"] if config.get("ref_start_time") else "Not Set (Start Now)"
        
        if HAS_RICH:
            # Main Menu와 유사한 Layout 적용 (Grid + Table)
            grid = Table.grid(padding=(0, 2))
            grid.add_column(justify="left")
            
            # 상단: 현재 설정 상태 (Panel로 감싸서 강조)
            config_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
            config_table.add_column("Key", style="bold cyan", justify="right")
            config_table.add_column("Value", style="yellow")
            
            config_table.add_row("Target (타겟)", f"{curr_target}")
            config_table.add_row("Interval (주기)", f"{curr_interval} Hours")
            config_table.add_row("Start At (기준)", f"{curr_ref}")
            
            config_panel = Panel(
                config_table,
                title="📡 Current Configuration",
                border_style="cyan",
                width=60,
                subtitle=f"[dim]Every {curr_interval}h starting from {curr_ref.split(' ')[-1] if ' ' in curr_ref else 'Now'}[/dim]"
            )

            # 하단: 메뉴 옵션 (Table)
            menu_table = Table(box=box.SIMPLE, show_header=True, header_style="bold magenta", width=60)
            menu_table.add_column("🔢 Option", justify="center", width=10)
            menu_table.add_column("📝 Description", justify="left")
            
            menu_table.add_row("[bold]1[/bold]", "🎯 Set Target [dim](Spider)[/dim]")
            menu_table.add_row("[bold]2[/bold]", "⏰ Set Interval [dim](1h/2h/4h...)[/dim]")
            menu_table.add_row("[bold]3[/bold]", "🚀 Set Reference Time [dim](Future Start)[/dim]")
            menu_table.add_row("", "") # Spacer
            menu_table.add_row("[bold cyan]4[/bold cyan]", "[bold cyan]🚀 Start Monitoring Loop[/bold cyan]")
            menu_table.add_row("[bold]0[/bold]", "🔙 Back to Main Menu")

            # 출력
            console.print(config_panel)
            console.print(menu_table)
            console.print()

        else:
            print("\n📡 모니터링 설정 (Monitoring Config)")
            print(f"  Target  : {curr_target}")
            print(f"  Interval: {curr_interval} Hours")
            print(f"  Start At: {curr_ref}")
            
            print("\n[설정 옵션]")
            print("  1. 🎯 타겟 설정 (Target)")
            print("  2. ⏰ 주기 설정 (Interval)")
            print("  3. 🚀 기준 시작 시간 (Start Time)")
            print("  4. 🚀 모니터링 시작 (Start Loop)")
            print("  0. 뒤로 가기 (Back)")

        choice = input("Select Option > ").strip()

        if choice == '0':
            break
            
        elif choice == '1':
            spiders = get_available_spiders()
            
            if HAS_RICH:
                table = Table(title="🎯 Available Spiders", box=box.SIMPLE)
                table.add_column("No.", style="cyan", justify="right")
                table.add_column("Spider Name", style="bold white")
                
                table.add_row("a", "ALL (Default)")
                for idx, s in enumerate(spiders, 1):
                    table.add_row(str(idx), s)
                
                console.print(table)
            else:
                print("\n[타겟 선택]")
                print("  a. 전체 (ALL) - 기본값")
                for idx, s in enumerate(spiders, 1):
                    print(f"  {idx}. {s}")
            
            sel = input("Select Target (No./a): ").strip().lower()
            if sel == 'a':
                config["target"] = "ALL"
            elif sel.isdigit() and 1 <= int(sel) <= len(spiders):
                config["target"] = spiders[int(sel)-1]
            else:
                config["target"] = "ALL"
            save_config(config)

        elif choice == '2':
            options = [1, 2, 4, 8, 24]
            
            if HAS_RICH:
                table = Table(title="⏰ Select Interval", box=box.SIMPLE)
                table.add_column("No.", style="cyan", justify="right")
                table.add_column("Interval", style="bold yellow")
                
                for i, opt in enumerate(options, 1):
                    table.add_row(str(i), f"{opt} Hour(s)")
                console.print(table)
            else:
                print("\n[주기 선택 (시간 단위)]")
                for i, opt in enumerate(options, 1):
                    print(f"  {i}. {opt}시간")
            
            sel = input("Select Interval (No.): ").strip()
            if sel.isdigit() and 1 <= int(sel) <= len(options):
                config["interval_hours"] = options[int(sel)-1]
                save_config(config)
            else:
                print("❌ Invalid Selection")
                time.sleep(1)

        elif choice == '3':
            print(f"\nExample: {today_10am}")
            inp = input("Enter Start Time (YYYY-MM-DD HH:MM) [Enter to skip]: ").strip()
            if inp:
                try:
                    time.strptime(inp, "%Y-%m-%d %H:%M")
                    config["ref_start_time"] = inp
                    save_config(config)
                except ValueError:
                    print("❌ Invalid Format.")
                    time.sleep(1)
            else:
                config["ref_start_time"] = None
                save_config(config)

        elif choice == '4':
            run_monitoring_loop(config)
            config = load_config()

def run_monitoring_loop(config):
    """실제 모니터링 루프 실행 (Dashboard UI)."""
    import datetime
    
    interval_hours = config["interval_hours"]
    target = config["target"]
    ref_time_str = config.get("ref_start_time")
    
    clear_screen()
    
    if HAS_RICH:
        console.print("[bold green]🚀 Initializing...[/bold green]")
    else:
        print("🚀 Initializing...")

    # 기준 시간 파싱 및 다음 실행 시간 계산
    now = datetime.datetime.now()
    
    if ref_time_str:
        ref_time = datetime.datetime.strptime(ref_time_str, "%Y-%m-%d %H:%M")
    else:
        ref_time = now 
    
    next_run = ref_time
    while next_run <= now:
        next_run += datetime.timedelta(hours=interval_hours)
    
    cycle_count = config.get("cycle_count", 0)

    try:
        from rich.live import Live
        from rich.layout import Layout
        from rich.align import Align
        from rich.text import Text
        
        # 메인 루프 (Live Dashboard)
        with Live(refresh_per_second=1, screen=True) as live: 
            # screen=True로 해서 전체 화면 모드 (깔끔함) -> 사용자 요청 반영 ("꽉 차보이는거 싫음"이면 False가 나을수도 있으나 screen=True가 몰입감은 좋음)
            # 사용자가 "너무 넓다"고 했으니 screen=False 유지하되 Align.center 사용
            pass
        
        # Live를 다시 구성 (screen=False)
        with Live(refresh_per_second=1) as live:
            while True:
                now = datetime.datetime.now()
                
                today_str = datetime.date.today().strftime("%Y-%m-%d")
                log_filename = f"monitoring_{today_str}.log"
                host_log_display = f"tricrawl/logs/{log_filename}"
                
                # 남은 시간 계산
                if now >= next_run:
                    wait_str = "🚀 Launching..."
                    status_color = "red"
                else:
                    diff = next_run - now
                    total_seconds = int(diff.total_seconds())
                    hours, remainder = divmod(total_seconds, 3600)
                    minutes, seconds = divmod(remainder, 60)
                    wait_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                    status_color = "green"

                if HAS_RICH:
                    # Dashboard Layout (Centered, Fixed Width)
                    
                    # 1. Info Table
                    info_table = Table(box=box.SIMPLE, show_header=False, padding=(0,1), width=50)
                    info_table.add_column("Label", justify="right", style="cyan")
                    info_table.add_column("Value", justify="left", style="white")
                    
                    info_table.add_row("Target:", f"[yellow]{target}[/yellow]")
                    info_table.add_row("Interval:", f"{interval_hours} Hours")
                    info_table.add_row("Cycles:", f"{cycle_count}")
                    info_table.add_row("Log File:", f"[dim]{host_log_display}[/dim]")

                    # 2. Main Countdown (Progress Bar + Big Text)
                    # 전체 주기(초) 계산
                    interval_seconds = interval_hours * 3600
                    # 남은 시간(초) -> Wait Str은 위에서 계산됨
                    
                    # 진행률 (시간이 흐를수록 참 -> 100% 도달 시 실행)
                    completed = interval_seconds - diff.total_seconds()
                    
                    # Rich Progress Bar Configuration
                    from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn
                    
                    # 수동으로 Progress Bar 렌더링 (Live 내부에서)
                    # 여기서는 간단히 Text Bar와 Big Font 효과를 흉내냄
                    
                    # Big Counter Text
                    counter_panel_content = Text(wait_str, style=f"bold {status_color}" if status_color == "green" else "bold red blink", justify="center")
                    # 폰트 사이즈 키우는건 터미널 지원 한계가 있으므로, 별와 공백으로 강조
                    
                    if status_color == "green":
                         pass
                    else:
                         pass

                    # Panel Composition
                    dashboard_grid = Table.grid(padding=1)
                    dashboard_grid.add_column(justify="center")
                    
                    # 카운트다운 패널 (크게)
                    dashboard_grid.add_row(Panel(
                        Align.center(
                             Text.assemble(
                                 (f"\n{wait_str}\n", f"bold {status_color}"),
                                 justify="center"
                             )
                        ),
                        title="⏳ Next Run Countdown", 
                        border_style=status_color, 
                        width=54, 
                        padding=(0,2)
                    ))
                    
                    dashboard_grid.add_row(Panel(info_table, title="📊 Status", border_style="cyan", width=54))
                    
                    # Final Output
                    live.update(
                        Panel(dashboard_grid, title="📡 Monitoring Dashboard", border_style="bold green", subtitle="[dim]Press Ctrl+C to stop[/dim]", padding=(1,2), width=60)
                    )
                else:
                    pass

                # 실행 시점 체크
                if now >= next_run:
                    if HAS_RICH: live.stop()
                    
                    print(f"\n\n[{now.strftime('%H:%M:%S')}] 🚀 Running Scheduler Job (Cycle: {cycle_count + 1})")
                    log_file_path = LOG_DIR / log_filename
                    
                    if target == "ALL":
                        run_all_spiders(confirm_promt=False, log_file=log_file_path)
                    else:
                        run_crawler(target, log_file=log_file_path, append_log=True)
                    
                    cycle_count += 1
                    config["cycle_count"] = cycle_count
                    
                    next_run += datetime.timedelta(hours=interval_hours)
                    while next_run <= datetime.datetime.now():
                         next_run += datetime.timedelta(hours=interval_hours)
                    

                    
                    print(f"✅ Finished. Next: {next_run.strftime('%H:%M:%S')}")
                    time.sleep(3) 
                    
                    clear_screen()
                    if HAS_RICH: live.start()

                time.sleep(1)

    except KeyboardInterrupt:
        print("\n\n🛑 모니터링이 사용자에 의해 중단되었습니다.")
        time.sleep(1)
    except Exception as e:
        print(f"\n❌ 모니터링 중 치명적 오류 발생: {e}")
        input("엔터를 눌러 복귀...")

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


def run_crawler(spider="test", limit=None, log_file=None, append_log=False):
    """
    Scrapy 크롤러 실행 래퍼.
    
    Args:
        spider (str): 스파이더 이름
        limit (int): (Deprecated)
        log_file (Path, optional): 로그 파일 경로. None이면 last_run.log 사용.
        append_log (bool): True면 로그 파일을 초기화하지 않고 이어씀.
    """
    # 기본 로그 파일 설정
    if not log_file:
        log_file = LOG_DIR / "last_run.log"
    log_file = Path(log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # config 로드 (days_limit 등)
    config_path = PROJECT_ROOT / "config" / "crawler_config.yaml"
    days_limit = 3
    timeout = 60
    retries = 2

    if config_path.exists():
        import yaml
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                conf = yaml.safe_load(f) or {}
                # Global Config
                global_conf = conf.get("global", {})
                days_limit = global_conf.get("days_to_crawl", 3)
                default_timeout = global_conf.get("timeout_seconds", 60)
                default_retries = global_conf.get("max_retries", 2)
                
                # Spider Specific Config
                spider_conf = conf.get("spiders", {}).get(spider, {})
                timeout = spider_conf.get("timeout_seconds", default_timeout)
                retries = spider_conf.get("max_retries", default_retries)

        except Exception as e:
            print(f"??  Config Load Error: {e}")

    # 시작 정보 출력
    print()  

    if shutil.which("scrapy") is None:
        pass 
    
    start_time = time.time()
    original_cwd = Path.cwd()
    os.chdir(TRICRAWL_DIR) 
    
    try:
        # 1. 로그 파일 초기화 (append_log=False일 때만)
        if not append_log:
            try:
                log_file.write_text("", encoding="utf-8")
            except Exception:
                pass
        else:
            # 이어쓰기 모드: 구분선 추가
            try:
                with open(log_file, "a", encoding="utf-8") as f:
                    ts = time.strftime("%Y-%m-%d %H:%M:%S")
                    f.write(f"\n{'='*20} Run: {spider} at {ts} {'='*20}\n")
            except Exception:
                pass


        # 2. Docker Command 구성 (docker-compose run)
        # 컨테이너 내부 경로로 변환 (tricrawl/logs/... -> /app/tricrawl/logs/...)
        try:
            rel_path = log_file.relative_to(PROJECT_ROOT)
            docker_log_path = f"/app/{rel_path.as_posix()}"
        except ValueError:
            docker_log_path = "/app/tricrawl/logs/last_run.log"

        cmd = [
            "docker-compose", 
            "run", 
            "--rm",
            "crawler", 
            "scrapy", 
            "crawl", 
            spider,
            "-a", f"days_limit={days_limit}",
            "-s", f"DOWNLOAD_TIMEOUT={timeout}",
            "-s", f"RETRY_TIMES={retries}"
        ]
        
        if not DISCORD_ENABLED:
            cmd.extend(["-s", "DISCORD_WEBHOOK_URL="])
            
        # 환경변수 전달
        env_args = [
            "-e", f"TRICRAWL_LOG_FILE={docker_log_path}",
            "-e", "TERM=xterm-256color",
            "-e", "PYTHONIOENCODING=utf-8"
        ]
        
        final_cmd = cmd[:3] + env_args + cmd[3:]

        if HAS_RICH and not append_log: 
             console.print(f"[dim]Command: {' '.join(final_cmd)}[/dim]")
              
        if HAS_RICH:
            # 타임아웃/재시도 정보 표시 (디버깅용)
            console.print(f"[bold cyan]🚀 Spider '{spider}' 실행 중...[/bold cyan] [dim](Timeout: {timeout}s, Retries: {retries})[/dim]")
            
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
            summary_lines.append(f"크롤링 완료: {spider}")
        else:
            summary_lines.append(f"크롤링 종료 (코드: {exit_code})")
        summary_lines.append(f"소요 시간: {elapsed}")
        
        # 3. 로그 분석
        stats = _extract_stats_from_log(log_file, last_run_only=append_log) 

        if stats:
            if "item_scraped_count" in stats:
                summary_lines.append(f"수집: {stats['item_scraped_count']}")
            if "item_dropped_count" in stats:
                summary_lines.append(f"필터/중복 제외: {stats['item_dropped_count']}")
            if "log_count/ERROR" in stats:
                 summary_lines.append(f"에러: {stats['log_count/ERROR']}")

        summary_lines.append(f"로그 파일: {log_file.name}")
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
        print("\n중단됨")
    except Exception as e:
        print(f"\n실행 오류: {e}")
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
        table_left.add_row("[bold magenta]2[/bold magenta]. 📡 Monitoring Mode [dim](Auto Schedule)[/dim]")
        table_left.add_row("[bold magenta]3[/bold magenta]. 🔬 Open Dashboard [dim](Superset)[/dim]")
        table_left.add_row("[bold magenta]4[/bold magenta]. 📄 View Logs [dim](Notepad)[/dim]")

        # 오른쪽: 시스템 관리 (System & Tools)
        table_right = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
        table_right.add_column("🛠️ System & Tools")

        table_right.add_row("[bold cyan]5[/bold cyan]. 🐳 Start Docker [dim](System Up)[/dim]")
        table_right.add_row("[bold cyan]6[/bold cyan]. 🛑 Stop Docker [dim](System Down)[/dim]")
        table_right.add_row("[bold cyan]7[/bold cyan]. 💾 Export DB [dim](JSONL/CSV)[/dim]")
        table_right.add_row(f"[bold cyan]8[/bold cyan]. 🔔 Toggle Discord [dim]({'ON' if DISCORD_ENABLED else 'OFF'})[/dim]")

        # Grid에 추가
        grid.add_row(table_left, table_right)
        
        # 하단 종료 메뉴
        console.print(grid)
        console.print("\n[dim]Press [bold]q[/bold] to Quit[/dim]")
        console.print()
    else:
        print("╭────┬────────────────────────────────┬────┬────────────────────────────────╮")
        print("│ 1  │ 🌑 Start Crawl                 │ 5  │ 🐳 Start Docker                │")
        print("│ 2  │ 📡 Monitoring Mode             │ 6  │ 🛑 Stop Docker                 │")
        print("│ 3  │ 🔬 Open Dashboard              │ 7  │ 💾 Export DB                   │")
        print("│ 4  │ 📄 View Logs                   │ 8  │ 🔔 Toggle Discord              │")
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
            # Dark Web Crawl
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
                
                spider_table.add_row("a", "[bold yellow]Run All Spiders (All)[/bold yellow]")
                # Cancel row (Styled)
                spider_table.add_row("0", "[dim]Cancel (Return to Menu)[/dim]")
                
                console.print()
                console.print(spider_table)
            else:
                print("\n🕷️  Available Spiders:")
                for idx, s in enumerate(spiders, 1):
                    print(f"  [{idx}] {s}")
                print(f"  [a] Run All Spiders")
                print(f"  [0] Cancel")

            selected_spider = None
            while True:
                choice = input("\n  Select Spider (Index or Name): ").strip()
                if choice == '0':
                    selected_spider = None
                    break
                
                if choice.lower() == 'a':
                    selected_spider = "ALL"
                    break

                if choice.isdigit() and 1 <= int(choice) <= len(spiders):
                    selected_spider = spiders[int(choice)-1]
                    break
                
                if choice in spiders:
                    selected_spider = choice
                    break
                    
                print("❌ Invalid selection.")

            if selected_spider:
                if selected_spider == "ALL":
                    run_all_spiders()
                else:
                    run_crawler(selected_spider)
                input("\n  [Enter] Continue...")
        
        elif cmd == '2':
            # Monitoring Mode (New)
            monitoring_menu()

        elif cmd == '3':
            # Open Dashboard (Moved from 2)
            try:
                client = SupersetDashboardMiddleware()
                url = client.get_url()
                print(f"\n🔬 Superset Dashboard: {url}")
                ok = client.open_dashboard()
                if not ok:
                    print("❌ 자동으로 브라우저를 열지 못했습니다. 위 URL을 직접 여세요.")
            except (ValueError, NameError) as e:
                print(f"❌ 오류: {e}")
                print("Superset 미들웨어 초기화 실패. .env 설정을 확인하세요.")
            input("\n  [Enter] Continue...")

        elif cmd == '4':
            # View Logs (Moved from 3)
            view_logs()

        elif cmd == '5':
            # Start Docker
            start_docker()
            input("\n  [Enter] Continue...")

        elif cmd == '6':
            # Stop Docker
            stop_docker()
            input("\n  [Enter] Continue...")

        elif cmd == '7':
             # Export DB (Moved from 4)
            if exporter:
                print("\n💾 Exporting data from Supabase...")
                try:
                    jsonl_path = exporter.export_to_jsonl()
                    if jsonl_path:
                        exporter.convert_to_csv(jsonl_path)
                    print("✅ Export completed (check 'tricrawl/data').")
                except Exception as e:
                    print(f"❌ Export failed: {e}")
            else:
                print("\n❌ Exporter module not loaded.")
            input("\n  [Enter] Continue...")
            
        elif cmd == '8':
            # Toggle Discord
            global DISCORD_ENABLED
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
            except Exception:
                pass
            
            status_text = "ON" if DISCORD_ENABLED else "OFF"
            print(f"\n🔔 Discord Notifications: {status_text}")
            time.sleep(1)


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
