#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Atelier-5
"""
selftest-twin.py — the whole chain, headless: Webots, the robot's body, its gateway, the ontology.

    .venv/bin/python scripts/selftest-twin.py          (about 2 minutes; Webots and Docker needed)

It starts the virtual table as the app does (atl.sim), without a window, in
mydocs/selftest/, then checks what the spec asks of v0.1 and a little more:

    start        the table runs within the start's own time limits
    rate         the sensors report at 10 Hz or more
    box          a box set in front lights the front sensors; taken away, they go dark
    drive        driving forward moves the odometry and the robot
    estop        the E-stop holds the wheels whatever is sent, until released
    behaviours   each of the six sets its colour on the top LED
    edge         Explorer, set facing the table's edge, does not fall off
    views        each camera view gives a picture, and they differ
    ontology     the robot's A-Box conforms to the shapes; a too fast drive is refused
    reset        the robot goes back to the centre

Every check prints a line; the exit code is the number that failed. One
simulation per PC: stop the app's simulation first.
"""

from __future__ import annotations

import hashlib
import math
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop("PYTHONPATH", None)

from atl import ontology, sim, world  # noqa: E402

TWIN = ROOT / "mydocs" / "selftest"
COLOURS = {"explorer": (1.0, 1.0, 0.0), "friendly": (0.0, 1.0, 0.0), "fearful": (1.0, 0.0, 0.0),
           "inspector": (0.0, 0.8, 1.0), "attentive": (0.0, 0.0, 1.0), "obedient": (1.0, 0.0, 0.6)}
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"  {'✓' if ok else '✗'} {name:<11} {detail}", flush=True)
    return ok


def get():
    return sim.gateway("GET", "/state")


def post(path, body=None):
    return sim.gateway("POST", path, body or {})


def settle(s=0.6):
    time.sleep(s)


def place_robot(x, y, yaw):
    post("/behaviour", {"name": "none"})
    post("/place", {"name": world.SCENE["robot"]["name"], "x": x, "y": y, "yaw": yaw})
    settle(0.8)


def frame():
    import urllib.request
    with urllib.request.urlopen(sim.GATEWAY + "/camera/overview.jpg", timeout=5) as r:
        return r.read()


