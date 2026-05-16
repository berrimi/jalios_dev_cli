"""Jalios dev tool — terminal logging."""

from __future__ import annotations

import time
from pathlib import Path

from rich.console import Console

_console = Console()
_log_file: Path | None = None


def init_logging() -> Path:
    global _log_file
    _log_file = Path(f"/tmp/jalios_sync_{int(time.time())}.log")
    return _log_file


def _write(rich_msg: str, plain_msg: str) -> None:
    _console.print(rich_msg)
    if _log_file:
        with _log_file.open("a", encoding="utf-8") as fh:
            fh.write(plain_msg + "\n")


def log_info(msg: str) -> None:
    _write(f"[blue][INFO][/blue] {msg}", f"[INFO] {msg}")


def log_success(msg: str) -> None:
    _write(f"[green][SUCCESS][/green] {msg}", f"[SUCCESS] {msg}")


def log_error(msg: str) -> None:
    _write(f"[red][ERROR][/red] {msg}", f"[ERROR] {msg}")


def log_warning(msg: str) -> None:
    _write(f"[yellow][WARN][/yellow] {msg}", f"[WARN] {msg}")


def log_sync(msg: str) -> None:
    _write(f"[cyan][SYNC][/cyan] {msg}", f"[SYNC] {msg}")


def log_watch(msg: str) -> None:
    _write(f"[magenta][WATCH][/magenta] {msg}", f"[WATCH] {msg}")
