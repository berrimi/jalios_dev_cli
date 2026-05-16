"""Rsync plugin output to webapp."""

from __future__ import annotations

import subprocess
from pathlib import Path

from jalios_dev import log_sync, log_warning
from jalios_dev.models import AppConfig, RuntimeState, SyncError


def _validate_sync_paths(src: Path, dst: Path) -> None:
    if not src or str(src) == "/":
        raise SyncError("source path is empty or root")
    if not dst or str(dst) == "/":
        raise SyncError("dest path is empty or root")


def _rsync_flags(preview: bool) -> list[str]:
    flags = ["rsync", "-a", "--checksum", "--out-format=%n"]
    if preview:
        flags.append("--dry-run")
    return flags


def _run_rsync(
    src: Path,
    dst: Path,
    config: AppConfig,
    state: RuntimeState,
    src_label: str,
) -> None:
    _validate_sync_paths(src, dst)
    dst.mkdir(parents=True, exist_ok=True)
    flags = _rsync_flags(config.preview_mode)
    result = subprocess.run(
        flags + [f"{src}/", f"{dst}/"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        if config.preview_mode:
            log_warning(f"rsync preview warning for {src_label}: {result.stderr.strip()}")
            return
        raise SyncError(result.stderr.strip() or f"rsync failed for {src_label}")

    for line in result.stdout.splitlines():
        file = line.strip()
        if not file or file.endswith("/"):
            continue
        log_sync(f"{src}/{file} → {dst}/{file}")
        state.synced_files += 1


def sync_plugin_to_webapp(config: AppConfig, state: RuntimeState) -> None:
    plugin_bin = config.plugin_project / "bin"
    webapp_classes = config.webapp_project_root / "WEB-INF" / "classes"
    if plugin_bin.is_dir():
        _run_rsync(plugin_bin, webapp_classes, config, state, "bin")
    else:
        log_warning(f"Plugin bin directory not found: {plugin_bin}")

    plugin_assets = (
        config.plugin_project
        / "plugins"
        / config.plugin_project_name
    )
    webapp_plugins = (
        config.webapp_project_root
        / "plugins"
        / config.plugin_project_name
    )
    if plugin_assets.is_dir():
        _run_rsync(plugin_assets, webapp_plugins, config, state, "plugins")
    else:
        log_warning(f"Plugin assets directory not found: {plugin_assets}")
