from __future__ import annotations

import os
import platform
import subprocess
import webbrowser
from pathlib import Path
from urllib.parse import quote

from matrix.daemon import server_url, start_server, stop_server
from matrix.settings import load_env, settings


def _notify(title: str, message: str) -> None:
    if platform.system() != "Darwin":
        return
    safe = message.replace('"', "'")[:200]
    subprocess.run(
        ["osascript", "-e", f'display notification "{safe}" with title "{title}"'],
        check=False,
    )


def build_ui_url(host: str, port: int, with_token: bool = True) -> str:
    url = server_url(host, port)
    if with_token:
        load_env()
        token = settings().api_token
        if token:
            url = f"{url}/?token={quote(token)}"
    return url


def _open_browser(host: str, port: int, with_token: bool = True, browser: str | None = None) -> str:
    url = build_ui_url(host, port, with_token=with_token)
    load_env()
    browser = browser or os.environ.get("MATRIX_BROWSER", "").strip()
    if browser:
        subprocess.run(["open", "-a", browser, url], check=False)
    else:
        subprocess.run(["open", url], check=False)
    return url


def open_matrix_app(host: str | None = None, port: int | None = None, stop_existing: bool = False) -> str:
    if platform.system() != "Darwin":
        raise RuntimeError("matrix app is macOS-only; use: matrix ui")

    load_env()
    cfg = settings()
    host = host or cfg.api_host
    port = port or cfg.api_port

    if stop_existing:
        stop_server()

    try:
        pid = start_server(host, port)
        opened = _open_browser(host, port)
        msg = f"MATRIX running (pid {pid}) → {opened}"
        _notify("MATRIX", "Opened in your browser")
        return msg
    except Exception as exc:
        err = str(exc)
        _notify("MATRIX failed", err)
        log_path = Path.home() / ".matrix" / "server.log"
        raise RuntimeError(f"{err}\nSee {log_path}") from exc


def install_app_bundle(project_root: str, dest: str | None = None) -> Path:
    from pathlib import Path
    import os

    root = Path(project_root).resolve()
    script = root / "scripts" / "build-macos-app.sh"
    if not script.is_file():
        raise FileNotFoundError(script)
    env = {}
    if dest:
        env["MATRIX_APP_DEST"] = dest
    subprocess.run(
        ["bash", str(script)],
        cwd=str(root),
        check=True,
        env={**os.environ, **env},
    )
    return Path(dest or Path.home() / "Applications") / "MATRIX.app"