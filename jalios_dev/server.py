"""Tomcat start/stop."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

from jalios_dev import log_info, log_success, log_warning
from jalios_dev.config import CONFIG_PATH
from jalios_dev.models import AppConfig, ServerError

_BOOTSTRAP = "org.apache.catalina.startup.Bootstrap"
_SEARCH_PATHS = ("/opt/tomcat", "/usr/local/tomcat", "/usr/share/tomcat")


def _bootstrap_pids() -> list[int]:
    result = subprocess.run(
        ["pgrep", "-f", _BOOTSTRAP],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [int(p) for p in result.stdout.split() if p.strip()]


def find_tomcat_home(config: AppConfig) -> Path:
    home = config.tomcat_home
    if home and (home / "bin" / "catalina.sh").is_file():
        return home
    for path in _SEARCH_PATHS:
        candidate = Path(path)
        if (candidate / "bin" / "catalina.sh").is_file():
            return candidate
    raise ServerError(f"Set tomcat_home in {CONFIG_PATH}")


def stop_tomcat() -> None:
    pids = _bootstrap_pids()
    if not pids:
        log_info("Tomcat is not running")
        return

    log_info(f"Stopping Tomcat (PIDs: {pids}) with SIGTERM...")
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass

    for _ in range(15):
        pids = _bootstrap_pids()
        if not pids:
            log_success("Tomcat stopped gracefully")
            return
        time.sleep(1)

    log_warning("Tomcat didn't stop gracefully, sending SIGKILL...")
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    time.sleep(2)

    if _bootstrap_pids():
        raise ServerError("Failed to stop Tomcat")
    log_success("Tomcat killed")


def start_server(config: AppConfig) -> None:
    tomcat_home = find_tomcat_home(config)
    if _bootstrap_pids():
        log_warning("Tomcat already running — skipping start")
        return

    if config.catalina_base and config.catalina_base.exists():
        catalina_base = config.catalina_base
    else:
        catalina_base = tomcat_home

    env = {**os.environ, "CATALINA_BASE": str(catalina_base)}
    catalina = tomcat_home / "bin" / "catalina.sh"
    subprocess.Popen(
        [str(catalina), "start"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    for _ in range(30):
        if _bootstrap_pids():
            log_success("Tomcat server is running")
            return
        time.sleep(1)
    raise ServerError("Server startup failed after 30s")
