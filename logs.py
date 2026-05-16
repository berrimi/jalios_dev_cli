"""Server log tailing and colorization."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from rich.console import Console
from rich.text import Text

from jalios_dev import log_error, log_info
from jalios_dev.models import AppConfig

_console = Console()
_LEVELS = {
    "INFO": "blue",
    "WARN": "yellow",
    "ERROR": "red",
    "DEBUG": "magenta",
    "FATAL": "bold red",
}


def _resolve_log_path(config: AppConfig) -> Path | None:
    candidates = [
        config.webapp_project_root / "WEB-INF/data/logs/jcms.log",
    ]
    if config.catalina_base:
        candidates.append(config.catalina_base / "logs/catalina.out")
    candidates.append(config.tomcat_home / "logs/catalina.out")
    for path in candidates:
        if path.is_file():
            return path
    return None


def _colorize_line(line: str) -> Text:
    if "ChannelInitServlet" in line and "is ready" in line:
        return Text(line, style="green")

    if re.search(r"\w+Exception:", line) or "Caused by:" in line:
        return Text(line, style="bold red")

    if line.startswith("at com.") or line.startswith("at java."):
        return Text(line, style="dim")

    if re.search(r"\.\.\.\s+\d+\s+more", line):
        return Text(line, style="dim")

    for level, style in _LEVELS.items():
        if re.search(rf"\b{level}\b", line):
            return Text(line, style=style)

    return Text(line)


def _print_tail(path: Path, lines: int = 100) -> None:
    result = subprocess.run(
        ["tail", "-n", str(lines), str(path)],
        capture_output=True,
        text=True,
    )
    for line in result.stdout.splitlines():
        _console.print(_colorize_line(line))


def watch_server_logs(config: AppConfig) -> None:
    log_path = _resolve_log_path(config)
    if not log_path:
        log_error("Cannot find log file to watch")
        return

    log_info(f"Watching logs: {log_path}")
    _print_tail(log_path)

    proc = subprocess.Popen(
        ["tail", "-F", str(log_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        _console.print(_colorize_line(line.rstrip("\n")))
