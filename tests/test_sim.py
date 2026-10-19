# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Atelier-5
"""Starting the virtual table and passing the page's calls to the robot: without Webots or Docker."""

import os
from pathlib import Path

import pytest

from atl import sim


def test_webots_opens_the_table_on_its_own_port_with_or_without_a_window():
    cmd = sim.webots_command("/snap/bin/webots", Path("/t/table.wbt"))
    assert cmd[0] == "/snap/bin/webots" and cmd[-1] == "/t/table.wbt"
    assert f"--port={sim.WEBOTS_PORT}" in cmd and "--batch" in cmd and "--minimize" not in cmd
    headless = sim.webots_command("/snap/bin/webots", Path("/t/table.wbt"), gui=False)
    assert "--no-rendering" in headless and "--minimize" in headless


def test_webots_does_not_inherit_another_snaps_environment():
    env = sim.webots_env({"SNAP": "/snap/pycharm-community/662", "SNAP_NAME": "pycharm-community",
                          "LD_LIBRARY_PATH": "/opt/ros/foxy/lib", "DISPLAY": ":0", "HOME": "/home/me"})
    assert env == {"DISPLAY": ":0", "HOME": "/home/me"}


def test_the_body_runs_as_this_user_on_the_host_network_with_the_twin_at_the_same_path():
    cmd = sim.body_command(Path("/home/me/twin"))
    assert cmd[:4] == ["docker", "run", "-d", "--rm"] and "--net=host" in cmd
    assert cmd[cmd.index("--user") + 1] == f"{os.getuid()}:{os.getgid()}"          # nothing it writes belongs to root
    assert "/home/me/twin:/home/me/twin" in cmd and sim.IMAGE in cmd
    assert "table:=/home/me/twin/table.json" in cmd
    assert f"webots_port:={sim.WEBOTS_PORT}" in cmd and f"port:={sim.GATEWAY_PORT}" in cmd


def test_a_status_says_what_is_missing_before_a_start(monkeypatch):
    monkeypatch.setattr(sim, "webots_binary", lambda: None)
    s = sim.Simulation()
    st = s.status()
    assert st["phase"] == "stopped" and set(st["steps"]) == set(sim.STEPS)
    assert any("Webots R2025a is not installed" in m for m in st["missing"])


def test_without_a_gateway_the_robot_is_down(monkeypatch):
    monkeypatch.setattr(sim, "GATEWAY", "http://127.0.0.1:9")          # nothing listens on the discard port
    with pytest.raises(sim.GatewayDown):
        sim.gateway("GET", "/state", timeout=0.5)


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(sim, "GATEWAY", "http://127.0.0.1:9")
    from atl.app import app
    app.config["TESTING"] = True
    return app.test_client()


def test_the_page_gets_a_clear_answer_when_the_simulation_is_not_running(client):
    r = client.get("/api/robot/state", headers={"Host": "127.0.0.1:8780"})
    assert r.status_code == 503 and "not running" in r.get_json()["errors"][0]


def test_only_the_robots_own_actions_pass_through(client):
    h = {"Host": "127.0.0.1:8780", "Origin": "http://127.0.0.1:8780"}
    assert client.post("/api/robot/shutdown", json={}, headers=h).status_code == 404
    assert client.post("/api/robot/drive", json={"linear": 0.1}, headers=h).status_code == 503
    assert set(__import__("atl.app", fromlist=["ROBOT_ACTIONS"]).ROBOT_ACTIONS) == {
        "drive", "behaviour", "button", "clap", "lift", "led", "estop", "reset", "place", "view"}


def test_the_simulation_status_route(client):
    r = client.get("/api/sim", headers={"Host": "127.0.0.1:8780"})
    st = r.get_json()
    assert r.status_code == 200 and st["phase"] in ("stopped", "failed") and "missing" in st
