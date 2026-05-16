"""Rsync plugin output to webapp."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from jalios_dev import log_info, log_sync, log_warning
from jalios_dev.models import AppConfig, RuntimeState, SyncError

_RSYNC_EXCLUDES = ["--exclude=.git", "--exclude=.svn"]
_SYNC_CONF_NAMES = ("sync.conf", ".sync.conf", ".sync.properties")


def resolve_webapp_root(config: AppConfig) -> None:
    for name in _SYNC_CONF_NAMES:
        conf = config.webapp_project / name
        if not conf.is_file():
            continue
        config_dir = conf.parent
        config.webapp_project_root = config_dir
        for line in conf.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.startswith("root.dir"):
                continue
            root_dir = line.split("=", 1)[-1].strip().strip("\r")
            if not root_dir:
                break
            actual = config_dir / root_dir
            if actual.is_dir():
                config.webapp_project_root = actual
            else:
                log_warning(f"Webapp root directory not found: {actual}")
            break
        return
    config.webapp_project_root = config.webapp_project


def _validate_sync_paths(src: Path, dst: Path) -> None:
    if not src or str(src) == "/":
        raise SyncError("source path is empty or root")
    if not dst or str(dst) == "/":
        raise SyncError("dest path is empty or root")


def _rsync_flags(preview: bool, *, checksum: bool) -> list[str]:
    flags = ["rsync", "-a", "--out-format=%n", *_RSYNC_EXCLUDES]
    if checksum:
        flags.append("--checksum")
    if preview:
        flags.append("--dry-run")
    return flags


def _plugin_dir(plugin_root: Path, sub: str, name: str) -> Path | None:
    named = plugin_root / sub / name
    if named.is_dir():
        return named
    parent = plugin_root / sub
    if not parent.is_dir():
        return None
    for child in sorted(parent.iterdir()):
        if child.is_dir():
            return child
    return None


def _map_plugin_rel(src: Path, config: AppConfig) -> Path | None:
    plugin = config.plugin_project.resolve()
    try:
        rel = src.resolve().relative_to(plugin)
    except ValueError:
        return None
    name = config.plugin_project_name
    root = config.webapp_project_root
    if rel.parts[:2] == ("plugins", name) or (
        len(rel.parts) >= 2 and rel.parts[0] == "plugins"
    ):
        return root / rel
    if len(rel.parts) >= 3 and rel.parts[:3] == ("WEB-INF", "plugins", name):
        return root / rel
    if rel.parts[0] == "WEB-INF" and rel.parts[1] == "plugins" and len(rel.parts) >= 3:
        return root / rel
    return None


def _run_rsync(
    src: Path,
    dst: Path,
    config: AppConfig,
    state: RuntimeState,
    src_label: str,
    *,
    checksum: bool = True,
) -> None:
    _validate_sync_paths(src, dst)
    dst.mkdir(parents=True, exist_ok=True)
    flags = _rsync_flags(config.preview_mode, checksum=checksum)
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


def _copy_file(src: Path, dst: Path, config: AppConfig, state: RuntimeState) -> None:
    if config.preview_mode:
        log_sync(f"[preview] {src} → {dst}")
        state.synced_files += 1
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    log_sync(f"{src} → {dst}")
    state.synced_files += 1


def sync_changed_file(path: str, config: AppConfig, state: RuntimeState) -> None:
    src = Path(path).resolve()
    if not src.is_file():
        return
    dest = _map_plugin_rel(src, config)
    if dest is None:
        log_warning(f"No sync mapping for: {src}")
        return
    _copy_file(src, dest, config, state)


def _sync_plugin_trees(
    config: AppConfig,
    state: RuntimeState,
    *,
    checksum: bool,
) -> None:
    plugin = config.plugin_project
    name = config.plugin_project_name
    root = config.webapp_project_root

    assets = _plugin_dir(plugin, "plugins", name)
    if assets:
        log_info(f"  Syncing plugin assets ({assets.name}/ → plugins/{assets.name}/)")
        _run_rsync(
            assets, root / "plugins" / assets.name, config, state, "plugins",
            checksum=checksum,
        )
    else:
        log_warning(f"Plugin assets directory not found under {plugin}/plugins")

    inf = _plugin_dir(plugin, "WEB-INF/plugins", name)
    if inf:
        log_info(f"  Syncing plugin descriptor (WEB-INF/plugins/{inf.name}/)")
        _run_rsync(
            inf, root / "WEB-INF" / "plugins" / inf.name, config, state,
            "WEB-INF/plugins", checksum=checksum,
        )
    else:
        log_warning("Plugin WEB-INF/plugins directory not found")


def sync_static_assets(config: AppConfig, state: RuntimeState) -> None:
    """Sync plugins/ + WEB-INF/plugins/ only (no bin) — for .js/.jsp watch."""
    log_info("Syncing plugin assets → webapp...")
    before = state.synced_files
    _sync_plugin_trees(config, state, checksum=False)
    if state.synced_files == before and not config.preview_mode:
        log_warning("rsync reported no asset changes (forcing copy on next save)")


def sync_plugin_to_webapp(config: AppConfig, state: RuntimeState) -> None:
    log_info("Syncing plugin project → webapp...")
    plugin = config.plugin_project
    root = config.webapp_project_root

    plugin_bin = plugin / "bin"
    webapp_classes = root / "WEB-INF" / "classes"
    if plugin_bin.is_dir():
        try:
            _run_rsync(plugin_bin, webapp_classes, config, state, "bin")
        except SyncError as exc:
            log_warning(f"bin/ sync failed (continuing): {exc}")
    else:
        log_warning(f"Plugin bin directory not found: {plugin_bin}")

    _sync_plugin_trees(config, state, checksum=True)
