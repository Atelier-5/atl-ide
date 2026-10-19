# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
services.py — what this tool is made of, and whether each part is working.

The About box lists every part a tool can have, with one of three states:

    up     enabled here, and working
    down   enabled here, and not working — the detail says what to do
    off    not part of this tool, or switched off

"off" matters as much as the other two. Tools built from the template differ:
one has an MCP server and a workspace folder, another has neither. Leaving a
row out would make a person wonder whether it was forgotten; showing it grey
says it was never there.

    services.describe()                     every row, checked now
    services.register("jira", "Jira",       a tool's own service
                      check=lambda: (True, "connected as Ann"),
                      enabled=lambda: configured())
    services.beat(client)                   the MCP server saying it is alive
    services.listening(host, port)          serve() recording where it listens

Core-owned (D-LAB-5 tool template): `copier update` rewrites this file.
"""

from __future__ import annotations

import concurrent.futures
import importlib.util
import os
import time
from typing import Callable, Dict, List, Optional, Tuple, Union

from . import identity
from . import version as ver

UP, DOWN, OFF = "up", "down", "off"

# The MCP server beats every BEAT_EVERY seconds while it runs; a beat older
# than ALIVE_FOR means it has gone. A stdio server has no port and no pid the
# web server can see, so traffic is the only honest evidence — and a heartbeat
# is traffic that does not depend on an agent happening to call a tool.
BEAT_EVERY = 20
ALIVE_FOR = 60

# A tool's own check gets this long before its row says it did not answer, so
# one slow backend cannot hold the whole About box open.
CHECK_TIMEOUT = 6.0

_beat: Dict[str, object] = {"client": None, "at": 0.0, "pid": None}
_where: Dict[str, object] = {"host": None, "port": None}

Check = Callable[[], Tuple[bool, str]]
Enabled = Callable[[], Union[bool, Tuple[bool, str]]]
_registered: List[Dict[str, object]] = []


def beat(client: str, pid: Optional[int] = None) -> None:
    """Record a heartbeat from the MCP server."""
    _beat.update(client=client or f"{identity.TOOL_NAME}-mcp", at=time.time(), pid=pid)


def listening(host: str, port: int) -> None:
    """Remember where the web server listens, for its row."""
    _where.update(host=host, port=port)


def register(service_id: str, name: str, check: Check,
             enabled: Optional[Enabled] = None) -> None:
    """Add a tool's own service to the list.

    `check()` returns (working, detail) and may take a moment — it runs in a
    worker with a timeout. `enabled()` returns a bool, or (bool, detail) to say
    why a row is grey ("not configured — add a token under Settings"). An
    exception from either is a "down" row carrying its message, never a broken
    About box. Registering an id again replaces the earlier one.
    """
    global _registered
    _registered = [s for s in _registered if s["id"] != service_id]
    _registered.append({"id": service_id, "name": name, "check": check,
                        "enabled": enabled or (lambda: True)})


# ------------------------------------------------------------- built-ins ----

def _row(service_id: str, name: str, state: str, detail: str) -> Dict[str, str]:
    return {"id": service_id, "name": name, "state": state, "detail": detail}


def _web() -> Dict[str, str]:
    # If this is answering, the web server is up: it is what is answering.
    host, port = _where["host"], _where["port"]
    where = f"{host}:{port} · " if host and port else ""
    return _row("web", "Web server", UP, f"{where}pid {os.getpid()}")


def _mcp() -> Dict[str, str]:
    if not getattr(identity, "WITH_MCP", False):
        return _row("mcp", "MCP server", OFF, "this tool has no MCP server")
    at = float(_beat["at"] or 0)
    if not at:
        return _row("mcp", "MCP server", DOWN,
                    "not running — an agent starts it; see the Agent button")
    ago = int(time.time() - at)
    if ago > ALIVE_FOR:
        return _row("mcp", "MCP server", DOWN,
                    f"last heard from {ago} s ago — its agent has probably closed")
    pid = f" · pid {_beat['pid']}" if _beat["pid"] else ""
    return _row("mcp", "MCP server", UP, f"running{pid} · heard from {ago} s ago")


def _updates() -> Dict[str, str]:
    found = ver.latest_version()
    if found.get("disabled"):
        return _row("updates", "Update check", OFF, "switched off (--no-update-check)")
    if found.get("error"):
        return _row("updates", "Update check", DOWN, str(found["error"]))
    return _row("updates", "Update check", UP,
                f"github.com answered · latest {found.get('version') or 'unknown'}")


def _skill() -> Dict[str, str]:
    from . import skill_install
    shipped = skill_install.packaged()
    if not shipped.is_file():
        return _row("skill", "Agent skill", OFF, "this tool ships no skill")
    how = f"{identity.SKILL_COMMAND} --install"

    def current(path) -> bool:
        try:
            return path.is_file() and path.read_bytes() == shipped.read_bytes()
        except OSError:
            return False

    there = skill_install.destination()
    if current(there):
        return _row("skill", "Agent skill", UP, f"installed in {there.parent}")
    # An agent working inside a checkout reads the repository's own copy, so a
    # current one there is as installed as it needs to be for that agent.
    here = skill_install.checkout_copies()
    if here and current(here[0]):
        return _row("skill", "Agent skill", UP,
                    f"in this checkout ({here[0].parent}) — run {how} for "
                    "agents working elsewhere")
    if there.is_file():
        return _row("skill", "Agent skill", DOWN,
                    f"the installed copy is out of date — run {how}")
    return _row("skill", "Agent skill", DOWN, f"not installed — run {how}")


def _workspace() -> Dict[str, str]:
    if not getattr(identity, "WITH_WORKSPACE", False) or \
            importlib.util.find_spec(f"{identity.PACKAGE}.core.workspace") is None:
        return _row("workspace", "Workspace folder", OFF, "this tool has no workspace")
    from . import workspace
    problems = []
    for entry in workspace.folders():
        path = entry["path"]
        if not os.path.isdir(path):
            problems.append(f"{entry['label']} folder is missing: {path}")
        elif not os.access(path, os.W_OK):
            problems.append(f"{entry['label']} folder is read-only: {path}")
    if problems:
        return _row("workspace", "Workspace folder", DOWN, "; ".join(problems))
    user = next((f for f in workspace.folders() if f["value"] == workspace.USER), None)
    return _row("workspace", "Workspace folder", UP,
                user["path"] if user else "folders in place")


BUILT_IN = (_web, _mcp, _updates, _skill, _workspace)


# ----------------------------------------------------------------- answer ---

def _one(service: Dict[str, object]) -> Dict[str, str]:
    sid, name = str(service["id"]), str(service["name"])
    try:
        said = service["enabled"]()
        on, why = (said if isinstance(said, tuple) else (bool(said), ""))
    except Exception as exc:                       # noqa: BLE001 - never break About
        return _row(sid, name, DOWN, f"could not tell whether it is set up: {exc}")
    if not on:
        return _row(sid, name, OFF, why or "not set up")
    try:
        ok, detail = service["check"]()
    except Exception as exc:                       # noqa: BLE001
        return _row(sid, name, DOWN, str(exc) or type(exc).__name__)
    return _row(sid, name, UP if ok else DOWN, detail)


def describe() -> List[Dict[str, str]]:
    """Every service, core's first, then the tool's own in registration order."""
    rows = []
    for build in BUILT_IN:
        try:
            rows.append(build())
        except Exception as exc:                   # noqa: BLE001
            name = build.__name__.strip("_")
            rows.append(_row(name, name, DOWN, f"could not check: {exc}"))
    if not _registered:
        return rows
    # The tool's checks may reach a network, so they run side by side against
    # one deadline. Not a `with` block: leaving one waits for every worker, and
    # a backend that hangs would then hold the About box open after all.
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=len(_registered))
    futures = [(s, pool.submit(_one, s)) for s in _registered]
    deadline = time.monotonic() + CHECK_TIMEOUT
    for service, future in futures:
        try:
            rows.append(future.result(timeout=max(0.0, deadline - time.monotonic())))
        except concurrent.futures.TimeoutError:
            rows.append(_row(str(service["id"]), str(service["name"]), DOWN,
                             f"did not answer within {CHECK_TIMEOUT:g} s"))
    pool.shutdown(wait=False, cancel_futures=True)
    return rows
