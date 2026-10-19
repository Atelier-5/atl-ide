# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
mcp_bridge.py — let an MCP server work through the tool's web server.

An agent and a person work through one server and one set of files, so a save
from either shows up in the other on the next read. The MCP server is therefore
a thin client of the HTTP API rather than a second implementation of it, and
this module is the client:

    from .core import mcp_bridge as web
    web.configure(port=args.port, autostart=True)
    web.call("GET", "/api/things")              # ensure_server() first
    raise web.ToolError("what the agent should read")   # its text reaches the model
    web.add_core_tools(server)                  # server_url, stop_server
    web.start_heartbeat()                       # so About can say it is running

Nothing may be written to stdout here or anywhere in an MCP server: stdout is
the transport. log() goes to stderr.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from . import identity

try:
    from mcp.server.mcpserver.exceptions import ToolError as _Delivered
except ImportError:                 # core imported where the mcp package is not
    _Delivered = Exception


class ToolError(_Delivered, ValueError):
    """A failure the agent is meant to read — raise this, not ValueError.

    The MCP SDK treats any other exception from a tool as a crash: it logs a
    traceback, and the model is told only "Error executing tool <name>", with
    the text left behind on the server. So every sentence written for the agent
    — a validation problem, "changed since you read it", "not configured" — was
    being thrown away. Only the SDK's own ToolError is delivered.

    It is also a ValueError, so code that already catches ValueError around a
    bridge call keeps working unchanged.
    """


class NotAnswering(ToolError, ConnectionError):
    """The web server is not there. A ConnectionError too, for existing catches."""


BASE = f"http://127.0.0.1:{identity.DEFAULT_PORT}"
AUTOSTART = True


def configure(port: Optional[int] = None, url: Optional[str] = None,
              autostart: bool = True) -> None:
    global BASE, AUTOSTART
    BASE = (url or f"http://127.0.0.1:{port or identity.DEFAULT_PORT}").rstrip("/")
    AUTOSTART = autostart


def start_heartbeat(every: Optional[float] = None) -> threading.Thread:
    """Tell the web server, every so often, that this MCP server is running.

    A stdio server has no port the web server could knock on, so without this
    the About box could only guess from tool calls, and an agent that is open
    but idle would look dead. The beat never starts a web server — an MCP
    server someone left open must not bring one back after it was stopped. A
    failed beat is tried again after a couple of seconds rather than a whole
    interval, so a web server that has just come up sees it straight away.
    """
    from . import services
    interval = float(every or services.BEAT_EVERY)
    body = json.dumps({"pid": os.getpid()}).encode()

    def pulse() -> None:
        while True:
            req = urllib.request.Request(
                BASE + "/api/mcp/heartbeat", data=body, method="POST",
                headers={"X-Agent": f"{identity.TOOL_NAME}-mcp",
                         "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=3):
                    pass
                wait = interval
            except Exception:            # noqa: BLE001 - not running is fine
                wait = min(2.0, interval)
            time.sleep(wait)

    thread = threading.Thread(target=pulse, name="mcp-heartbeat", daemon=True)
    thread.start()
    return thread


def log(msg: str) -> None:
    print(f"  [{identity.TOOL_NAME}] {msg}", file=sys.stderr, flush=True)


def call(method: str, path: str, payload: Optional[dict] = None,
         timeout: float = 30) -> Any:
    """One request against the web server, with its error messages preserved."""
    body = json.dumps(payload).encode() if payload is not None else None
    # Name ourselves on every call. The web server records it, so the Agent
    # panel in the browser can say an agent is working here rather than guess:
    # a stdio server has no port to look for and no pid the page could find.
    headers = {"X-Agent": f"{identity.TOOL_NAME}-mcp"}
    if body:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=body, method=method,
                                 headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            raw = res.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        try:
            data = json.loads(detail)
            errors = data.get("errors") or [data.get("description") or detail]
        except ValueError:
            errors = [detail]
        raise ToolError("; ".join(str(e) for e in errors)) from None
    except urllib.error.URLError as exc:
        raise NotAnswering(
            f"{identity.TITLE} at {BASE} is not answering: {exc.reason}") from None


def alive() -> bool:
    """Something answers at BASE, and it is this tool rather than another one."""
    try:
        return (call("GET", "/api/health", timeout=3) or {}).get("tool") == identity.TOOL_NAME
    except (ConnectionError, ValueError, OSError):
        return False


def ensure_server() -> None:
    """Start the web server if nothing is answering, and wait for it to come up.

    It inherits this process's working directory, which is the project the
    agent was started in, so a user folder resolves there and not inside
    site-packages or a plugin cache.
    """
    if alive():
        return
    if not AUTOSTART:
        raise NotAnswering(f"nothing is running at {BASE} — start it with run.sh "
                           f"or {identity.WEB_COMMAND}")
    port = urllib.parse.urlparse(BASE).port or identity.DEFAULT_PORT
    log(f"nothing on {BASE} — starting {identity.WEB_COMMAND}")
    subprocess.Popen(
        [sys.executable, "-m", f"{identity.PACKAGE}.app", "--port", str(port)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    for _ in range(60):
        time.sleep(0.25)
        if alive():
            log(f"ready at {BASE}")
            return
    raise NotAnswering(f"started {identity.WEB_COMMAND} but {BASE} never answered")


def add_core_tools(server: Any) -> None:
    """The two tools every tool's MCP server has: where the page is, and stop it."""

    @server.tool()
    def server_url() -> str:
        """The URL to open the tool in a browser, so a person can take over."""
        ensure_server()
        return BASE + "/"

    @server.tool()
    def stop_server() -> str:
        """Shut the tool's local web server down."""
        if not alive():
            return "nothing was running"
        try:
            call("POST", "/api/shutdown")
        except ConnectionError:
            pass                              # it died mid-answer, which is the point
        return f"stopped {identity.TITLE} at {BASE}"
