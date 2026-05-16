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
_LEVEL_STYLES = {
    "INFO": "blue",
    "WARN": "yellow",
    "ERROR": "red",
    "DEBUG": "magenta",
    "FATAL": "bold red",
}
_LEVEL_TOKEN_RE = re.compile(
    r"\[(INFO|WARN|ERROR|DEBUG|FATAL)\]|(?<![\w\[])\b(INFO|WARN|ERROR|DEBUG|FATAL)\b"
)
_EXCEPTION_RE = re.compile(
    r"^[ \t]*("
    r"[a-zA-Z0-9_.$]+Exception:"
    r"|[a-zA-Z0-9_.$]+Error:"
    r"|java\.[a-zA-Z0-9_.$]+Exception"
    r"|java\.[a-zA-Z0-9_.$]+Error"
    r"|Caused by:"
    r"|nested exception is:"
    r")"
)
_READY_RE = re.compile(
    r"jcms\.ChannelInitServlet.*is ready|is ready.*jcms\.ChannelInitServlet",
    re.IGNORECASE,
)


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


def _apply_level_tokens(line: str, default_style: str | None = None) -> Text:
    """Replace bare INFO with [INFO] (colored); other text uses default_style."""
    text = Text()
    last = 0
    for match in _LEVEL_TOKEN_RE.finditer(line):
        if match.start() > last:
            chunk = line[last : match.start()]
            text.append(chunk, style=default_style)
        level = match.group(1) or match.group(2)
        text.append(f"[{level}]", style=_LEVEL_STYLES[level])
        last = match.end()
    text.append(line[last:], style=default_style)
    return text


def _colorize_line(line: str) -> Text:
    if _READY_RE.search(line):
        return _apply_level_tokens(line, default_style="green")

    if _EXCEPTION_RE.match(line):
        return Text(line, style="bold red")

    if re.match(r"^[ \t]*at ", line):
        return Text(line, style="bright_black")

    if re.match(r"^[ \t]*\.\.\.[ \t]+[0-9]+[ \t]+more", line):
        return Text(line, style="bright_black")

    if _LEVEL_TOKEN_RE.search(line):
        return _apply_level_tokens(line)

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
