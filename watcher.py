"""File watcher with debounce."""

from __future__ import annotations

import time
from pathlib import Path
from threading import Lock, Timer
from typing import Callable, Literal

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from jalios_dev import log_watch
from jalios_dev.compile import compile_java_files
from jalios_dev.models import AppConfig, RuntimeState
from jalios_dev.server import start_server, stop_tomcat
from jalios_dev.sync import sync_changed_file, sync_plugin_to_webapp, sync_static_assets

IGNORE_DIRS = {".git", "bin", ".settings"}
IGNORE_EXTS = {".class", ".swp", ".swx", ".tmp"}
IGNORE_NAMES = {".project", ".classpath"}
_HANDLED_EVENTS = frozenset({"modified", "created", "moved"})

FileKind = Literal["java", "restart", "static"]
_observer: Observer | None = None
_COOLDOWN_SEC = 1.0

_RESTART_EXTS = {".xml", ".properties", ".prop"}


def _file_kind(path: Path) -> FileKind:
    ext = path.suffix.lower()
    if ext == ".java":
        return "java"
    if ext in _RESTART_EXTS:
        return "restart"
    return "static"


class DebouncedHandler(FileSystemEventHandler):
    def __init__(self, callback: Callable[[str], None], delay: float = 2.0):
        self._timer: Timer | None = None
        self._lock = Lock()
        self._callback = callback
        self._delay = delay
        self._pending_path: str | None = None
        self._cooldown_until = 0.0

    def on_any_event(self, event):
        if event.is_directory:
            return
        if event.event_type not in _HANDLED_EVENTS:
            return
        path = getattr(event, "dest_path", None) or event.src_path
        if self._should_ignore(path):
            return
        with self._lock:
            self._pending_path = path
            if self._timer:
                self._timer.cancel()
            self._timer = Timer(self._delay, self._dispatch)
            self._timer.start()

    def _should_ignore(self, path: str) -> bool:
        p = Path(path)
        if p.name in IGNORE_NAMES or p.name.endswith("~"):
            return True
        if p.suffix in IGNORE_EXTS:
            return True
        return any(part in IGNORE_DIRS for part in p.parts)

    def _dispatch(self) -> None:
        path = self._pending_path
        if not path:
            return
        now = time.monotonic()
        if now < self._cooldown_until:
            return
        try:
            self._callback(path)
        except Exception as exc:
            log_watch(f"error during dispatch: {exc}")
        finally:
            self._cooldown_until = time.monotonic() + _COOLDOWN_SEC
            with self._lock:
                self._pending_path = None


def _restart_after(
    config: AppConfig,
    state: RuntimeState,
    *,
    compile_files: list[Path] | None = None,
) -> None:
    stop_tomcat()
    if compile_files:
        compile_java_files(config, state, files=compile_files)
    sync_plugin_to_webapp(config, state)
    start_server(config)


def handle_change(path: str, config: AppConfig, state: RuntimeState) -> None:
    src = Path(path)
    name = src.name
    kind = _file_kind(src)

    if kind == "java":
        compile_java_files(config, state, files=[src])
        sync_plugin_to_webapp(config, state)
        if config.reloadable:
            log_watch(f"{name} changed — compiled, synced (reloadable=true)")
        else:
            log_watch(f"{name} changed — restarting server")
            stop_tomcat()
            start_server(config)
    elif kind == "restart":
        log_watch(f"{name} changed — sync, restart")
        _restart_after(config, state)
    else:
        log_watch(f"{name} changed — syncing")
        before = state.synced_files
        sync_static_assets(config, state)
        if state.synced_files == before:
            sync_changed_file(path, config, state)


def start_watcher(config: AppConfig, state: RuntimeState) -> Observer:
    global _observer
    handler = DebouncedHandler(
        lambda p: handle_change(p, config, state),
    )
    _observer = Observer()
    _observer.schedule(handler, str(config.plugin_project), recursive=True)
    _observer.start()
    return _observer


def stop_watcher() -> None:
    global _observer
    if _observer is not None:
        _observer.stop()
        _observer.join(timeout=5)
        _observer = None
