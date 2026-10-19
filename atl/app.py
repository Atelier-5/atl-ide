#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Atelier-5
"""
app.py — browser front end for engine.py.

    atl-ide-web                       # http://127.0.0.1:8780
    atl-ide-web --port 9000
    python3 -m atl.app            # the same, from a checkout

The page, stop, restart, update and the About box come from core.server; this
module only adds the tool's own routes, and those only move data between the
browser and engine or the workspace folders.
"""

from __future__ import annotations

import argparse
import atexit
import sys
from typing import Optional

import urllib.error
import urllib.request

from flask import Response, abort, jsonify, render_template, request, stream_with_context

from . import engine as engine
from . import i18n
from . import ontology
from . import sim
from .i18n import _
from .core import server
from .core import workspace as ws

app = server.create_app(__name__)

from .edge import routes as edge_routes  # edge layer
edge_routes.install(app)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024


def body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, "expected a JSON object body")
    return data


# ------------------------------------------------------------------ page ----

@app.before_request
def _language() -> None:
    """Every request speaks the person's language: their choice on the page, else their browser's."""
    i18n.use(i18n.pick(request.cookies.get("lang"), request.headers.get("Accept-Language")))


def _i18n_boot() -> dict:
    """The page's language, the languages there are, and the catalog: in the page, so it draws translated at once."""
    lang = i18n.current()
    return {"lang": lang, "langs": [{"id": l, "name": i18n.NAMES[l]} for l in i18n.LANGS], "catalog": i18n.catalog(lang)}


@app.get("/")
def index() -> str:
    return render_template("index.html", i18n=_i18n_boot())


@app.get("/api/i18n")
def i18n_catalog():
    """The page's language and its catalog (English text -> translation), and the languages there are."""
    return jsonify(_i18n_boot())


@app.get("/how")
def how():
    """How atl-ide works: an Archify drawing (docs/how-it-works.architecture.json)."""
    return app.send_static_file("how.html")


@app.get("/model")
def model():
    """The data model, the robot ontology and its topic contract: an Archify drawing (docs/data-model.class.json)."""
    return app.send_static_file("model.html")


@app.get("/favicon.ico")
def favicon():
    """Browsers ask for this by name whatever the page links to."""
    return app.send_static_file("favicon.svg")


# ------------------------------------------------------------ simulation ----
#
# The virtual table: Webots on this PC and the robot's body in its container (sim.py).
# The page never talks to the gateway itself: these routes pass a fixed set of
# calls through, so the gateway stays reachable from this server only.

ROBOT_ACTIONS = ("drive", "behaviour", "button", "clap", "lift", "led", "estop", "reset", "place")


def twin_dir():
    return (ws.FOLDERS[ws.USER] / "twin").resolve()


@app.get("/api/sim")
def sim_status():
    return jsonify(sim.SIM.status())


@app.post("/api/sim/start")
def sim_start():
    data = request.get_json(silent=True) or {}
    return jsonify(sim.SIM.start(twin_dir(), gui=bool(data.get("gui", True))))


@app.post("/api/sim/stop")
def sim_stop():
    return jsonify(sim.SIM.stop())


def _down():
    return jsonify({"errors": [_("The simulation is not running: start it on the Table screen.")]}), 503


@app.get("/api/robot/state")
def robot_state():
    try:
        return jsonify(sim.gateway("GET", "/state", timeout=2.0))
    except sim.GatewayDown:
        return _down()


@app.post("/api/robot/<action>")
def robot_act(action: str):
    if action not in ROBOT_ACTIONS:
        abort(404)
    try:
        return jsonify(sim.gateway("POST", f"/{action}", request.get_json(silent=True) or {}))
    except sim.GatewayDown:
        return _down()
    except sim.GatewayRefused as refused:
        return jsonify({"errors": [refused.message]}), refused.status


@app.get("/api/robot/camera.jpg")
def robot_camera():
    try:
        with urllib.request.urlopen(sim.GATEWAY + "/camera/overview.jpg", timeout=3) as r:
            return Response(r.read(), mimetype="image/jpeg", headers={"Cache-Control": "no-store"})
    except (urllib.error.URLError, OSError):
        return _down()


