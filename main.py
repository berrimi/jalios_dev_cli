"""CLI entrypoint."""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

from jalios_dev import (
    init_logging,
    log_error,
    log_info,
    log_success,
    log_warning,
)
from jalios_dev.compile import compile_java_files
from jalios_dev.config import load_config, validate_config
from jalios_dev.logs import watch_server_logs
from jalios_dev.models import AppConfig, ConfigError, JaliosError, RuntimeState
from jalios_dev.server import start_server, stop_tomcat
from jalios_dev.sync import sync_plugin_to_webapp
from jalios_dev import watcher as watcher_mod

_CONFIG: AppConfig | None = None
_SYNC_CONF_NAMES = ("sync.conf", ".sync.conf", ".sync.properties")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    args = argv if argv is not None else sys.argv[1:]
    command = "preview"
    remaining: list[str] = []
    for arg in args:
        if arg in ("preview", "sync", "run"):
            command = arg
        else:
            remaining.append(arg)

    parser = argparse.ArgumentParser(prog="jalios")
    parser.add_argument("-p", "--plugin", type=Path, default=None)
    parser.add_argument("-w", "--webapp", type=Path, default=None)
    parser.add_argument("-v", "--verbose", action="store_true")
    ns = parser.parse_args(remaining)
    ns.command = command
    return ns


def _resolve_path(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_dir():
        raise ConfigError(f"{label} directory not found: {resolved}")
    return resolved


def _find_sync_conf(webapp: Path) -> Path | None:
    for name in _SYNC_CONF_NAMES:
        candidate = webapp / name
        if candidate.is_file():
            return candidate
    return None


def _parse_sync_conf(config: AppConfig) -> None:
    conf = _find_sync_conf(config.webapp_project)
    if not conf:
        config.webapp_project_root = config.webapp_project
        return

    config_dir = conf.parent
    config.webapp_project_root = config_dir
    for line in conf.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("root.dir"):
            continue
        root_dir = line.split("=", 1)[-1].strip().strip("\r")
        if not root_dir:
            continue
        actual = config_dir / root_dir
        if actual.is_dir():
            config.webapp_project_root = actual
        else:
            log_warning(f"Webapp root directory not found: {actual}")
        break


def _print_banner() -> None:
    log_info("Jalios Plugin Project Sync Tool")


def _print_report(config: AppConfig, state: RuntimeState) -> None:
    duration_ms = int((time.time() - state.start_time) * 1000)
    mode = "PREVIEW" if config.preview_mode else "REAL SYNC"
    lines = [
        "-----------------------------------------------------------",
        "Sync Report",
        "-----------------------------------------------------------",
        f"Plugin Project : {config.plugin_project}",
        f"Webapp Project : {config.webapp_project}",
        f"Sync Target    : {config.webapp_project_root}",
        f"Mode           : {mode}",
        "-----------------------------------------------------------",
        f"Files synced   : {state.synced_files}",
        f"Files compiled : {state.compiled_files}",
        f"Duration       : {duration_ms}ms",
        "-----------------------------------------------------------",
    ]
    for line in lines:
        print(line)

    if config.preview_mode:
        log_warning("This is only a PREVIEW. Nothing has been changed.")
        log_info("Use 'jalios sync' to perform actual synchronization.")
    else:
        log_success("Sync completed successfully!")


def _startup(args: argparse.Namespace) -> tuple[AppConfig, RuntimeState]:
    log_path = init_logging()
    config = load_config(args.plugin, args.webapp)
    validate_config(config)
    config.plugin_project = _resolve_path(config.plugin_project, "Plugin project")
    config.webapp_project = _resolve_path(config.webapp_project, "Webapp project")
    _parse_sync_conf(config)
    state = RuntimeState(start_time=time.time())
    _print_banner()
    log_info(f"Session log: {log_path}")
    if args.verbose:
        log_info("Verbose mode enabled")
    return config, state


def _cmd_preview(config: AppConfig, state: RuntimeState) -> None:
    config.preview_mode = True
    sync_plugin_to_webapp(config, state)
    _print_report(config, state)


def _cmd_sync(config: AppConfig, state: RuntimeState) -> None:
    config.preview_mode = False
    compile_java_files(config, state)
    sync_plugin_to_webapp(config, state)
    _print_report(config, state)


def _cleanup(sig, frame) -> None:
    log_info("Interrupted — cleaning up")
    watcher_mod.stop_watcher()
    stop_tomcat()
    log_info("Cleanup complete")
    sys.exit(0)


def _cmd_run(config: AppConfig, state: RuntimeState) -> None:
    global _CONFIG
    _CONFIG = config
    config.preview_mode = False
    stop_tomcat()
    compile_java_files(config, state)
    sync_plugin_to_webapp(config, state)
    _print_report(config, state)
    start_server(config)
    watcher_mod.start_watcher(config, state)
    signal.signal(signal.SIGINT, _cleanup)
    signal.signal(signal.SIGTERM, _cleanup)
    watch_server_logs(config)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    try:
        config, state = _startup(args)
        if args.command == "preview":
            _cmd_preview(config, state)
        elif args.command == "sync":
            _cmd_sync(config, state)
        else:
            _cmd_run(config, state)
    except ConfigError as exc:
        log_error(str(exc))
        sys.exit(1)
    except JaliosError as exc:
        log_error(str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
