# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
routes.py — the edge's HTTP API, as one Flask blueprint, and install(app),
the one call that wires the layer into a tool. Owned by the edge layer.

    install(app)          in app.py, after create_app: the blueprint, the
                          local-only guard, the job kinds
    start_background()    in main(), before serving: the token keeper and
                          first start (scripts/edge-wire.py adds both)

    GET  /api/cloud                     connections (never a token) and the pairing in progress
    POST /api/cloud/link                {cloud, profile}: start pairing; the page shows the code
    POST /api/cloud/unlink | /use       {profile}
    GET  /api/jobs, /api/jobs/<id>      progress
    POST /api/jobs/<id>/cancel
    GET  /api/knowledge                 the local A-Boxes
    POST /api/knowledge/sync            {graph?}: a job, every linked connection
    GET|POST /api/chat …                the chat panel (chat.py)
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from flask import Blueprint, Flask, Response, abort, jsonify, request

from . import chat as chat_mod
from . import cloud, firststart, settings, sync
from . import knowledge as kn
from .jobs import JOBS, Busy, Stopped

bp = Blueprint("edge", __name__, static_folder="static", static_url_path="/edge-static")

LINK_LOCK = threading.Lock()
LINK: Dict[str, Any] = {"state": "idle"}
KEEP_FRESH_EVERY_S = 12 * 3600


def body() -> Dict[str, Any]:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, "send a JSON object")
    return data


def submit(kind: str, spec: Dict[str, Any]):
    try:
        return jsonify(JOBS.submit(kind, spec)), 202
    except Busy as exc:
        abort(409, str(exc))


# -------------------------------------------------------------- connections --

@bp.get("/api/cloud")
def cloud_state():
    with LINK_LOCK:
        link = {k: v for k, v in LINK.items() if k != "pending"}
        pending = LINK.get("pending")
        if pending:
            link.update(user_code=pending.get("user_code"), url=pending.get("verification_uri_complete"),
                        profile=pending.get("profile"))
    return jsonify({**cloud.public_state(), "profiles": cloud.profiles(), "link": link})


def _poll(pending: Dict[str, Any]) -> None:
    def waiting(status: str) -> None:
        with LINK_LOCK:
            LINK["status"] = status
    try:
        state = cloud.poll_link(pending, cancelled=lambda: LINK.get("pending") is not pending, on_wait=waiting)
        with LINK_LOCK:
            LINK.clear()
            LINK.update(state="linked", profile=state.get("profile"))
        start_first_start()                        # just linked: fetch what this edge lacks
    except cloud.CloudError as exc:
        with LINK_LOCK:
            if LINK.get("pending") is pending:
                LINK.clear()
                LINK.update(state="failed", error=str(exc))


@bp.post("/api/cloud/link")
def cloud_link():
    data = body()
    base = str(data.get("cloud") or "").strip()
    if not base:
        abort(400, f"say which cloud: the edge API address of {settings.CLOUD_NAME} (its About page shows it)")
    try:
        cloud.PROFILE = cloud.check_profile(str(data.get("profile") or cloud.active_profile()))
        pending = cloud.start_link(base)
    except cloud.CloudError as exc:
        abort(400, str(exc))
    with LINK_LOCK:
        LINK.clear()
        LINK.update(state="waiting", pending=pending)
    threading.Thread(target=_poll, args=(pending,), name="link-poll", daemon=True).start()
    return jsonify({"user_code": pending["user_code"], "url": pending["verification_uri_complete"],
                    "expires_in": pending["expires_in"]})


@bp.post("/api/cloud/unlink")
def cloud_unlink():
    """Forget one connection's token here. An admin revokes the edge itself
    in that cloud's Settings → Edges."""
    name = (request.get_json(silent=True) or {}).get("profile") or None
    with LINK_LOCK:
        pending = LINK.get("pending")
        if not name or (pending and pending.get("profile") == name):
            LINK.clear()
            LINK["state"] = "idle"
    try:
        cloud.forget(cloud.check_profile(name) if name else None)
    except cloud.CloudError as exc:
        abort(400, str(exc))
    return jsonify(cloud.public_state())


@bp.post("/api/cloud/use")
def cloud_use():
    try:
        cloud.use_profile(str(body().get("profile") or ""))
        cloud.PROFILE = None
    except cloud.CloudError as exc:
        abort(400, str(exc))
    return jsonify(cloud.public_state())


# --------------------------------------------------------------------- jobs --

