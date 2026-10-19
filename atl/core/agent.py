# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
agent.py — tell any agent how to reach this tool, and say whether one has.

An MCP server is written once and every client speaks to it unchanged: Claude
Code, Copilot in VS Code, Cursor, Claude Desktop. What differs between them is
about ten lines of JSON and where that file lives. This module writes those ten
lines, with real paths filled in, so nobody has to remember the shape.

    targets()          every client we know how to configure
    snippet(target)    the JSON to paste, as text
    status()           has an MCP server actually been talking to us?
    seen()             called by the web server when a request carries X-Agent

What this cannot do is start an MCP server. A stdio server is spawned by its
client, lives on that client's pipes, and dies with it; there is no port to
knock on and no pid to signal. So the panel offers the configuration instead,
which is the thing a person can act on, and reports whether an agent is
currently connected, which is a thing we can honestly observe.

Core-owned (D-LAB-5 tool template): `copier update` rewrites this file.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

from . import identity
from .version import repo_root

# An MCP client identifies itself on every call (core.mcp_bridge sets the
# header). We keep the last one and when it spoke; nothing else is recorded.
_seen: Dict[str, object] = {"client": None, "at": 0.0}

# How long after its last call an agent still counts as connected. A client
# that is merely idle is still attached to its server, but we cannot see the
# pipe -- only the traffic -- so this is a statement about traffic, and the
# wording in the panel says so.
ACTIVE_FOR = 15 * 60


def seen(client: str) -> None:
    """Record that an MCP server called us. The web server does this."""
    _seen["client"] = client or identity.TOOL_NAME
    _seen["at"] = time.time()


def status() -> Dict[str, object]:
    """Whether an agent has been through here, and how long ago."""
    at = float(_seen["at"] or 0)
    ago = time.time() - at if at else None
    return {
        "connected": bool(at) and ago is not None and ago < ACTIVE_FOR,
        "client": _seen["client"],
        "seconds_ago": int(ago) if ago is not None else None,
        # the server cannot start an MCP server, and the panel must not pretend
        "startable": False,
    }


# ---------------------------------------------------------------- command ---

def interpreter() -> str:
    """The Python that should run the MCP server, as an absolute path.

    A checkout has a virtualenv beside it with the tool's dependencies in it,
    and that is what an agent must run -- not whichever python happens to be
    first on the agent's PATH, which is usually the system one and has no mcp
    package. An installed copy is simpler: the interpreter running us already
    has the tool importable.
    """
    root = repo_root()
    if root is not None:
        venv = root / (".venv/Scripts/python.exe" if os.name == "nt"
                       else ".venv/bin/python")
        if venv.exists():
            return str(venv)
    return sys.executable


def command() -> List[str]:
    """Argv that starts this tool's MCP server."""
    return [interpreter(), "-m", f"{identity.PACKAGE}.mcp_server"]


def working_dir() -> Optional[str]:
    """Where the server should run, so the user folder resolves there.

    Only meaningful for a checkout: an installed copy follows whatever
    directory the agent itself was started in, which is what we want.
    """
    root = repo_root()
    return str(root) if root is not None else None


# ----------------------------------------------------------------- targets ---
#
# Each entry says where the file goes and what shape it has. The two shapes in
# the wild differ only in the wrapper key and whether a "type" is spelled out.

def _stdio(with_type: bool) -> Dict[str, object]:
    entry: Dict[str, object] = {}
    if with_type:
        entry["type"] = "stdio"
    argv = command()
    entry["command"] = argv[0]
    entry["args"] = argv[1:]
    where = working_dir()
    if where:
        entry["cwd"] = where
    return entry


def _wrap(key: str, with_type: bool) -> str:
    return json.dumps({key: {identity.TOOL_NAME: _stdio(with_type)}}, indent=2)


TARGETS = ("claude-code", "vscode", "cursor", "claude-desktop", "generic")


