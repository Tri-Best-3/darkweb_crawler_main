"""
Superset Dashboard
- public Ip :  http://168.107.30.207:8088
"""

import os
import sys
import subprocess

class SupersetDashboardMiddleware:
    def __init__(self):
        self.mode = os.getenv("TRICRAWL_SUPERSET_MODE", "cloud").strip().lower()
        self.cloud_url = os.getenv("SUPERSET_CLOUD_URL", "").strip()
        self.local_url = os.getenv("SUPERSET_LOCAL_URL", "http://127.0.0.1:8088").strip()
        self.default_path = os.getenv("SUPERSET_DEFAULT_PATH", "/superset/welcome/").strip() or "/"

    def get_url(self) -> str:
        base = self.local_url if self.mode == "local" else self.cloud_url
        base = base.rstrip("/")
        path = self.default_path
        if not path.startswith("/"):
            path = "/" + path
        return base + path

    def open_dashboard(self) -> bool:
        url = self.get_url()
        if not url.startswith("http"):
            # cloud 모드인데 SUPERSET_CLOUD_URL이 비어있는 경우
            raise ValueError(f"Invalid Superset URL. Set SUPERSET_CLOUD_URL/SUPERSET_LOCAL_URL. current={url}")

        try:
            if os.name == "nt":
                os.startfile(url)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", url], check=False)
            else:
                subprocess.run(["xdg-open", url], check=False)
            return True
        except Exception:
            return False
