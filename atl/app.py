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
import sys
from typing import Optional

from flask import abort, jsonify, render_template, request

from . import engine as engine
from . import i18n
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
    return server.serve(app, args, lines=lines)


if __name__ == "__main__":
    raise SystemExit(main())