@bp.get("/api/jobs")
def jobs_list():
    return jsonify(JOBS.list())


@bp.get("/api/jobs/<job_id>")
def job_get(job_id: str):
    try:
        return jsonify(JOBS.get(job_id))
    except KeyError:
        abort(404, f"no job {job_id}")


@bp.post("/api/jobs/<job_id>/cancel")
def job_cancel(job_id: str):
    try:
        return jsonify(JOBS.cancel(job_id))
    except KeyError:
        abort(404, f"no job {job_id}")


# ---------------------------------------------------------------- knowledge --

@bp.get("/api/knowledge")
def knowledge_list():
    kb = kn.KnowledgeBase()
    return jsonify({"graphs": [{"name": g, "statements": len(kb.load(g))} for g in kb.graphs()]})


def _sync_job(spec: Dict[str, Any], progress, cancelled) -> Dict[str, Any]:
    kb = kn.KnowledgeBase()
    graphs = [spec["graph"]] if spec.get("graph") else kb.graphs()
    out = {}
    for n, g in enumerate(graphs):
        if cancelled():
            raise Stopped()
        progress(f"{g}", n / max(1, len(graphs)))
        out[g] = sync.sync_everywhere(kb, g, spec.get("resolve"))
    return out


@bp.post("/api/knowledge/sync")
def knowledge_sync():
    if not cloud.linked_profiles():
        abort(409, "no connection is linked")
    data = request.get_json(silent=True) or {}
    spec = {k: data[k] for k in ("graph", "resolve") if data.get(k)}
    if spec.get("graph") and not kn.GRAPH_NAME.fullmatch(str(spec["graph"])):
        abort(400, "graph is a space's slug: lowercase letters, digits and -")
    return submit("knowledge-sync", spec)


# --------------------------------------------------------------------- chat --

_CHAT: Dict[str, Any] = {}


def chat_state() -> Tuple[chat_mod.Proposals, chat_mod.Chat]:
    if not _CHAT:
        # a private, owner-only folder: Claude Code writes its session here
        _CHAT["proposals"] = chat_mod.Proposals()
        _CHAT["chat"] = chat_mod.Chat(Path(tempfile.mkdtemp(prefix=f"{settings.TOOL}-chat-")))
    return _CHAT["proposals"], _CHAT["chat"]


@bp.get("/api/chat")
def chat_status():
    proposals, talk = chat_state()
    return jsonify({**chat_mod.available(), "session": bool(talk.session),
                    "waiting": [p for p in proposals.items.values() if p["state"] == "waiting"]})


@bp.post("/api/chat")
def chat_ask():
    """Ask Claude; the answer streams back as one JSON event per line."""
    data = body()
    message = str(data.get("message") or "").strip()
    if not message or len(message) > 8000:
        abort(400, "message must be 1 to 8000 characters")
    if not chat_mod.available()["available"]:
        abort(503, "Claude Code is not installed on this computer")
    lang = data.get("lang") if data.get("lang") in ("en", "de", "fr") else "en"
    port = int(request.host.rsplit(":", 1)[-1]) if ":" in request.host else 80
    proposals, talk = chat_state()

    def stream():
        for ev in talk.ask(message, port, lang):
            if ev["t"] == "proposal":
                p = proposals.items.get(ev["id"])
                if p:
                    ev = {**ev, "summary": p["summary"], "state": p["state"]}
            yield json.dumps(ev) + "\n"
    return Response(stream(), mimetype="application/x-ndjson", headers={"Cache-Control": "no-store"})


@bp.post("/api/chat/new")
def chat_new():
    chat_state()[1].new()
    return jsonify({"ok": True})


@bp.post("/api/chat/stop")
def chat_stop():
    chat_state()[1].stop()
    return jsonify({"ok": True})


@bp.post("/api/chat/proposals")
def chat_propose():
    """From the MCP server in panel mode: a change to wait for the person."""
    data = body()
    try:
        p = chat_state()[0].add(data.get("summary", ""), data.get("method", ""), data.get("path", ""),
                                data.get("body") or {})
    except ValueError as exc:
        abort(400, str(exc))
    return jsonify(p), 201


