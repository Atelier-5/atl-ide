# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
server.py — what every tool's web server does that has nothing to do with the tool.

    app = create_app(__name__)          # Flask app with the core blueprint on it
    ap = argparse.ArgumentParser(...)
    add_server_args(ap)                 # --host --port --debug --no-update-check --version
    args = ap.parse_args()
    return serve(app, args, lines=["  flows folder  /some/where"])

The blueprint gives the page:

    GET  /api/health       tool name and version; what launchers and MCP poll
    GET  /api/version      installed vs published, plus everything the About box shows
    GET  /api/services     each part of the tool: up, down, or not part of it
    POST /api/mcp/heartbeat  the MCP server saying it is still running
    POST /api/update       pip-upgrade an installed copy (loopback only)
    POST /api/restart      re-exec on the same port (loopback only)
    POST /api/shutdown     exit (loopback only)
    /core-static/...       core.css, core.js, the logo

and core/templates/core/_base.html, which a tool's index.html extends to get
the header with the theme picker, About, Restart and Stop.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
import subprocess
import sys
import threading
from typing import Callable, Dict, Iterable, List, Optional

from flask import Blueprint, Flask, abort, jsonify, request
from werkzeug.exceptions import HTTPException

from . import agent
from . import identity
from . import services
from . import version as ver

bp = Blueprint("core", __name__,
               static_folder="static", static_url_path="/core-static",
               template_folder="templates")

# Extra rows for the About box, from the tool: {"Flows folder": "/some/where"}.
_about_extras: List[Callable[[], Dict[str, str]]] = []


def about_extras(provider: Callable[[], Dict[str, str]]) -> None:
    """Register a callable whose rows the About box shows under the version."""
    _about_extras.append(provider)


# -------------------------------------------------------------------- app ---

def create_app(import_name: str, **flask_kwargs) -> Flask:
    """A Flask app with the core blueprint, JSON errors and the tool's identity
    available to every template as `tool` and `version`."""
    app = Flask(import_name, **flask_kwargs)
    app.json.sort_keys = False
    app.register_blueprint(bp)

    @app.context_processor
    def _identity():
        return {"tool": identity, "version": ver.__version__,
                "with_mcp": agent.available()}

    @app.before_request
    def _note_agent():
        # An MCP server names itself on every call (core.mcp_bridge). That is
        # the only way the page can know an agent is working here: a stdio
        # server has no port to find and no pid to look up.
        client = request.headers.get("X-Agent")
        # a heartbeat says the server is running, not that an agent is working:
        # counting it would light the Agent dot for as long as a client is open
        if client and request.path != "/api/mcp/heartbeat":
            agent.seen(client)

    @app.errorhandler(HTTPException)
    def _as_json(exc: HTTPException):
        # both spellings: "errors" is what core.js reads, "description" is
        # what a hand-rolled fetch() usually looks for
        text = exc.description or exc.name
        return jsonify({"errors": [text], "description": text}), exc.code

    return app


def only_local(what: str) -> None:
    """Local tool, local kill switch.

    Only a loopback client may stop, restart or upgrade the server, and only
    over POST, so a page in another tab cannot navigate the server to death.
    Call it from any tool route that writes, deletes or holds a credential.
    """
    try:
        caller = ipaddress.ip_address(request.remote_addr or "")
    except ValueError:
        abort(403, f"{what} is only available to a local client")
    if not caller.is_loopback:
        abort(403, f"{what} is only available to a local client")


def template_info() -> Dict[str, str]:
    """Which template this tool was built on, and where to read about it."""
    version = str(getattr(identity, "TEMPLATE_VERSION", "") or "unknown")
    base = getattr(identity, "TEMPLATE_URL", "")
    released = re.fullmatch(r"v\d+(\.\d+)*", version) is not None
    return {"name": getattr(identity, "TEMPLATE_NAME", "template"),
            "version": version, "released": released, "repo": base,
            # a release has notes; an unreleased commit only has the history
            "url": f"{base}/releases/tag/{version}" if released and base
                   else (f"{base}/commits/main" if base else "")}


# ----------------------------------------------------------------- routes ---