def targets() -> List[Dict[str, object]]:
    """Every client we can configure, in the order the panel should show them."""
    home = Path.home()
    root = repo_root()
    here = root if root is not None else Path.cwd()
    return [
        {
            "id": "claude-code",
            "name": "Claude Code",
            "path": str(here / ".mcp.json"),
            "in_project": True,
            "config": _wrap("mcpServers", with_type=False),
            "instructions": {
                "what": "skill",
                "path": str(home / ".claude" / "skills" / identity.SKILL_NAME / "SKILL.md"),
                "how": f"{identity.SKILL_COMMAND} --install",
            },
            "note": "A checkout already has this file. Claude Code also takes "
                    "the tool as a plugin, which brings the skill with it.",
        },
        {
            "id": "vscode",
            "name": "VS Code (GitHub Copilot)",
            "path": str(here / ".vscode" / "mcp.json"),
            "in_project": True,
            "config": _wrap("servers", with_type=True),
            "instructions": {
                "what": "instructions",
                "path": str(here / ".github" / "copilot-instructions.md"),
                "how": f"{identity.SKILL_COMMAND} --print > "
                       f"{Path('.github') / 'copilot-instructions.md'}",
            },
            "note": "Open Copilot Chat, switch it to Agent mode, and the tool "
                    "appears in the tools picker.",
        },
        {
            "id": "cursor",
            "name": "Cursor",
            "path": str(here / ".cursor" / "mcp.json"),
            "in_project": True,
            "config": _wrap("mcpServers", with_type=False),
            "instructions": {
                "what": "instructions",
                "path": str(here / ".cursor" / "rules" / f"{identity.TOOL_NAME}.mdc"),
                "how": f"{identity.SKILL_COMMAND} --print",
            },
            "note": "Project rules live beside the server config.",
        },
        {
            "id": "claude-desktop",
            "name": "Claude Desktop",
            "path": _desktop_config_path(),
            "in_project": False,
            "config": _wrap("mcpServers", with_type=False),
            "instructions": None,
            "note": "One file for the whole app, not per project. Restart "
                    "Claude Desktop after editing it.",
        },
        {
            "id": "generic",
            "name": "Anything else that speaks MCP",
            "path": None,
            "in_project": False,
            "config": _wrap("mcpServers", with_type=False),
            "instructions": None,
            "note": "stdio transport. Point the client at the command above; "
                    "the wrapper key is whatever that client calls its server list.",
        },
    ]


def _desktop_config_path() -> str:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "Claude"
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "Claude"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "Claude"
    return str(base / "claude_desktop_config.json")


def target(target_id: str) -> Optional[Dict[str, object]]:
    for entry in targets():
        if entry["id"] == target_id:
            return entry
    return None


def snippet(target_id: str) -> Optional[str]:
    found = target(target_id)
    return None if found is None else str(found["config"])


def available() -> bool:
    """Is there an MCP server in this tool at all?

    core/ is not gated on the MCP answer, so this module exists even in a tool
    built without one. Handing out a config that names a module which was never
    generated would be worse than saying there is nothing to connect to.
    """
    return bool(getattr(identity, "WITH_MCP", False))


def merge_into(existing: str, target_id: str) -> str:
    """This tool's entry added to a config file that may already have others.

    Overwriting the file would throw away every other MCP server the person has
    registered there, which is the kind of help nobody thanks you for. A file
    we cannot parse is left alone: the caller reports that rather than guessing
    what the user meant.
    """
    found = target(target_id)
    if found is None:
        raise KeyError(target_id)
    mine = json.loads(str(found["config"]))
    key = next(iter(mine))                       # "mcpServers" or "servers"
    text = (existing or "").strip()
    if not text:
        return json.dumps(mine, indent=2) + "\n"
    current = json.loads(text)                   # ValueError: caller handles it
    if not isinstance(current, dict):
        raise ValueError("the file does not hold a JSON object")
    servers = current.get(key)
    if not isinstance(servers, dict):
        servers = {}
    servers[identity.TOOL_NAME] = mine[key][identity.TOOL_NAME]
    current[key] = servers
    return json.dumps(current, indent=2) + "\n"


def write_config(target_id: str) -> str:
    """Put this tool's entry in the target's config file, keeping what is there.

    Returns the path written. Raises OSError if it cannot be written, and
    ValueError if the file exists but is not JSON we can safely add to.

    What lands there names this machine's interpreter by absolute path, because
    an agent has its own PATH and a relative one resolves against whatever
    directory it happened to start in. That makes the file personal: committing
    it hands a colleague a path that does not exist on their machine. A tool
    from this template ignores these two files for that reason.
    """
    found = target(target_id)
    if found is None or not found["path"]:
        raise KeyError(target_id)
    path = Path(str(found["path"]))
    try:
        existing = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        existing = ""
    merged = merge_into(existing, target_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(merged, encoding="utf-8")
    return str(path)


def describe() -> Dict[str, object]:
    """Everything the Agent panel shows, in one answer."""
    if not available():
        return {
            "tool": identity.TOOL_NAME,
            "title": identity.TITLE,
            "available": False,
            "why": f"{identity.TITLE} was built without an MCP server, so there "
                   "is nothing for an agent to connect to.",
            "targets": [],
            "status": status(),
        }
    return {
        "tool": identity.TOOL_NAME,
        "title": identity.TITLE,
        "available": True,
        "command": command(),
        "cwd": working_dir(),
        "install": "checkout" if repo_root() is not None else "installed",
        "targets": targets(),
        "status": status(),
    }
