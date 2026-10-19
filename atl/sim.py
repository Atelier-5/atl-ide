# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Atelier-5
"""
sim.py — start and stop the virtual table: Webots on this PC, the robot's body in its container.

    start  1. world.py writes table.wbt, table.json and table_top.png into the workspace (mydocs/twin)
           2. Webots opens table.wbt on WEBOTS_PORT; its two robots (thymio_1, atl_sup) wait as <extern>
           3. the body's container (atl-bot-thymio, ROS 2 Kilted) connects both and starts the gateway
           4. the gateway answers on GATEWAY_PORT with fresh sensor values: running
    stop   the container, then Webots. Closing the Webots window stops the body too.

One simulation per PC: the ports are fixed for now. Standard library only, so the
page, the MCP server and the self-test share it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import world

WEBOTS_PORT = 1240
GATEWAY_PORT = 8781
GATEWAY = f"http://127.0.0.1:{GATEWAY_PORT}"
IMAGE = os.environ.get("ATL_IDE_BOT_IMAGE", "atl-bot-thymio:kilted")
CONTAINER = "atl-bot-thymio"
WAIT_WEBOTS = 90.0           # s until both robots wait for their controllers
WAIT_BODY = 90.0             # s until the gateway reports fresh sensor values

STEPS = ("world", "webots", "body", "gateway")


def webots_binary() -> Optional[str]:
    """The Webots launcher: the snap's, else whatever `webots` is on PATH."""
    for candidate in (os.environ.get("ATL_IDE_WEBOTS"), "/snap/bin/webots", shutil.which("webots")):
        if candidate and os.access(candidate, os.X_OK):
            return candidate
    return None


def webots_command(binary: str, table: Path, gui: bool = True) -> List[str]:
    cmd = [binary, "--batch", "--mode=realtime", f"--port={WEBOTS_PORT}", "--stdout", "--stderr"]
    if not gui:
        cmd += ["--minimize", "--no-rendering"]
    return cmd + [str(table)]


def body_command(twin: Path) -> List[str]:
    """The container: host network (Webots and the gateway on 127.0.0.1), the twin folder at the same path
    inside and out, and this user's uid, so nothing it writes belongs to root."""
    return ["docker", "run", "-d", "--rm", "--name", CONTAINER, "--net=host",
            "--user", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/tmp", "-v", f"{twin}:{twin}", IMAGE,
            "ros2", "launch", "thymio_twin", "thymio.launch.py", f"table:={twin / 'table.json'}",
            f"webots_port:={WEBOTS_PORT}", f"port:={GATEWAY_PORT}"]


def gateway(method: str, path: str, body: Optional[dict] = None, timeout: float = 3.0) -> Any:
    """One call to the body's gateway; raises GatewayDown when it does not answer."""
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(GATEWAY + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read() or b"{}")
        except ValueError:
            detail = {}
        raise GatewayRefused(e.code, detail.get("error") or str(e)) from None
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
        raise GatewayDown(str(e)) from None


class GatewayDown(Exception):
    """The gateway does not answer: the simulation is not running."""