def run():
    t0 = time.time()
    sim.SIM.start(TWIN, gui=False)
    while sim.SIM.status()["phase"] == "starting":
        time.sleep(0.5)
    st = sim.SIM.status()
    if not check("start", st["phase"] == "running", f"{time.time() - t0:.0f} s" if st["phase"] == "running" else st["error"]):
        for line in st["log"]:
            print("      " + line)
        return
    check("contract", get().get("contract") == "atl-thymio/0.1", get().get("contract", ""))

    # the rate: distinct readings (the twin's sensors are noisy) in two seconds of polling
    seen, end = set(), time.time() + 2.0
    while time.time() < end:
        s = get()
        seen.add(tuple(s.get("ground") or []) + tuple(s.get("acc") or []))
        time.sleep(0.01)
    check("rate", len(seen) / 2.0 >= 10, f"{len(seen) / 2.0:.0f} Hz")

    # the box: its near face 3 cm before the front sensor, then far away
    place_robot(0.0, 0.0, 0.0)
    ahead = 0.0816 + 0.03 + 0.05                     # the front sensor, the gap, half the box
    post("/place", {"name": "carton box", "x": ahead, "y": 0.0, "yaw": 0.0})
    settle()
    near = get()["prox"][2]
    post("/place", {"name": "carton box", "x": 0.45, "y": 0.3, "yaw": 0.0})
    settle()
    far = get()["prox"][2]
    check("box", near > 1000 and far < 100, f"front centre {near:.0f} at 3 cm, {far:.0f} with the box away")

    # driving: 0.1 m/s for 1.5 s, sent again every 0.2 s as the page does
    place_robot(-0.1, 0.0, 0.0)
    o0, p0 = get()["odom"], get()["pose"]
    end = time.time() + 1.5
    while time.time() < end:
        post("/drive", {"linear": 0.1, "angular": 0.0})
        time.sleep(0.2)
    post("/drive", {"linear": 0.0, "angular": 0.0})
    settle()
    o1, p1 = get()["odom"], get()["pose"]
    dodom, dpose = o1["x"] - o0["x"], math.hypot(p1["x"] - p0["x"], p1["y"] - p0["y"])
    check("drive", 0.1 < dodom < 0.2 and abs(dodom - dpose) < 0.03, f"odometry +{dodom:.3f} m, the robot moved {dpose:.3f} m")

    # the E-stop: wheels still while driving is asked
    post("/estop", {"on": True})
    for _ in range(5):
        post("/drive", {"linear": 0.1, "angular": 0.0})
        time.sleep(0.2)
    held = max(abs(w) for w in get()["wheels"])
    post("/estop", {"on": False})
    post("/drive", {"linear": 0.0, "angular": 0.0})
    check("estop", held < 0.05 and not get()["estop"], f"wheels at most {held:.2f} rad/s while held, released after")

    # the behaviours and their colours
    wrong = []
    for name, colour in COLOURS.items():
        place_robot(0.0, 0.0, 0.0)
        post("/behaviour", {"name": name})
        settle(0.8)
        s = get()
        led = s.get("led") or [0, 0, 0]
        if s["behaviour"]["behaviour"] != name or any(abs(a - b) > 0.05 for a, b in zip(led, colour)):
            wrong.append(f"{name}: {s['behaviour']['behaviour']}, led {led}")
    post("/behaviour", {"name": "none"})
    check("behaviours", not wrong, "; ".join(wrong) or "each sets its colour on the top LED")

    # the edge: Explorer set 15 cm from the long edge, facing it, for 20 s
    place_robot(0.45, 0.1, 0.0)
    post("/behaviour", {"name": "explorer"})
    lowest, escapes, last, end = 1.0, 0, "", time.time() + 20
    while time.time() < end:
        s = get()
        lowest = min(lowest, s["pose"]["z"])
        doing = s["behaviour"]["doing"]
        escapes += doing.startswith("edge") and not last.startswith("edge")
        last = doing
        time.sleep(0.1)
    post("/behaviour", {"name": "none"})
    check("edge", lowest > -0.01 and escapes > 0, f"{escapes} escapes in 20 s, lowest {lowest:+.3f} m")

    # the camera's views
    place_robot(0.1, -0.1, 0.8)
    shots = {}
    for view in ("table", "follow", "top"):
        post("/view", {"view": view})
        settle(1.0)
        shots[view] = hashlib.sha1(frame()).hexdigest()
    check("views", len(set(shots.values())) == 3 and get()["view"] == "top", ", ".join(shots))

    # the ontology: the A-Box the body serves, against the shapes atl-ide holds
    g = ontology.abox_from(sim.gateway_text("/robot.ttl"))
    ok, why = ontology.conforms(g)
    refused = ontology.check(g, "drive", {"linear": 0.5, "angular": 0.0})
    check("ontology", ok and bool(refused) and not ontology.check(g, "drive", {"linear": 0.1, "angular": 0.0}),
          f"{len(g)} triples, conforms; drive 0.5 m/s: {refused[0] if refused else 'accepted!'}" if ok else "; ".join(why))

    # reset
    post("/reset")
    settle(1.0)
    p = get()["pose"]
    check("reset", math.hypot(p["x"], p["y"]) < 0.01, f"robot at ({p['x']:+.3f}, {p['y']:+.3f})")


if __name__ == "__main__":
    if sim.SIM.missing():
        sys.exit("cannot start: " + "; ".join(sim.SIM.missing()))
    try:
        sim.gateway("GET", "/state", timeout=0.5)
        sys.exit("a simulation is already running on this PC: stop it first (Table screen, Stop)")
    except sim.GatewayDown:
        pass
    print(f"atl-ide self-test: the virtual table, headless, in {TWIN.relative_to(ROOT)}/")
    try:
        run()
    except (sim.GatewayDown, sim.GatewayRefused, KeyError) as err:
        check("gateway", False, f"{type(err).__name__}: {err}")
    finally:
        sim.SIM.stop()
    failed = results.count(False)
    print(f"{len(results) - failed} of {len(results)} passed")
    sys.exit(failed)
