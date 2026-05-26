"""Java compilation via javac."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from jalios_dev import log_debug, log_info, log_success, log_sync, log_warning
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


def _compile_list(
    config: AppConfig,
    state: RuntimeState,
    java_files: list[Path],
    bin_dir: Path,
) -> bool:
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
        log_debug(f"javac command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        output = (result.stdout + result.stderr).strip()
        if result.returncode != 0:
            lines = [ln for ln in output.splitlines() if ln.strip()]
            errors = [ln for ln in lines if "error:" in ln]
            log_warning(f"Compilation had {len(errors) or len(lines)} errors:")
            for line in lines[:10]:
                log_warning(f"  {line}")
            return False
        state.compiled_files += len(java_files)
        log_success(f"Compiled {len(java_files)} file(s)")
        return True
    finally:
        tmp.unlink(missing_ok=True)


def _copy_class_to_source(
    java_files: list[Path],
    bin_dir: Path,
    src_dir: Path,
) -> None:
    src_dir_resolved = src_dir.resolve()
    for java_file in java_files:
        try:
            rel = java_file.resolve().relative_to(src_dir_resolved)
        except ValueError:
            continue
        pkg = rel.parent
        stem = rel.stem
        for bin_class in bin_dir.glob(str(Path(pkg) / f"{stem}*.class")):
            dst = src_dir / bin_class.relative_to(bin_dir)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(bin_class, dst)
            log_sync(f"[class] {bin_class} → {dst}")


def compile_java_files(
    config: AppConfig,
    state: RuntimeState,
    files: list[Path] | None = None,
) -> bool:
    src_dir = config.plugin_project / "WEB-INF" / "classes"
    bin_dir = config.plugin_project / "bin"

    if not src_dir.is_dir():
        log_warning(f"Plugin source directory not found: {src_dir}")
        return True

    if files:
        java_files = [f.resolve() for f in files if f.suffix == ".java" and f.is_file()]
    else:
        java_files = list(src_dir.rglob("*.java"))

    if not java_files:
        log_info("No .java files to compile")
        return True

    if not shutil.which("javac"):
        log_warning("javac not found - cannot compile")
        return False

    bin_dir.mkdir(parents=True, exist_ok=True)
    src_dir_resolved = src_dir.resolve()
    if files:
        log_info(f"  Compiling {len(java_files)} changed Java file(s)...")
    else:
        log_info(f"  Compiling {len(java_files)} Java files...")

    ok = _compile_list(config, state, java_files, bin_dir)
    if ok and config.copy_class_to_source:
        _copy_class_to_source(java_files, bin_dir, src_dir_resolved)
    return ok
