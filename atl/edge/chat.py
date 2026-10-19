# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
chat.py — the edge's chat panel: Claude, with this edge's tools and nothing
else. Owned by the edge layer; the prompt and what may be proposed are in
settings.py.

The page talks to Claude Code running on this computer (`claude -p`), signed
in with the person's own claude.ai account: no API key, no extra bill.
Claude Code gets:

    tools        none of its own (--tools ""): no shell, no files, no web
    MCP          only this edge's MCP server (--strict-mcp-config), started in
                 panel mode: every change it asks for is a PROPOSAL that the
                 person confirms in the panel (<ENV>_CHAT_CONFIRM=1)
    not allowed  stop_server

What leaves the computer is what the tools answer. A proposal names one call
to this edge's own API, and only calls in settings.CHAT_ALLOWED can be
proposed. The person's click runs it.
"""

from __future__ import annotations

import collections
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from . import settings

REPO = Path(__file__).resolve().parents[2]
SERVER = settings.TOOL.replace("-", "_")          # the MCP server's name as Claude Code sees it


class Proposals:
    """Changes Claude asked for, waiting for the person's click."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self.items: Dict[str, Dict[str, Any]] = {}

    def add(self, summary: str, method: str, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        method = str(method).upper()
        if not any(method == m and re.fullmatch(p, str(path)) for m, p in settings.CHAT_ALLOWED):
            raise ValueError(f"{method} {path} cannot be proposed from the chat")
        if not isinstance(body, dict):
            raise ValueError("body must be an object")
        with self._lock:
            pid = f"p{next(self._ids)}"
            self.items[pid] = {"id": pid, "summary": str(summary)[:300], "method": method, "path": path,
                               "body": body, "state": "waiting", "at": time.time()}
            return dict(self.items[pid])

    def take(self, pid: str, state: str) -> Dict[str, Any]:
        """Mark a waiting proposal confirmed or dismissed (once)."""
        with self._lock:
            p = self.items.get(pid)
            if not p:
                raise KeyError(pid)
            if p["state"] != "waiting":
                raise ValueError(f"this proposal is {p['state']} already")
            p["state"] = state
            return dict(p)


def available() -> Dict[str, Any]:
    exe = shutil.which("claude")
    if not exe:
        return {"available": False, "why": "Claude Code (`claude`) is not installed on this computer"}
    try:
        v = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        v = ""
    return {"available": True, "version": v}


def mcp_config(workdir: Path, port: int) -> Path:
    """This edge's MCP server, in panel mode, as Claude Code starts it."""
    cfg = {"mcpServers": {SERVER: {
        "command": sys.executable,
        "args": ["-m", f"{settings.PACKAGE}.mcp_server", "--no-autostart", "--port", str(port)],
        "env": {"PYTHONPATH": str(REPO), f"{settings.ENV}_CHAT_CONFIRM": "1"},
    }}}
    workdir.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = workdir / "mcp.json"
    path.write_text(json.dumps(cfg))
    os.chmod(path, 0o600)
    return path


def command(message: str, workdir: Path, port: int, lang: str, session: Optional[str]) -> List[str]:
    args = [shutil.which("claude") or "claude", "-p", message,
            "--output-format", "stream-json", "--verbose", "--include-partial-messages",
            "--tools", "",
            "--strict-mcp-config", "--mcp-config", str(mcp_config(workdir, port)),
            "--allowedTools", f"mcp__{SERVER}",
            "--disallowedTools", f"mcp__{SERVER}__stop_server",
            "--append-system-prompt", settings.CHAT_SYSTEM.format(lang=lang)]
    if session:
        args += ["--resume", session]
    return args


def events(lines: Iterator[str]) -> Iterator[Dict[str, Any]]:
    """Claude Code's stream-json, as the panel's events:

        {"t": "text", "text": …}             a piece of the answer
        {"t": "tool", "name": …, "id": …}    a tool Claude calls
        {"t": "proposal", "id": …}           a change waiting for a click
        {"t": "done", "session": …, "error": …}
    """
    streamed = False
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        kind = e.get("type")
        if kind == "stream_event":
            ev = e.get("event") or {}
            delta = ev.get("delta") or {}
            if ev.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
                streamed = True
                yield {"t": "text", "text": delta.get("text", "")}
            elif ev.get("type") == "message_start":
                streamed = False
        elif kind == "assistant":
            for c in (e.get("message") or {}).get("content") or []:
                if c.get("type") == "text" and not streamed:
                    yield {"t": "text", "text": c.get("text", "")}
                elif c.get("type") == "tool_use":
                    yield {"t": "tool", "name": str(c.get("name", "")).replace(f"mcp__{SERVER}__", ""), "id": c.get("id")}
        elif kind == "user":
            for c in (e.get("message") or {}).get("content") or []:
                if not isinstance(c, dict) or c.get("type") != "tool_result":
                    continue
                text = c.get("content")
                if isinstance(text, list):
                    text = " ".join(x.get("text", "") for x in text if isinstance(x, dict))
                m = re.search(r'"proposal":\s*"(p\d+)"', str(text or ""))
                if m:
                    yield {"t": "proposal", "id": m.group(1)}
        elif kind == "result":
            yield {"t": "done", "session": e.get("session_id"),
                   "error": e.get("result") if e.get("is_error") else None}


class Chat:
    """One conversation at a time; a new message continues it (--resume)."""

    def __init__(self, workdir: Path) -> None:
        self.workdir = workdir
        self.session: Optional[str] = None
        self.proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()

    def new(self) -> None:
        self.stop()
        self.session = None

    def stop(self) -> None:
        p = self.proc
        if p and p.poll() is None:
            p.kill()

    def ask(self, message: str, port: int, lang: str) -> Iterator[Dict[str, Any]]:
        if not self._lock.acquire(blocking=False):
            yield {"t": "done", "error": "Claude is still answering the last message."}
            return
        try:
            self.workdir.mkdir(parents=True, exist_ok=True, mode=0o700)
            env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "ANTHROPIC_API_KEY")}
            self.proc = subprocess.Popen(command(message, self.workdir, port, lang, self.session),
                                         cwd=self.workdir, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, text=True, env=env)
            assert self.proc.stdout is not None and self.proc.stderr is not None
            # drain stderr all the time: a full pipe would block Claude Code
            # and the panel would wait for ever (as ffmpeg once did)
            tail: "collections.deque[str]" = collections.deque(maxlen=20)
            err = self.proc.stderr
            threading.Thread(target=lambda: [tail.append(x.rstrip()) for x in err], daemon=True).start()
            finished = False
            for ev in events(self.proc.stdout):
                if ev["t"] == "done":
                    finished = True
                    if ev.get("session"):
                        self.session = ev["session"]
                yield ev
            self.proc.wait()
            if not finished:
                yield {"t": "done", "error": ("\n".join(tail)[-300:] or "stopped")}
        finally:
            self.proc = None
            self._lock.release()