@bp.get("/api/health")
def health():
    return jsonify({"ok": True, "tool": identity.TOOL_NAME,
                    "version": ver.__version__, "pid": os.getpid()})


@bp.get("/api/version")
def version_info():
    """Installed vs published, and the rest of the About box. Never fails."""
    installed = ver.__version__
    found = ver.latest_version(force=request.args.get("force") == "1")
    latest = found.get("version")
    behind = bool(latest and ver.version_tuple(str(latest)) > ver.version_tuple(installed))
    extras: Dict[str, str] = {}
    for provider in _about_extras:
        try:
            extras.update(provider())
        except Exception as exc:                  # noqa: BLE001 - About must open
            extras["!"] = f"could not describe: {exc}"
    return jsonify({
        "tool": identity.TOOL_NAME,
        "title": identity.TITLE,
        "description": identity.DESCRIPTION,
        "installed": installed,
        "latest": latest,
        "update_available": behind,
        "checked": found.get("checked"),
        "disabled": found.get("disabled", False),
        "offline": bool(found.get("error")),
        "repo": identity.REPO_URL,
        "releases": f"{identity.REPO_URL}/releases",
        "licence": identity.LICENCE,
        "licence_url": identity.LICENCE_URL,
        "copyright": identity.COPYRIGHT,
        "disclaimer": identity.DISCLAIMER,
        "coffee": identity.COFFEE_URL,
        "install": ver.install_kind(),
        "web_command": identity.WEB_COMMAND,
        "template": template_info(),
        "extras": extras,
    })


@bp.get("/api/services")
def services_info():
    """Every part of the tool and its state, for the About box. Never fails."""
    return jsonify({"services": services.describe()})


@bp.post("/api/mcp/heartbeat")
def mcp_heartbeat():
    """The MCP server's pulse. Loopback only: nothing off the machine is ours."""
    only_local("the MCP heartbeat")
    data = request.get_json(silent=True) or {}
    pid = data.get("pid")
    services.beat(str(request.headers.get("X-Agent") or ""),
                  pid if isinstance(pid, int) else None)
    return jsonify({"ok": True, "every": services.BEAT_EVERY})


@bp.get("/api/agent")
def agent_info():
    """How to point an agent at this tool, and whether one is talking to us."""
    return jsonify(agent.describe())


@bp.post("/api/agent/write")
def agent_write():
    """Write one client's config file, after the person asked for that file.

    Loopback only, like every other route that writes: this puts a file
    somewhere of the caller's choosing. The path is not taken from the request
    -- only the target id is -- so a page cannot name an arbitrary file.
    """
    only_local("writing an agent configuration")
    data = request.get_json(silent=True) or {}
    found = agent.target(str(data.get("target") or ""))
    if found is None or not agent.available():
        abort(400, "no such agent target")
    if not found["path"]:
        abort(400, f"{found['name']} has no configuration file to write")
    try:
        written = agent.write_config(str(found["id"]))
    except OSError as exc:
        abort(500, f"could not write it: {exc}")
    return jsonify({"written_to": written, "target": found["id"]})


@bp.post("/api/shutdown")
def shutdown():
    """Stop the server: the red button in the header, run.sh --stop, and MCP."""
    only_local("shutdown")
    # answer first, exit a beat later; werkzeug has no in-request shutdown hook
    threading.Timer(0.4, lambda: os._exit(0)).start()
    return jsonify({"stopping": True})


@bp.post("/api/restart")
def restart():
    """Start the server again on the same port, picking up changed code."""
    only_local("restart")
    threading.Timer(0.4, _reexec).start()
    return jsonify({"restarting": True})


