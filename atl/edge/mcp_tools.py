# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
mcp_tools.py — the edge layer's MCP tools, added to the tool's own MCP server
by add_edge_tools(server) (scripts/edge-wire.py puts the call in
mcp_server.py). Owned by the edge layer.

Started by the edge's own chat panel (<ENV>_CHAT_CONFIRM=1), every change is
a PROPOSAL the person confirms there with a click. Elsewhere (Claude Code,
Claude Desktop) the client asks before each tool call, so changes run
directly. Use act() for the tool's own changing tools too.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from ..core import mcp_bridge as web
from . import settings


def confirm_in_panel() -> bool:
    return os.environ.get(f"{settings.ENV}_CHAT_CONFIRM") == "1"


def act(summary: str, method: str, path: str, payload: Optional[dict] = None) -> Any:
    """Make a change, or in the chat panel propose it for the person to confirm."""
    web.ensure_server()
    if confirm_in_panel():
        made = web.call("POST", "/api/chat/proposals",
                        {"summary": summary, "method": method, "path": path, "body": payload or {}})
        return {"proposal": made["id"], "status": "proposed: waiting for the person to confirm it in the chat "
                "panel. It has NOT run. Do not say it is done; after they confirm, jobs() shows it."}
    return web.call(method, path, payload)


def add_edge_tools(server: Any) -> None:
    @server.tool()
    def connections() -> dict:
        """The clouds this edge is linked to: each connection's site, tenant,
        spaces, token expiry and any renewal problem. Never a token."""
        web.ensure_server()
        return web.call("GET", "/api/cloud")

    @server.tool()
    def jobs() -> list:
        """Background work: each job's kind, state, phase and progress."""
        web.ensure_server()
        return web.call("GET", "/api/jobs")

    @server.tool()
    def cancel_job(job_id: str) -> dict:
        """Stop a queued or running job."""
        return act(f"Cancel job {job_id}", "POST", f"/api/jobs/{job_id}/cancel", {})

    @server.tool()
    def knowledge() -> dict:
        """The local A-Boxes (one per space) and how many statements each holds."""
        web.ensure_server()
        return web.call("GET", "/api/knowledge")

    @server.tool()
    def sync_knowledge(graph: str = "") -> dict:
        """Merge the A-Boxes with every linked cloud (one space's, or all).
        Returns the job; poll jobs()."""
        return act(f"Sync {graph or 'every'} A-Box with every linked cloud", "POST", "/api/knowledge/sync",
                   {"graph": graph} if graph else {})

    @server.tool()
    def link(cloud: str, profile: str = "prod") -> dict:
        """Start linking this edge to a cloud (its edge API address, from the
        cloud's About page) under a connection name. An admin of the tenant
        then approves the code the page shows."""
        return act(f"Link to {cloud} as {profile}", "POST", "/api/cloud/link",
                   {"cloud": cloud, "profile": profile})

    # the backbone's tools, for an IoT or robot edge
    for bridge in ("nodered", "ros2"):
        try:
            mod = __import__(f"{__package__}.bridges.{bridge}", fromlist=["add_tools"])
        except ImportError:
            continue
        mod.add_tools(server)