@app.get("/api/robot/camera.mjpg")
def robot_stream():
    try:
        upstream = urllib.request.urlopen(sim.GATEWAY + "/camera/overview.mjpg", timeout=5)
    except (urllib.error.URLError, OSError):
        return _down()

    def relay():
        try:
            while True:
                chunk = upstream.read1(64 * 1024) if hasattr(upstream, "read1") else upstream.read(16 * 1024)
                if not chunk:
                    return
                yield chunk
        except (OSError, ValueError):
            return
        finally:
            upstream.close()
    return Response(stream_with_context(relay()), mimetype="multipart/x-mixed-replace; boundary=frame",
                    headers={"Cache-Control": "no-store"})


# --------------------------------------------------------------- ontology ----
#
# The robot as data (ontology.py): what it is, what its readings mean, what it
# accepts, and whether a request is one it accepts. The MCP tools use these, so an
# agent and the page read the same description.

ROBOTS = ontology.Robots(lambda: sim.gateway_text("/robot.ttl"), twin_dir)


def _abox():
    try:
        return ROBOTS.abox(), None
    except ontology.NoRobot as none:
        return None, (jsonify({"errors": [_(str(none))]}), 404)


@app.get("/api/ontology/robot")
def ontology_robot():
    g, err = _abox()
    return err or jsonify(ontology.robot(g, i18n.current()))


@app.get("/api/ontology/commands")
def ontology_commands():
    g, err = _abox()
    return err or jsonify(ontology.commands(g, i18n.current()))


@app.get("/api/ontology/sensors")
def ontology_sensors():
    g, err = _abox()
    if err:
        return err
    try:
        state = sim.gateway("GET", "/state", timeout=2.0)
    except sim.GatewayDown:
        return _down()
    return jsonify(ontology.sensors(g, state, i18n.current()))


@app.post("/api/ontology/check")
def ontology_check():
    g, err = _abox()
    if err:
        return err
    data = body()
    return jsonify({"errors": ontology.check(g, str(data.get("name", "")), data.get("params") or {})})


# ---------------------------------------------------------------- engine ----

@app.post("/api/validate")
def validate():
    return jsonify({"errors": engine.validate(body().get("note"))})


@app.post("/api/summarise")
def summarise():
    note = body().get("note")
    errors = engine.validate(note)
    if errors:
        return jsonify({"errors": errors}), 400
    return jsonify(engine.summarise(note))


# ------------------------------------------------------------- workspace ----
#
# An agent (through MCP) and a person (in the browser) edit the same files, so
# a save carries the version it was based on, and the server refuses one that
# would silently overwrite a change the saver never saw (409).

@app.get("/api/folders")
def folders():
    return jsonify(ws.folders())


@app.get("/api/notes")
def list_notes():
    return jsonify(ws.listing())


@app.get("/api/notes/<name>")
def read_note(name: str):
    return jsonify(ws.read(name, request.args.get("folder") or None))


@app.put("/api/notes/<name>")
def save_note(name: str):
    data = body()
    note = data.get("note")
    errors = engine.validate(note)
    if errors:
        return jsonify({"errors": errors}), 400
    folder: Optional[str] = data.get("folder") or request.args.get("folder") or None
    try:
        saved = ws.save(name, note, folder, data.get("base_version"))
    except ws.Conflict as clash:
        return jsonify({"errors": ["changed on disk since you opened it"],
                        "version": clash.current_version,
                        "note": clash.current}), 409
    return jsonify(saved)


@app.delete("/api/notes/<name>")
def delete_note(name: str):
    return jsonify(ws.delete(name, request.args.get("folder") or None))


# ------------------------------------------------------------------ main ----

def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(prog="atl-ide-web",
                                 description=__doc__.strip().splitlines()[0])
    server.add_server_args(ap)
    ap.add_argument("--dir", default=ws.FOLDERS[ws.USER].name,
                    help="your own notes (default: ./mydocs)")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)

    ws.configure(user_dir=args.dir)
    lines = [f"  {f['label'].lower():<13} {f['path']}" for f in ws.folders()]
    edge_routes.start_background()  # edge layer
    atexit.register(sim.SIM.stop)    # the server going away takes the simulation with it
    return server.serve(app, args, lines=lines)


if __name__ == "__main__":
    raise SystemExit(main())
