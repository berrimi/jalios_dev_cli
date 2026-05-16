# jalios-dev

Development tool for [Jalios JCMS](https://www.jalios.com) plugin projects. Syncs plugin sources to a running webapp, compiles Java on change, and manages Tomcat.

## Requirements

- Linux (uses `rsync`, `pgrep`, `prctl`/setproctitle)
- Python 3.11+
- Java 8+ and `javac`
- Tomcat 9+
- `rsync`

## Installation

```bash
git clone <repo> ~/jalios-dev
cd ~/jalios-dev
pip install .
```

This installs the `jalios` CLI command.

## Usage

```
jalios [COMMAND] [OPTIONS]
```

### Commands

| Command     | Description |
|-------------|-------------|
| `preview`   | Show what would be synced without changing anything (default) |
| `sync`      | Sync plugin files and compile Java |
| `run`       | Sync, compile, start Tomcat, watch for file changes, stream JCMS logs |

### Options

| Flag                   | Description |
|------------------------|-------------|
| `-p, --plugin PATH`    | Path to plugin project (auto-detected) |
| `-w, --webapp PATH`    | Path to webapp project (auto-detected) |
| `-v, --verbose`        | Verbose output |
| `-h, --help`           | Show help |

### Examples

```bash
jalios                   # preview (safe, no changes)
jalios sync              # actually sync and compile
jalios run               # sync, compile, start server, watch files + logs
jalios -p ~/my-plugin -w ~/my-webapp sync
```

## Configuration

Created automatically on first run at `~/.config/jalios/config.toml`.

```toml
tomcat_home = "/opt/apache-tomcat-9"
workspace_path = "/home/user/workspace_jalios"
java_version = "11"
```

Optional fields: `plugin_project_name`, `webapp_project_name`, `excluded_dirs`, `excluded_files`, `restart_patterns`.

## Hot Reload

If Tomcat has `reloadable="true"` on the JCMS webapp context, `jalios run` skips server restarts on Java changes — Tomcat reloads the webapp automatically. Detection checks:

- `$WEBAPP/META-INF/context.xml`
- `$CATALINA_HOME/conf/context.xml`
- `$CATALINA_BASE/conf/Catalina/localhost/$APP.xml`

Without `reloadable="true"`, Java changes trigger a full Tomcat restart.

## Project Structure

```
jalios-dev/
├── jalios_dev/
│   ├── __init__.py    # terminal logging helpers
│   ├── main.py        # CLI entrypoint, arg parsing
│   ├── config.py      # config load, auto-detection, validation
│   ├── watcher.py     # file watcher with debounce
│   ├── sync.py        # rsync plugin → webapp
│   ├── compile.py     # javac compilation
│   ├── server.py      # Tomcat start / stop
│   ├── logs.py        # JCMS log streaming with colorization
│   └── models.py      # AppConfig / RuntimeState dataclasses
├── pyproject.toml
└── README.md
```

## Platform

Linux only. Depends on `rsync`, `pgrep`, and the `setproctitle` Python package for process naming.