@bp.post("/api/update")
def update():
    """Upgrade an installed copy in place. The caller restarts afterwards.

    Deliberately not automatic: pip rewrites the files this process is running
    from, so the new code only takes effect on a restart, and a restart into a
    half-finished install is worse than staying put. The output comes back
    whatever happens, because a failed upgrade is exactly when you want to read
    what pip said.
    """
    only_local("update")
    if ver.install_kind() != "installed":
        return jsonify({
            "ok": False, "kind": "checkout",
            "output": "This is a source checkout, not an installed package. "
                      "Update it with:  git pull",
        }), 400

    want = ver.latest_version().get("version")
    ref = f"v{want}" if want else identity.DEFAULT_BRANCH
    target = f"{identity.REPO_URL}@{ref}"
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", f"git+{target}"]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as exc:
        return jsonify({"ok": False, "kind": "installed",
                        "output": f"could not run pip: {exc}"}), 500

    tail = (done.stdout + done.stderr).strip().splitlines()
    return jsonify({"ok": done.returncode == 0, "kind": "installed",
                    "target": target,
                    "output": "\n".join(tail[-14:]) or "(pip said nothing)"})


def _reexec() -> None:
    """Replace this process with a fresh one, same arguments, same directory.

    execv rather than spawn-and-exit: the new server inherits the working
    directory, which user folders are resolved against, and there is no window
    where two of them are alive fighting for the port.

    The listening socket has to be closed by hand first. Python marks its own
    descriptors non-inheritable, but werkzeug's does survive the exec, and the
    replacement then cannot bind: "Address already in use" on the port it just
    vacated. Everything above stdio goes; stdout and stderr stay so the new
    server can still log.
    """
    try:
        os.closerange(3, 1024)
    except OSError:                      # nothing to close, or not permitted
        pass
    os.execv(sys.executable,
             [sys.executable, "-m", f"{identity.PACKAGE}.app", *sys.argv[1:]])


# ------------------------------------------------------------------- main ---

def add_server_args(ap: argparse.ArgumentParser,
                    default_port: int = identity.DEFAULT_PORT) -> None:
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=default_port)
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--no-update-check", action="store_true",
                    help="never contact github.com to compare versions")
    ap.add_argument("--version", action="version",
                    version=f"{identity.TOOL_NAME} {ver.__version__} "
                            f"(built on {template_info()['name']} "
                            f"{template_info()['version']})")


def on_a_network(host: str) -> bool:
    """Whether this host makes the server reachable from another machine."""
    if host in ("", "0.0.0.0", "::"):
        return True
    if host == "localhost":
        return False
    try:
        return not ipaddress.ip_address(host).is_loopback
    except ValueError:
        return True                 # a name we cannot judge: assume the worst


def serve(app: Flask, args: argparse.Namespace,
          lines: Iterable[str] = (), network_note: Optional[str] = None) -> int:
    """Print the startup block, warn if exposed, and serve until stopped.

    The startup block is flushed line by line: run.sh and run.cmd may send
    stdout to a log, where it is block-buffered, and a startup line that turns
    up four kilobytes later is no use to anyone.
    """
    ver.UPDATE_CHECK = not args.no_update_check
    services.listening(args.host, args.port)
    say = lambda text="": print(text, flush=True)   # noqa: E731
    for line in lines:
        say(line)
    say(f"  version       {ver.__version__}"
        + ("" if ver.UPDATE_CHECK else "  (update check off)"))
    say(f"  template      {template_info()['name']} {template_info()['version']}")
    where = "localhost" if args.host in ("", "0.0.0.0", "::") else args.host
    say(f"  listening on  http://{where}:{args.port}")

    if on_a_network(args.host):
        # Werkzeug's stock "development server" banner is replaced, not added
        # to: printed every time it teaches that warnings from this program are
        # noise. This is the one case that is actually dangerous.
        print(f"\n  ! --host {args.host} makes this reachable from other machines "
              "on your network.\n"
              + (network_note or "    Shutdown, restart and update stay refused "
                 "to them; the tool's own pages do not."),
              file=sys.stderr, flush=True)

    if args.debug:
        app.run(host=args.host, port=args.port, debug=True)
        return 0

    # make_server rather than app.run: app.run goes through run_simple, which
    # prints werkzeug's banner. That warning is for someone deploying a web app;
    # this is a local single-user tool, and the banner only hides the lines above.
    from werkzeug.serving import make_server
    try:
        server = make_server(args.host, args.port, app, threaded=True)
    except OSError as exc:
        print(f"  ! cannot listen on {args.host}:{args.port}: {exc.strerror or exc}",
              file=sys.stderr, flush=True)
        return 1
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        say("\n  stopped")
    return 0
