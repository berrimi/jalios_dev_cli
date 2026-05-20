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
IGNORE_EXTS = {".class", ".swp", ".swx", ".swo", ".swn", ".tmp", ".bak"}
IGNORE_NAMES = {".project", ".classpath"}
_IGNORE_SUFFIXES = {"~"}
_HANDLED_EVENTS = frozenset({"modified", "created", "moved"})

FileKind = Literal["java", "restart", "static"]
_observer: Observer | None = None
_COOLDOWN_SEC = 1.0


def _build_restart_exts(config: AppConfig) -> set[str]:
    exts: set[str] = set()
    for pattern in config.restart_patterns:
        ext = Path(pattern).suffix.lower()
        if ext and ext != ".java":
            exts.add(ext)
    return exts or {".xml", ".properties", ".prop"}


def _file_kind(path: Path, restart_exts: set[str]) -> FileKind:
    ext = path.suffix.lower()
    if ext == ".java":
        return "java"
    if ext in restart_exts:
        return "restart"
    return "static"


class DebouncedHandler(FileSystemEventHandler):
    def __init__(self, callback: Callable[[str], None], delay: float = 2.0):
        self._timer: Timer | None = None
        self._lock = Lock()
        self._dispatch_lock = Lock()
        self._callback = callback
        self._delay = delay
        self._pending_paths: set[str] = set()
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
            self._pending_paths.add(path)
            if self._timer:
                self._timer.cancel()
            self._timer = Timer(self._delay, self._dispatch)
            self._timer.start()

    def _should_ignore(self, path: str) -> bool:
        p = Path(path)
        if p.name in IGNORE_NAMES:
            return True
        if p.name == "4913":
            return True
        if p.suffix in IGNORE_EXTS or p.suffix.endswith("~"):
            return True
        if any(p.name.endswith(s) for s in _IGNORE_SUFFIXES):
            return True
        return any(part in IGNORE_DIRS for part in p.parts)

    def _dispatch(self) -> None:
        with self._lock:
            paths = self._pending_paths.copy()
            self._pending_paths.clear()
        if not paths:
            return
        now = time.monotonic()
        if now < self._cooldown_until:
            with self._lock:
                self._pending_paths.update(paths)
                remaining = self._cooldown_until - now
                self._timer = Timer(remaining, self._dispatch)
                self._timer.start()
            return
        with self._dispatch_lock:
            for path in paths:
                try:
                    self._callback(path)
                except Exception as exc:
                    log_watch(f"error during dispatch: {exc}")
            self._cooldown_until = time.monotonic() + _COOLDOWN_SEC


def _restart_after(config: AppConfig, state: RuntimeState) -> None:
    stop_tomcat()
    sync_plugin_to_webapp(config, state)
    start_server(config)


def handle_change(path: str, config: AppConfig, state: RuntimeState) -> None:
    src = Path(path)
    name = src.name
    restart_exts = _build_restart_exts(config)
    kind = _file_kind(src, restart_exts)

    if kind == "java":
        ok = compile_java_files(config, state, files=[src])
        if not ok:
            log_watch(f"{name} compilation failed — skipping sync")
            return
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