class GatewayRefused(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


class Simulation:
    """The one simulation of this PC. Its state is safe to read from any thread."""

    def __init__(self):
        self.lock = threading.Lock()
        self.twin: Optional[Path] = None
        self.webots: Optional[subprocess.Popen] = None
        self.phase = "stopped"               # stopped | starting | running | stopping | failed
        self.steps: Dict[str, str] = {s: "todo" for s in STEPS}
        self.error = ""
        self.gui = True
        self.started_at = 0.0

    # -- reading --------------------------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        with self.lock:
            out = {"phase": self.phase, "steps": dict(self.steps), "error": self.error, "gui": self.gui,
                   "twin": str(self.twin) if self.twin else None, "missing": self.missing(),
                   "since": round(time.time() - self.started_at) if self.started_at else 0}
        out["log"] = self.log_tail()
        return out

    def missing(self) -> List[str]:
        """What stops a start, in words a person can act on."""
        out = []
        if not webots_binary():
            out.append("Webots R2025a is not installed: sudo snap install webots")
        if not shutil.which("docker"):
            out.append("Docker is not installed")
        else:
            try:
                r = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, timeout=10)
                if r.returncode != 0:
                    out.append(f"the robot's image {IMAGE} is missing: build it in atl-bot-thymio "
                               f"(docker build -f docker/Dockerfile -t {IMAGE} .)")
            except (OSError, subprocess.TimeoutExpired):
                out.append("Docker does not answer")
        return out

    def log_tail(self, lines: int = 12) -> List[str]:
        if not self.twin:
            return []
        out = []
        for name in ("webots.log", "body.log"):
            p = self.twin / name
            if p.exists():
                text = p.read_text(errors="replace").splitlines()
                keep = [l for l in text if l.strip() and "Cannot download" not in l and "finished with error" not in l]
                out += [f"{name}: {l}" for l in keep[-lines // 2:]]
        return out

    # -- starting and stopping ---------------------------------------------------------------
    def start(self, twin: Path, gui: bool = True) -> Dict[str, Any]:
        with self.lock:
            if self.phase in ("starting", "running"):
                return {"phase": self.phase}
            self.phase, self.error, self.gui, self.twin = "starting", "", gui, twin
            self.steps = {s: "todo" for s in STEPS}
            self.started_at = time.time()
        threading.Thread(target=self._start, name="sim-start", daemon=True).start()
        return {"phase": "starting"}

    def _step(self, name: str, state: str):
        with self.lock:
            self.steps[name] = state

    def _fail(self, message: str):
        with self.lock:
            self.phase, self.error = "failed", message
        self._stop_processes()

    def _start(self):
        missing = self.missing()
        if missing:
            return self._fail("; ".join(missing))
        twin = self.twin
        self._step("world", "now")
        world.write(twin)
        self._step("world", "done")

        self._step("webots", "now")
        self._remove_container()                 # one left over from a crash would hold the name
        log = open(twin / "webots.log", "w")
        self.webots = subprocess.Popen(webots_command(webots_binary(), twin / "table.wbt", self.gui), cwd=twin,
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        waiting = "Waiting for local or remote connection"
        end = time.time() + WAIT_WEBOTS
        while time.time() < end:
            text = (twin / "webots.log").read_text(errors="replace")
            if all(f"{waiting} on port {WEBOTS_PORT} targeting robot named '{r}'" in text
                   for r in ("thymio_1", world.SCENE["supervisor"])):
                break
            if self.webots.poll() is not None:
                return self._fail(f"Webots ended before the table was ready (exit {self.webots.returncode})")
            time.sleep(0.5)
        else:
            return self._fail("Webots did not open the table in time")
        self._step("webots", "done")

        self._step("body", "now")
        with open(twin / "body.log", "w") as blog:
            r = subprocess.run(body_command(twin), stdout=blog, stderr=subprocess.STDOUT, timeout=60)
        if r.returncode != 0:
            return self._fail("the robot's container did not start: see body.log")
        threading.Thread(target=self._follow_body_log, name="sim-body-log", daemon=True).start()
        self._step("body", "done")

        self._step("gateway", "now")
        end = time.time() + WAIT_BODY
        while time.time() < end:
            try:
                if gateway("GET", "/state").get("connected"):
                    break
            except (GatewayDown, GatewayRefused):
                pass
            if self.webots.poll() is not None:
                return self._fail("Webots was closed")
            time.sleep(0.5)
        else:
            return self._fail("the robot did not report its sensors in time: see body.log")
        self._step("gateway", "done")
        with self.lock:
            self.phase = "running"
        threading.Thread(target=self._watch, name="sim-watch", daemon=True).start()

    def _follow_body_log(self):
        with open(self.twin / "body.log", "a") as blog:
            subprocess.run(["docker", "logs", "-f", CONTAINER], stdout=blog, stderr=subprocess.STDOUT)

    def _watch(self):
        """Closing the Webots window (or the container ending) stops the simulation."""
        while True:
            time.sleep(1.0)
            with self.lock:
                if self.phase != "running":
                    return
            if self.webots is not None and self.webots.poll() is not None:
                self.stop("Webots was closed")
                return
            if not self._container_running():
                self._fail("the robot's container ended: see body.log")
                return

    def stop(self, why: str = "") -> Dict[str, Any]:
        with self.lock:
            if self.phase == "stopped":
                return {"phase": "stopped"}
            self.phase = "stopping"
        self._stop_processes()
        with self.lock:
            self.phase, self.error = "stopped", why
            self.steps = {s: "todo" for s in STEPS}
            self.started_at = 0.0
        return {"phase": "stopped"}

    def _stop_processes(self):
        self._remove_container()
        if self.webots is not None and self.webots.poll() is None:
            self.webots.terminate()
            try:
                self.webots.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.webots.kill()
        self.webots = None

    @staticmethod
    def _remove_container():
        if shutil.which("docker"):
            subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True, timeout=30)

    @staticmethod
    def _container_running() -> bool:
        try:
            r = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", CONTAINER], capture_output=True, text=True, timeout=10)
            return r.returncode == 0 and r.stdout.strip() == "true"
        except (OSError, subprocess.TimeoutExpired):
            return False


SIM = Simulation()
