#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Atelier-5
"""
mcp_server.py — MCP access to atl-ide.

Exposes the robot over stdio, so an agent sees the same virtual table a person has
open in the browser. Everything goes through the web server (core.mcp_bridge),
started on demand. Reading is free; acting is a proposal (edge.mcp_tools.act),
which a facilitator confirms in the chat panel; the emergency stop never waits.

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
from typing import Any, Optional

from mcp.server.mcpserver import MCPServer

from .core import mcp_bridge as web

server = MCPServer(
    name="atl-ide",
    instructions=(
        "atl-ide: the Atelier-5 robotics IDE. A Thymio II on a virtual table in Webots, explored by young people "
        "(12 and up) with a facilitator. Be a correspondant: ask what they observed and expect before you suggest. "
        "simulation() says whether the table runs; robot() what the robot is (from its ontology: sensors, where they "
        "sit, what was measured); sensors() its live readings, each named; commands() what it accepts. Always "
        "check_command() before command(): the ontology's shapes refuse what the robot cannot do. command() and "
        "start_simulation() are proposals a facilitator confirms in the chat panel; never say the robot did something "
        "before sensors() shows it. estop() is never a proposal: use it at once if the robot must stop."
    ),
)

web.add_core_tools(server)

from .edge.mcp_tools import act, add_edge_tools  # edge layer
add_edge_tools(server)


def _get(path: str) -> Any:
    web.ensure_server()
    return web.call("GET", path)


@server.tool()
def simulation() -> dict:
    """The virtual table: phase (stopped, starting, running, failed), the start's steps, what is missing to start it,
    and the last lines of the log when it failed."""
    return _get("/api/sim")


@server.tool()
def start_simulation() -> Any:
    """Start the virtual table: Webots opens it with one Thymio II and the robot's body connects (about 10 s).
    A proposal: the facilitator confirms it. Then poll simulation() until it is running."""
    return act("Start the simulation", "POST", "/api/sim/start", {"gui": True})


@server.tool()
def stop_simulation() -> Any:
    """Stop the virtual table (Webots and the robot's body). A proposal: the facilitator confirms it."""
    return act("Stop the simulation", "POST", "/api/sim/stop", {})


@server.tool()
def robot() -> dict:
    """What the robot is, from its ontology (A-Box): its name and contract, its motors' limits, every sensor and
    actuator it hosts (kind, device, position on the robot in m, raw range, topic) with what was measured, and the
    commands it accepts. Available once the simulation has run once."""
    return _get("/api/ontology/robot")


@server.tool()
def sensors() -> dict:
    """The live readings, each with the sensor it comes from (kind, side, raw range), plus the IMU (m/s2), odometry,
    the twin's true pose, the running behaviour and what it is doing, the E-stop, lift and LED. Needs the simulation."""
    return _get("/api/ontology/sensors")


@server.tool()
def commands() -> list:
    """What the robot accepts: each command's name, gateway route, whether a facilitator must confirm it, and its
    parameters with their limits (from the ontology's SHACL shapes)."""
    return _get("/api/ontology/commands")


@server.tool()
def check_command(name: str, params: Optional[dict] = None) -> list[str]:
    """Check a command against the robot's ontology before proposing it: [] when the robot accepts it, else what is
    wrong, in words (e.g. a speed past the motors' limit, an unknown behaviour). Example: check_command("drive",
    {"linear": 0.08, "angular": 0})."""
    web.ensure_server()
    return web.call("POST", "/api/ontology/check", {"name": name, "params": params or {}})["errors"]


@server.tool()
def command(name: str, params: Optional[dict] = None) -> Any:
    """Ask the robot to do something: drive {linear m/s, angular rad/s} (repeat within 0.5 s to keep driving),
    behaviour {name}, button {name}, clap {n}, lift {up}, led {r, g, b}, reset, place {name, x, y, yaw}.
    It is checked against the ontology first; then it is a proposal the facilitator confirms. For the
    emergency stop use estop()."""
    params = dict(params or {})
    if name == "drive":
        params.setdefault("linear", 0.0)
        params.setdefault("angular", 0.0)
    if name == "estop":
        return estop(bool(params.get("on", True)))
    errors = check_command(name, params)
    if errors:
        raise web.ToolError("; ".join(errors))
    what = ", ".join(f"{k} {v}" for k, v in params.items())
    return act(f"Robot: {name}" + (f" ({what})" if what else ""), "POST", f"/api/robot/{name}", params)


@server.tool()
def estop(on: bool = True) -> dict:
    """The emergency stop: on holds the motors at once, whatever else is sent; off releases them. Never a proposal:
    safety does not wait for a click."""
    web.ensure_server()
    return web.call("POST", "/api/robot/estop", {"on": on})


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