@bp.post("/api/chat/proposals/<pid>/<what>")
def chat_decide(pid: str, what: str):
    """The person's click: confirm runs the proposed call, dismiss drops it."""
    from flask import current_app
    if what not in ("confirm", "dismiss"):
        abort(404)
    try:
        p = chat_state()[0].take(pid, "confirmed" if what == "confirm" else "dismissed")
    except KeyError:
        abort(404, "no such proposal")
    except ValueError as exc:
        abort(409, str(exc))
    if what == "dismiss":
        return jsonify({"state": "dismissed"})
    with current_app.test_client() as c:
        r = c.open(p["path"], method=p["method"], json=p["body"], headers={"Host": request.host})
    return jsonify({"state": "confirmed", "status": r.status_code, "result": r.get_json(silent=True)}), \
        (200 if r.status_code < 400 else 502)


# ------------------------------------------------------------------ bridges --
# Only the bridge of this edge's kind exists (copier writes one or none).

try:
    from .bridges import nodered
except ImportError:
    nodered = None
try:
    from .bridges import ros2
except ImportError:
    ros2 = None

if nodered is not None:
    @bp.get("/api/nodered")
    def nodered_status():
        out = nodered.available()
        if out["available"]:
            out["flows"] = nodered.flows()
        return jsonify(out)

    @bp.post("/api/nodered/call")
    def nodered_call():
        data = body()
        try:
            return jsonify(nodered.call(str(data.get("path") or ""), data.get("body") or {}))
        except ValueError as exc:
            abort(400, str(exc))
        except OSError as exc:
            abort(502, f"Node-RED did not answer: {exc}")

if ros2 is not None:
    @bp.get("/api/ros2")
    def ros2_status():
        out = ros2.available()
        if out["available"]:
            out["topics"] = ros2.topics()
        return jsonify(out)

    @bp.post("/api/ros2/publish")
    def ros2_publish():
        data = body()
        if not ros2.available()["available"]:
            abort(503, "ROS 2 is not available to this edge")
        return jsonify(ros2.publish(str(data.get("topic") or ""), str(data.get("type") or ""), data.get("data") or {}))


# ---------------------------------------------------------------- the guard --

def _guard(app: Flask) -> None:
    """This server answers to this machine only.

    DNS rebinding: a web page can make its own name resolve to 127.0.0.1 and
    then talk to this server as if it were the page's own origin. Binding to
    loopback does not stop that; checking the Host does. A write must also
    come from this page (or carry no Origin: an agent, a script). And no
    other page may frame this one.
    """
    extra = {h.lower() for h in os.environ.get(f"{settings.ENV}_EXTRA_HOSTS", "").split(",") if h}

    @app.before_request
    def _this_machine_only():
        host = (request.host or "").lower()
        name = host.split("]")[0] + "]" if host.startswith("[") else host.rsplit(":", 1)[0]
        if name not in {"127.0.0.1", "localhost", "[::1]"} | extra | set(app.config.get("CORE_EXTRA_HOSTS", ())):
            abort(403, "this server answers to localhost only")
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("Origin")
            if origin and origin.rstrip("/").lower() != f"{request.scheme}://{host}":
                abort(403, "requests from another site are refused")

    @app.after_request
    def _no_framing(resp):
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'; base-uri 'none'; object-src 'none'")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        return resp


# ---------------------------------------------------------- background work --

def start_first_start() -> None:
    """The first-start job, when anything is still missing."""
    try:
        if firststart.needed():
            JOBS.submit("first-start", {})
    except (Busy, cloud.CloudError):
        pass


def _keep_tokens_fresh() -> None:
    """Renew device tokens that are due, at start and twice a day, so a token
    cannot lapse just because nobody used the edge in its last 30 days."""
    while True:
        try:
            done = cloud.keep_fresh()
            if done:
                print(f"  device tokens: {done}", flush=True)
        except Exception as exc:              # never let the keeper die
            print(f"  device tokens: check failed: {exc}", flush=True)
        time.sleep(KEEP_FRESH_EVERY_S)


_INSTALLED = {"done": False, "background": False}


def install(app: Flask) -> None:
    """Everything the layer adds to a tool's app: the blueprint, the
    local-only guard and the job kinds. At import time in app.py; nothing
    runs in the background yet, so tests can import the app."""
    if _INSTALLED["done"]:
        return
    _INSTALLED["done"] = True
    _guard(app)
    app.register_blueprint(bp)
    JOBS.register("knowledge-sync", _sync_job)
    JOBS.register("first-start", firststart.run)


def start_background() -> None:
    """In main(), when the server really starts: the token keeper and first start."""
    if _INSTALLED["background"]:
        return
    _INSTALLED["background"] = True
    threading.Thread(target=_keep_tokens_fresh, name="token-keeper", daemon=True).start()
    start_first_start()
