"""Java compilation via javac."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from jalios_dev import log_info, log_success, log_warning
from jalios_dev.models import AppConfig, RuntimeState

_PATH_RE = re.compile(r'path="([^"]*)"')


def _extract_classpath(plugin_project: Path, bin_dir: Path) -> str:
    classpath_file = plugin_project / ".classpath"
    if not classpath_file.is_file():
        return f"{bin_dir}:{plugin_project / 'WEB-INF/lib'}/*"

    entries: list[str] = []
    text = classpath_file.read_text(encoding="utf-8", errors="replace")
    for match in _PATH_RE.finditer(text):
        path = match.group(1)
        if path.startswith("org.eclipse"):
            continue
        resolved = Path(path) if path.startswith("/") else plugin_project / path
        if resolved.exists():
            entries.append(str(resolved))
    if entries:
        return ":".join(entries)
    return f"{bin_dir}:{plugin_project / 'WEB-INF/lib'}/*"


def _count_class_files(bin_dir: Path) -> int:
    return sum(1 for _ in bin_dir.rglob("*.class"))


def compile_java_files(config: AppConfig, state: RuntimeState) -> None:
    src_dir = config.plugin_project / "WEB-INF" / "classes"
    bin_dir = config.plugin_project / "bin"

    if not src_dir.is_dir():
        log_warning(f"Plugin source directory not found: {src_dir}")
        return

    java_files = list(src_dir.rglob("*.java"))
    if not java_files:
        log_info("No .java files found")
        return

    if not shutil.which("javac"):
        log_warning("javac not found - cannot compile")
        return

    bin_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(f"/tmp/jalios_compile_{os.getpid()}.txt")
    try:
        tmp.write_text("\n".join(str(f) for f in java_files), encoding="utf-8")
        cp = _extract_classpath(config.plugin_project, bin_dir)
        cmd = [
            "javac",
            "-d",
            str(bin_dir),
            "-cp",
            cp,
            "-target",
            config.java_version,
            "-source",
            config.java_version,
            f"@{tmp}",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        output = (result.stdout + result.stderr).strip()
        if result.returncode != 0:
            lines = [ln for ln in output.splitlines() if ln.strip()]
            errors = [ln for ln in lines if "error:" in ln]
            log_warning(f"Compilation had {len(errors) or len(lines)} errors:")
            for line in lines[:10]:
                log_warning(f"  {line}")
        else:
            count = _count_class_files(bin_dir)
            state.compiled_files = count
            log_success(f"Compilation successful - {count} class files in bin/")
    finally:
        tmp.unlink(missing_ok=True)
