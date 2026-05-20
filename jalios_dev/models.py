"""Config and runtime dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


class JaliosError(Exception):
    pass


class ConfigError(JaliosError):
    pass


class SyncError(JaliosError):
    pass


class ServerError(JaliosError):
    pass


@dataclass
class AppConfig:
    workspace_path: Path
    tomcat_home: Path
    plugin_project: Path
    webapp_project: Path
    webapp_project_root: Path
    plugin_project_name: str
    webapp_project_name: str
    java_version: str = "11"
    excluded_dirs: list[str] = field(default_factory=list)
    excluded_files: list[str] = field(default_factory=list)
    restart_patterns: list[str] = field(
        default_factory=lambda: ["*.java", "*.xml", "*.properties", "*.prop"]
    )
    reloadable: bool = False
    preview_mode: bool = False
    verbose: bool = False
    catalina_base: Path | None = None


@dataclass
class RuntimeState:
    synced_files: int = 0
    compiled_files: int = 0
    start_time: float = 0.0
