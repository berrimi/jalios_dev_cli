"""File watcher with debounce."""

from __future__ import annotations

import fnmatch
from pathlib import Path
from threading import Lock, Timer
from typing import Callable

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from jalios_dev import log_watch
from jalios_dev.compile import compile_java_files
from jalios_dev.models import AppConfig, RuntimeState
from jalios_dev.server import start_server, stop_tomcat
from jalios_dev.sync import sync_plugin_to_webapp

IGNORE_DIRS = {".git", "bin", ".settings"}
IGNORE_EXTS = {".class", ".swp", ".swx", ".tmp"}
IGNORE_NAMES = {".project", ".classpath"}

_observer: Observer | None = None


class DebouncedHandler(FileSystemEventHandler):
    def __init__(self, callback: Callable[[str], None], delay: float = 2.0):
        self._timer: Timer | None = None
        self._lock = Lock()
        self._callback = callback
        self._delay = delay

    def on_any_event(self, event):
        if event.is_directory:
            return
        if self._should_ignore(event.src_path):
            return
        with self._lock:
            if self._timer:
                self._timer.cancel()
            self._timer = Timer(
                self._delay, self._dispatch, args=[event.src_path]
            )
            self._timer.start()

    def _should_ignore(self, path: str) -> bool:
        p = Path(path)
        if p.name in IGNORE_NAMES or p.name.endswith("~"):
            return True
        if p.suffix in IGNORE_EXTS:
            return True
        return any(part in IGNORE_DIRS for part in p.parts)

    def _dispatch(self, path: str) -> None:
        try:
            self._callback(path)
        except Exception as exc:
            log_watch(f"error during dispatch: {exc}")


def handle_change(path: str, config: AppConfig, state: RuntimeState) -> None:
    name = Path(path).name
    is_restart = any(fnmatch.fnmatch(name, p) for p in config.restart_patterns)
    if is_restart:
        log_watch(f"{name} changed — restarting server")
        stop_tomcat()
        compile_java_files(config, state)
        sync_plugin_to_webapp(config, state)
        start_server(config)
    else:
        log_watch(f"{name} changed — syncing")
        sync_plugin_to_webapp(config, state)


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
