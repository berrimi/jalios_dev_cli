"""Load and validate TOML configuration."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from jalios_dev import log_info, log_warning
from jalios_dev.models import AppConfig, ConfigError

CONFIG_PATH = Path.home() / ".config" / "jalios" / "config.toml"
LEGACY_CONFIG = Path.home() / ".jalios"
REQUIRED_GLOBAL = (
    "workspace_path",
    "tomcat_home",
    "plugin_project_name",
    "webapp_project_name",
)


def _read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    merged.update(override)
    return merged


def _check_migration() -> None:
    if LEGACY_CONFIG.is_file() and not CONFIG_PATH.is_file():
        raise ConfigError(
            f"Found legacy shell config at {LEGACY_CONFIG} but no TOML at {CONFIG_PATH}. "
            "Create ~/.config/jalios/config.toml (see config.toml.example) and migrate settings."
        )


def _load_global() -> dict[str, Any]:
    _check_migration()
    if not CONFIG_PATH.is_file():
        raise ConfigError(f"Missing global config: {CONFIG_PATH}")
    data = _read_toml(CONFIG_PATH)
    for key in REQUIRED_GLOBAL:
        if key not in data or not data[key]:
            raise ConfigError(f"Missing required field in global config: {key}")
    return data


def _load_local(plugin_dir: Path) -> dict[str, Any]:
    local = plugin_dir / ".jalios.toml"
    if not local.is_file():
        return {}
    return _read_toml(local)


def _catalina_base(workspace: Path) -> Path | None:
    wtp = (
        workspace
        / ".metadata/.plugins/org.eclipse.wst.server.core/tmp0"
    )
    return wtp if wtp.is_dir() else None


def load_config(
    plugin_override: Path | None,
    webapp_override: Path | None,
) -> AppConfig:
    global_data = _load_global()
    workspace = Path(global_data["workspace_path"]).expanduser()
    tomcat_home = Path(global_data["tomcat_home"]).expanduser()
    plugin_name = str(global_data["plugin_project_name"])
    webapp_name = str(global_data["webapp_project_name"])
    java_version = str(global_data.get("java_version", "11"))

    plugin_project = (
        plugin_override.expanduser()
        if plugin_override
        else workspace / plugin_name
    )
    webapp_project = (
        webapp_override.expanduser()
        if webapp_override
        else workspace / webapp_name
    )

    local_data = _load_local(plugin_project)
    merged = _merge(
        {
            "java_version": java_version,
            "excluded_dirs": [".git", "bin", ".settings"],
            "excluded_files": [".classpath", ".project"],
            "restart_patterns": ["*.java", "*.xml", "*.properties", "*.prop"],
        },
        local_data,
    )

    return AppConfig(
        workspace_path=workspace,
        tomcat_home=tomcat_home,
        plugin_project=plugin_project,
        webapp_project=webapp_project,
        webapp_project_root=webapp_project,
        plugin_project_name=plugin_name,
        webapp_project_name=webapp_name,
        java_version=str(merged.get("java_version", "11")),
        excluded_dirs=list(merged.get("excluded_dirs", [])),
        excluded_files=list(merged.get("excluded_files", [])),
        restart_patterns=list(merged.get("restart_patterns", [])),
        catalina_base=_catalina_base(workspace),
    )


def validate_config(config: AppConfig) -> None:
    for label, path in (
        ("workspace_path", config.workspace_path),
        ("tomcat_home", config.tomcat_home),
    ):
        if not path.exists():
            raise ConfigError(f"{label} does not exist: {path}")
