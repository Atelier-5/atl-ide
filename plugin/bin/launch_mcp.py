#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
launch_mcp.py — start the atl-ide MCP server from the Claude Code plugin.

A plugin is a clone of plugin/ and nothing else: no virtualenv, no Flask, no
mcp package. So on first use this makes one venv per released version, installs
exactly the version the plugin pins (bin/VERSION) into it, and then runs the MCP
server from there. Later starts find the venv ready and skip straight to it.

    ~/.local/share/dlab5-tools/atl-ide/<version>/     Linux, macOS
    %LOCALAPPDATA%\\dlab5-tools\\atl-ide\\<version>\\  Windows

Everything the install prints goes to stderr, because stdout is the MCP
transport and one stray pip line on it breaks the handshake.

    DLAB5_TOOL_SOURCE=/path/to/checkout   install from there instead of the tag
    DLAB5_TOOL_REINSTALL=1                install again even if the venv is ready

Standard library only. Core-owned (D-LAB-5 tool template).
"""

from __future__ import annotations

import os
import subprocess
import sys
import venv
from pathlib import Path

TOOL = "atl-ide"
PACKAGE = "atl"
REPO_URL = "https://github.com/Atelier-5/atl-ide"
HERE = Path(__file__).resolve().parent


def log(msg: str) -> None:
    print(f"  [{TOOL} plugin] {msg}", file=sys.stderr, flush=True)


def data_home() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def main() -> int:
    if sys.version_info < (3, 10):
        log(f"needs Python 3.10 or newer, found {sys.version.split()[0]}")
        return 1
    version = (HERE / "VERSION").read_text(encoding="utf-8").strip()
    source = os.environ.get("DLAB5_TOOL_SOURCE") or f"git+{REPO_URL}@v{version}"
    home = data_home() / "dlab5-tools" / TOOL / version
    python = home / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    stamp = home / ".installed-from"

    # a clean environment for everything below: an inherited PYTHONPATH (ROS 2
    # sets one on DLAB5 workstations) would shadow the venv's own packages
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}

    ready = (python.exists() and stamp.exists()
             and stamp.read_text(encoding="utf-8") == source
             and not os.environ.get("DLAB5_TOOL_REINSTALL"))
    if not ready:
        log(f"installing {TOOL} {version} from {source} into {home}")
        if not python.exists():
            venv.EnvBuilder(with_pip=True, clear=True).create(home)
        done = subprocess.run(
            [str(python), "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
             "--upgrade", source],
            stdout=sys.stderr, stderr=sys.stderr, stdin=subprocess.DEVNULL, env=env)
        if done.returncode != 0:
            log("install failed — see pip's output above. Check the network, or set "
                "DLAB5_TOOL_SOURCE to a local checkout")
            return done.returncode
        stamp.write_text(source, encoding="utf-8")
        log("installed")

    # a child rather than exec: it behaves the same on Windows, where exec does
    # not keep the stdio pipes the client is talking over
    return subprocess.call([str(python), "-m", f"{PACKAGE}.mcp_server", *sys.argv[1:]], env=env)


if __name__ == "__main__":
    raise SystemExit(main())
