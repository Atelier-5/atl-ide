#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Atelier-5
"""
mcp_server.py — MCP access to atl-ide.

Exposes the tool over stdio, so an agent can work on the same data a person has
open in the browser. The pure engine calls run in-process; everything that
touches files goes through the web server (core.mcp_bridge), which is started
on demand, so browser and agent never disagree about what is on disk.

    atl-ide-mcp                               # talks to 127.0.0.1:8780
    atl-ide-mcp --port 9000
    atl-ide-mcp --no-autostart                # fail instead of starting one
    python3 -m atl.mcp_server            # the same, from a checkout

Register it in .mcp.json (a checkout already has one), or install the Claude
Code plugin, which brings this server and the skill together.

Nothing may be written to stdout: that is the MCP transport. Log to stderr.
"""

from __future__ import annotations

import argparse
import urllib.parse
from typing import Optional

from mcp.server.mcpserver import MCPServer

from . import engine as engine
from .core import mcp_bridge as web

server = MCPServer(
    name="atl-ide",
    instructions=(
        "atl-ide: the Atelier-5 robotics IDE, a Thymio II twin in Webots over ROS 2" + ". "
        "A note is a JSON object with a title, a body and optional tags. "
        "Call validate_note before saving anything you assembled by hand."
        " Notes live in two folders: 'user' (the person's own, where new saves "
        "go) and 'shared' (samples that ship with the tool). Pass the version "
        "read_note returned as base_version when you save, so a change the "
        "person made in the browser meanwhile is never overwritten silently."
    ),
)

web.add_core_tools(server)

from .edge.mcp_tools import add_edge_tools  # edge layer
add_edge_tools(server)


@server.tool()
def validate_note(note: dict) -> list[str]:
    """Everything wrong with a note. An empty list means it is valid."""
    return engine.validate(note)


@server.tool()
def summarise_note(note: dict) -> dict:
    """Word and line counts and the distinct tags of a valid note."""
    errors = engine.validate(note)
    if errors:
        # web.ToolError, not ValueError: only this kind reaches the agent's model
        raise web.ToolError("; ".join(errors))
    return engine.summarise(note)


def _qualify(name: str, folder: str) -> str:
    path = f"/api/notes/{urllib.parse.quote(name)}"
    return f"{path}?folder={urllib.parse.quote(folder)}" if folder else path


@server.tool()
def list_notes() -> list[dict]:
    """Every saved note, with its folder and version."""
    web.ensure_server()
    return web.call("GET", "/api/notes")


@server.tool()
def read_note(name: str, folder: str = "") -> dict:
    """One note: {name, folder, version, data}. With no folder, the user's
    copy wins over a shared one of the same name."""
    web.ensure_server()
    return web.call("GET", _qualify(name, folder))


@server.tool()
def save_note(name: str, note: dict, folder: str = "",
              base_version: Optional[str] = None) -> dict:
    """Write a note. With no folder it goes back where it lives, or to 'user'
    when new. Pass base_version from read_note: a save against a version that
    has since changed is refused, and the error carries the current content."""
    web.ensure_server()
    payload = {"note": note, "folder": folder or None, "base_version": base_version}
    return web.call("PUT", _qualify(name, ""), payload)


@server.tool()
def delete_note(name: str, folder: str = "") -> dict:
    """Delete a note. Say which folder when the name exists in both."""
    web.ensure_server()
    return web.call("DELETE", _qualify(name, folder))


def main() -> int:
    ap = argparse.ArgumentParser(prog="atl-ide-mcp",
                                 description=__doc__.strip().splitlines()[0])
    ap.add_argument("--url", help="web server base URL (overrides --port)")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--no-autostart", action="store_true",
                    help="fail rather than start a web server that is not running")
    args = ap.parse_args()
    web.configure(port=args.port, url=args.url, autostart=not args.no_autostart)
    web.log(f"serving MCP over stdio, web server at {web.BASE}")
    web.start_heartbeat()
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
