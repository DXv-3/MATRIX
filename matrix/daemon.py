from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from matrix.config import data_dir
from matrix.settings import load_env, settings

PID_FILE = data_dir() / "matrix-server.pid"


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex((host, port)) == 0


def _health_ok(host: str, port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/health", timeout=2) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def start_server(host: str | None = None, port: int | None = None) -> int:
    load_env()
    cfg = settings()
    host = host or cfg.api_host
    port = port or cfg.api_port

    data_dir().mkdir(parents=True, exist_ok=True)

    if _port_in_use(host, port) and _health_ok(host, port):
        return _read_pid() or 0

    if PID_FILE.is_file():
        try:
            old = int(PID_FILE.read_text(encoding="utf-8").strip())
            if _alive(old):
                if _port_in_use(host, port):
                    return old
                os.kill(old, signal.SIGTERM)
                time.sleep(0.3)
        except ValueError:
            PID_FILE.unlink(missing_ok=True)

    if _port_in_use(host, port):
        raise RuntimeError(
            f"Port {port} is in use but MATRIX health check failed. "
            f"Run: matrix stop  OR  lsof -i :{port}"
        )

    log = data_dir() / "server.log"
    script = _project_root() / "scripts" / "run-server.sh"
    if not script.is_file():
        raise FileNotFoundError(script)

    with open(log, "a", encoding="utf-8") as lf:
        proc = subprocess.Popen(
            ["/bin/bash", str(script)],
            stdout=lf,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            cwd=str(_project_root()),
        )
    PID_FILE.write_text(str(proc.pid), encoding="utf-8")

    for _ in range(30):
        time.sleep(0.2)
        if _health_ok(host, port):
            return proc.pid
        if proc.poll() is not None:
            PID_FILE.unlink(missing_ok=True)
            raise RuntimeError(f"Server failed to start; see {log}")

    raise RuntimeError(f"Server did not become healthy; see {log}")


def stop_server() -> bool:
    load_env()
    cfg = settings()
    stopped = False
    if PID_FILE.is_file():
        try:
            pid = int(PID_FILE.read_text(encoding="utf-8").strip())
            if _alive(pid):
                os.kill(pid, signal.SIGTERM)
                stopped = True
            PID_FILE.unlink(missing_ok=True)
        except ValueError:
            PID_FILE.unlink(missing_ok=True)

    if _port_in_use(cfg.api_host, cfg.api_port):
        try:
            out = subprocess.check_output(
                ["lsof", "-ti", f":{cfg.api_port}"],
                text=True,
            ).strip()
            for line in out.splitlines():
                if line.strip().isdigit():
                    os.kill(int(line.strip()), signal.SIGTERM)
                    stopped = True
        except (subprocess.CalledProcessError, OSError):
            pass
        time.sleep(0.3)
    return stopped


def _read_pid() -> int | None:
    if not PID_FILE.is_file():
        return None
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def server_url(host: str = "127.0.0.1", port: int = 8765) -> str:
    return f"http://{host}:{port}"