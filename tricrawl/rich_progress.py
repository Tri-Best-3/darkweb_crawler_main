"""
Rich Progress Bar Extension

Scrapy 크롤링 진행 상황을 시각적으로 표시하는 확장.
- 실시간 진행률 표시 (Items, Requests, Errors)
- 시작 시 설정 상태 표시 (Discord, Supabase 등)
- 최근 크롤링 데이터 한 줄 표시
- 완료 시 최종 통계 출력
"""
import os
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.console import Console, Group
from rich.panel import Panel
from rich.live import Live
from scrapy import signals
from scrapy.exceptions import NotConfigured


class RichProgress:
    """Scrapy 크롤링 진행 상황을 Rich Progress Bar로 표시."""

    def __init__(self, crawler):
        self.crawler = crawler
        self.stats = crawler.stats
        self.console = Console()
        
        # Progress Bar 설정
        self.progress = Progress(
            SpinnerColumn("dots"),  # 더 부드러운 스피너
            TextColumn("[bold cyan]{task.description}[/bold cyan]"),
            BarColumn(bar_width=25),
            TimeElapsedColumn(),
            TextColumn("{task.fields[info]}"),
            console=self.console,
            transient=False,
        )
        self.task_id = None
        
        # 상태 표시용
        self.last_item_text = "[dim]🔧 초기화 중...[/dim]"
        self.first_response = False  # 첫 응답 여부
        
        # Live 컨텍스트
        self.live = None

    @classmethod
    def from_crawler(cls, crawler):
        if not crawler.settings.getbool("RICH_PROGRESS_ENABLED", True):
            raise NotConfigured

        ext = cls(crawler)
        crawler.signals.connect(ext.spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(ext.spider_closed, signal=signals.spider_closed)
        crawler.signals.connect(ext.item_scraped, signal=signals.item_scraped)
        crawler.signals.connect(ext.item_dropped, signal=signals.item_dropped)
        crawler.signals.connect(ext.response_received, signal=signals.response_received)
        crawler.signals.connect(ext.request_scheduled, signal=signals.request_scheduled)
        return ext

    def _print_startup_status(self, spider):
        """시작 시 설정 상태 출력."""
        settings = self.crawler.settings
        
        # Discord 상태
        discord_url = settings.get("DISCORD_WEBHOOK_URL")
        discord_status = "[green]✓ 연결됨[/green]" if discord_url else "[yellow]⚠ 미설정[/yellow]"
        
        # Supabase 상태
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_status = "[green]✓ 연결됨[/green]" if supabase_url else "[red]✗ 미설정[/red]"
        
        # 중복 ID 로드 개수 (dedup pipeline에서 설정)
        loaded_ids = self.stats.get_value("dedup/loaded_ids", 0)
        dedup_status = f"[cyan]{loaded_ids:,}[/cyan]개" if loaded_ids else "[dim]0개[/dim]"
        
        # Log 파일 (경로 축약)
        log_file = settings.get("LOG_FILE", "")
        if log_file:
            log_file_display = "..." + str(log_file)[-35:] if len(str(log_file)) > 35 else str(log_file)
        else:
            log_file_display = "[dim]없음[/dim]"
        
        status_lines = [
            f"🕷️  [bold]스파이더:[/bold] {spider.name}",
            f"📢  [bold]디스코드 알림:[/bold] {discord_status}",
            f"💾  [bold]Supabase DB:[/bold] {supabase_status}",
            f"🔍  [bold]중복 ID 로드:[/bold] {dedup_status}",
            f"📝  [bold]로그 파일:[/bold] {log_file_display}",
        ]
        
        self.console.print(Panel(
            "\n".join(status_lines),
            title="[bold blue]🚀 Start Crawling[/bold blue]",
            border_style="blue",
            padding=(0, 1),
            width=50,
        ))

    def _build_display(self):
        """Progress Bar + 최근 아이템을 합친 표시 그룹 생성."""
        from rich.text import Text
        return Group(
            self.progress,
            Text.from_markup(f"  {self.last_item_text}"),
        )

    def spider_opened(self, spider):
        """스파이더 시작 시 상태 표시 및 Progress Bar 시작."""
        self._print_startup_status(spider)
        self.console.print()  # 빈 줄
        
        self.task_id = self.progress.add_task(
            "Crawling",
            total=None,
            info="[dim]Initializing...[/dim]"
        )
        
        # Live 컨텍스트 시작 (부드러운 업데이트)
        self.live = Live(
            self._build_display(),
            console=self.console,
            refresh_per_second=10,  # 초당 10회 업데이트
            transient=False,
        )
        self.live.start()

    def spider_closed(self, spider):
        """스파이더 종료 시 Progress Bar 정지 및 최종 통계 출력."""
        if self.live:
            self.live.stop()
        
        scraped = self.stats.get_value("item_scraped_count", 0)
        dropped = self.stats.get_value("item_dropped_count", 0)
        req_count = self.stats.get_value("downloader/request_count", 0)
        resp_count = self.stats.get_value("downloader/response_count", 0)
        err_count = self.stats.get_value("log_count/ERROR", 0)
        
        result_lines = [
            f"📦  [bold]수집:[/bold] [bold green]{scraped}[/bold green]건",
            f"🗑️   [bold]중복/필터:[/bold] {dropped}건",
            f"🌐  [bold]요청/응답:[/bold] {req_count}/{resp_count}",
            f"❌  [bold]에러:[/bold] [bold red]{err_count}[/bold red]건",
        ]
        
        self.console.print()
        self.console.print(Panel(
            "\n".join(result_lines),
            title="[bold green]✨ Crawling Completed[/bold green]",
            border_style="green",
            padding=(0, 1),
            width=40,
        ))

    def request_scheduled(self, request, spider):
        """요청 스케줄 시 상태 표시 (첫 요청 = Tor 연결 중)."""
        if not self.first_response:
            self.last_item_text = "[yellow]🌐 Tor 연결 중...[/yellow]"
            if self.live:
                self.live.update(self._build_display())

    def item_scraped(self, item, spider):
        """아이템 스크랩 시 상태 업데이트."""
        title = item.get("title", "")[:30]
        self.last_item_text = f"[cyan]⏳ 크롤링 중[/cyan] | [green]✅ 수집: {title}[/green]"
        self._update_status()

    def item_dropped(self, item, response, exception, spider):
        """아이템 드롭 시 상태 업데이트."""
        title = item.get("title", "")[:30] if hasattr(item, "get") else str(item)[:30]
        self.last_item_text = f"[cyan]⏳ 크롤링 중[/cyan] | [dim]🔄 스킵: {title}[/dim]"
        self._update_status()

    def response_received(self, response, request, spider):
        """응답 수신 시 상태 업데이트."""
        if not self.first_response:
            self.first_response = True
            self.last_item_text = "[cyan]⏳ 크롤링 중...[/cyan]"
        self._update_status()

    def _update_status(self):
        """Progress Bar 상태 텍스트 업데이트."""
        if self.task_id is None:
            return
            
        scraped = self.stats.get_value("item_scraped_count", 0)
        dropped = self.stats.get_value("item_dropped_count", 0)
        req_count = self.stats.get_value("downloader/request_count", 0)
        err_count = self.stats.get_value("log_count/ERROR", 0)

        info_text = (
            f"📦 [green]{scraped}[/green] | "
            f"🗑️ {dropped} | "
            f"🌐 {req_count} | "
            f"❌ [red]{err_count}[/red]"
        )

        self.progress.update(self.task_id, info=info_text)
        
        # Live 컨텍스트 업데이트
        if self.live:
            self.live.update(self._build_display())

