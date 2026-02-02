"""
TriCrawl Data Exporter
Exports Supabase data to local JSONL/CSV files.
Uses Rich for progress visualization.
"""
import os
from datetime import datetime
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich import box
from supabase import create_client, Client

# 환경변수 로드
load_dotenv()

class DataExporter:
    def __init__(self):
        self.url = os.getenv("SUPABASE_URL")
        self.key = os.getenv("SUPABASE_KEY")
        self.console = Console()
        self.client: Client = None

        if self.url and self.key:
            try:
                self.client = create_client(self.url, self.key)
            except Exception as e:
                self.console.print(f"[red]❌ Supabase 연결 초기화 실패: {e}[/red]")

    def check_connection(self):
        if not self.client:
            self.console.print("[red]❌ Supabase 설정이 없습니다. .env 파일을 확인해주세요.[/red]")
            return False
        return True

    def export_to_jsonl(self):
        """DB 전체 데이터를 JSONL로 내보내기"""
        import json
        
        if not self.check_connection():
            return

        # 저장 경로
        data_dir = os.path.join(os.path.dirname(__file__), "data")
        os.makedirs(data_dir, exist_ok=True)
        
        filename = f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
        filepath = os.path.join(data_dir, filename)

        self.console.print(f"\n[bold cyan]💾 Supabase 데이터를 '{filename}'으로 내보냅니다...[/bold cyan]")

        try:
            total_count = 0
            page_size = 1000
            current_offset = 0
            
            with open(filepath, "w", encoding="utf-8") as f:
                with self.console.status("[bold green]데이터 다운로드 중...[/bold green]") as status:
                    while True:
                        # 페이징 처리 (1000건씩)
                        res = self.client.table("darkweb_leaks") \
                            .select("*") \
                            .order("posted_at", desc=True) \
                            .range(current_offset, current_offset + page_size - 1) \
                            .execute()
                        
                        rows = res.data
                        if not rows:
                            break
                        
                        for row in rows:
                            f.write(json.dumps(row, ensure_ascii=False) + "\n")
                        
                        count = len(rows)
                        total_count += count
                        current_offset += count
                        
                        status.update(f"[bold green]데이터 다운로드 중... ({total_count}건 저장)[/bold green]")
                        
                        if count < page_size:
                            break

            self.console.print(f"\n[bold green]✅ 내보내기 완료![/bold green]")
            self.console.print(f"📄 파일 위치: [underline]{filepath}[/underline]")
            self.console.print(f"📊 총 레코드: {total_count}건")

            # CSV 변환 제안
            return filepath

        except Exception as e:
            self.console.print(f"[bold red]❌ 내보내기 실패:[/bold red] {e}")
            if os.path.exists(filepath):
                os.remove(filepath)
            return None

    def convert_to_csv(self, jsonl_path):
        """JSONL 파일을 CSV로 변환 (UTF-8-SIG for Excel)"""
        import pandas as pd
        
        if not os.path.exists(jsonl_path):
            self.console.print(f"[red]❌ 파일이 없습니다: {jsonl_path}[/red]")
            return

        try:
            with self.console.status("[bold green]CSV 변환 중...[/bold green]"):
                df = pd.read_json(jsonl_path, lines=True)
                
                # 날짜 포맷 정리
                if 'posted_at' in df.columns:
                    df['posted_at'] = pd.to_datetime(df['posted_at']).dt.strftime('%Y-%m-%d %H:%M:%S')
                
                csv_path = jsonl_path.replace(".jsonl", ".csv")
                df.to_csv(csv_path, index=False, encoding="utf-8-sig")
            
            self.console.print(f"\n[bold green]✅ CSV 변환 완료![/bold green]")
            self.console.print(f"📄 파일 위치: [underline]{csv_path}[/underline]")
            

        except Exception as e:
            self.console.print(f"[bold red]❌ CSV 변환 실패:[/bold red] {e}")
