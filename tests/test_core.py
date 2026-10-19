# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
The core's promises, checked in this tool.

Core-owned (D-LAB-5 tool template): `copier update` rewrites this file. Tool
tests go in their own files.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from atl import app as web
from atl import engine as cli
from atl.core import agent, identity, services, skill_install, version

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / identity.PACKAGE
FAR_AWAY = {"REMOTE_ADDR": "10.11.12.13"}
LOCAL = {"REMOTE_ADDR": "127.0.0.1"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(version, "UPDATE_CHECK", False)   # never the network in tests
    web.app.config["TESTING"] = True
    return web.app.test_client()


# ---------------------------------------------------------------- server ----

def test_health_names_this_tool(client):
    got = client.get("/api/health").get_json()
    assert got["tool"] == identity.TOOL_NAME
    assert got["version"] == version.__version__


def test_the_template_version_is_in_the_code_and_in_about(client):
    assert identity.TEMPLATE_VERSION and identity.TEMPLATE_VERSION != "unknown"
    answers = ROOT / ".copier-answers.yml"
    if answers.is_file():                     # a checkout: both must say the same
        recorded = re.search(r"^_commit:\s*(\S+)", answers.read_text(encoding="utf-8"), re.M)
        assert recorded and recorded.group(1) == identity.TEMPLATE_VERSION
    about = client.get("/api/version").get_json()["template"]
    assert about["version"] == identity.TEMPLATE_VERSION
    assert about["name"] == "python-tool-template"
    assert about["url"].startswith("https://github.com/ERP-LAB-5/python-tool-template")


def test_version_answers_offline(client):
    got = client.get("/api/version").get_json()
    assert got["installed"] == version.__version__
    assert got["disabled"] is True and got["update_available"] is False
    assert got["repo"] == identity.REPO_URL


@pytest.mark.parametrize("path", ["/api/shutdown", "/api/restart", "/api/update"])
def test_lifecycle_is_refused_from_off_the_machine(client, path):
    assert client.post(path, environ_base=FAR_AWAY).status_code == 403


def test_lifecycle_is_post_only(client):
    # a GET from a link in another tab must not stop the server
    assert client.get("/api/shutdown", environ_base=LOCAL).status_code == 405


def test_update_from_a_checkout_says_git_pull(client):
    if version.install_kind() != "checkout":
        pytest.skip("installed copy")
    got = client.post("/api/update", environ_base=LOCAL)
    assert got.status_code == 400 and "git pull" in got.get_json()["output"]


def test_errors_come_back_as_json(client):
    got = client.get("/api/no-such-route")
    assert got.status_code == 404 and got.get_json()["errors"]


def test_the_page_extends_the_core_shell(client):
    html = client.get("/").get_data(as_text=True)
    assert "/core-static/core.js" in html and 'id="core-about"' in html


@pytest.mark.parametrize("asset", ["core.js", "core.css", "dlab5.png"])
def test_core_static_is_served(client, asset):
    assert client.get(f"/core-static/{asset}").status_code == 200


def test_network_detection():
    from atl.core.server import on_a_network
    assert not on_a_network("127.0.0.1") and not on_a_network("localhost")
    assert on_a_network("0.0.0.0") and on_a_network("192.168.1.5")


# ----------------------------------------------------------------- agent ----
#
# These exist because the panel is only as good as the config it hands over: a
# snippet naming a module that was never generated, or a write that throws away
# somebody else's servers, would both look fine on screen.

def test_agent_route_answers(client):
    got = client.get("/api/agent").get_json()
    assert got["tool"] == identity.TOOL_NAME
    assert got["available"] is bool(identity.WITH_MCP)


@pytest.mark.skipif(not identity.WITH_MCP, reason="tool built without MCP")
def test_every_target_configures_the_module_that_exists(client):
    got = client.get("/api/agent").get_json()
    assert got["targets"], "an MCP tool should offer somewhere to connect from"
    for target in got["targets"]:
        entry = json.loads(target["config"])
        key = next(iter(entry))
        assert key in ("mcpServers", "servers")
        mine = entry[key][identity.TOOL_NAME]
        # the module has to be the one the package actually ships
        assert mine["args"][:2] == ["-m", f"{identity.PACKAGE}.mcp_server"]
        assert Path(mine["command"]).is_absolute(), "an agent has its own PATH"
    assert (PKG / "mcp_server.py").is_file()


@pytest.mark.skipif(not identity.WITH_MCP, reason="tool built without MCP")
def test_writing_a_config_keeps_servers_that_are_already_there():
    existing = json.dumps({"mcpServers": {"someone-else": {"command": "x"}}})
    merged = json.loads(agent.merge_into(existing, "claude-code"))
    assert "someone-else" in merged["mcpServers"], "never drop another server"
    assert identity.TOOL_NAME in merged["mcpServers"]


@pytest.mark.skipif(not identity.WITH_MCP, reason="tool built without MCP")
def test_writing_a_config_replaces_only_our_own_entry():
    first = agent.merge_into("", "claude-code")
    twice = agent.merge_into(first, "claude-code")
    assert json.loads(twice) == json.loads(first), "writing twice is the same"


@pytest.mark.skipif(not identity.WITH_MCP, reason="tool built without MCP")
def test_the_vscode_shape_differs_from_the_claude_one():
    # the whole reason this module exists: same server, two spellings
    assert "servers" in json.loads(agent.snippet("vscode"))
    assert "mcpServers" in json.loads(agent.snippet("claude-code"))
    assert json.loads(agent.snippet("vscode"))["servers"][identity.TOOL_NAME]["type"] == "stdio"


def test_writing_a_config_is_refused_from_off_the_machine(client):
    got = client.post("/api/agent/write", json={"target": "claude-code"},
                      environ_base=FAR_AWAY)
    assert got.status_code == 403


def test_an_unknown_target_is_refused(client):
    got = client.post("/api/agent/write", json={"target": "no-such-agent"},
                      environ_base=LOCAL)
    assert got.status_code == 400


def test_an_agent_calling_marks_itself_seen(client):
    assert client.get("/api/agent").get_json()["status"]["connected"] is False
    client.get("/api/health", headers={"X-Agent": "test-harness"})
    status = client.get("/api/agent").get_json()["status"]
    assert status["connected"] is True and status["client"] == "test-harness"
    # and the page must never claim it can start one
    assert status["startable"] is False


# -------------------------------------------------------------- services ----

@pytest.fixture
def fresh_services(monkeypatch):
    monkeypatch.setattr(services, "_registered", [])
    monkeypatch.setitem(services._beat, "at", 0.0)
    monkeypatch.setitem(services._beat, "pid", None)
    return services


def by_id(client):
    rows = client.get("/api/services").get_json()["services"]
    return {row["id"]: row for row in rows}


def test_every_part_is_listed_with_a_state(client, fresh_services):
    rows = by_id(client)
    assert {"web", "mcp", "updates", "skill", "workspace"} <= set(rows)
    assert all(row["state"] in ("up", "down", "off") for row in rows.values())
    assert rows["web"]["state"] == "up"
    assert rows["updates"]["state"] == "off"          # the fixture turns it off


def test_a_part_this_tool_was_built_without_is_grey(client, fresh_services):
    rows = by_id(client)
    assert (rows["mcp"]["state"] == "off") is not bool(identity.WITH_MCP)
    assert (rows["workspace"]["state"] == "off") is not bool(identity.WITH_WORKSPACE)


@pytest.mark.skipif(not identity.WITH_MCP, reason="no MCP server in this tool")
def test_the_mcp_server_is_up_while_it_beats(client, fresh_services, monkeypatch):
    assert by_id(client)["mcp"]["state"] == "down"
    got = client.post("/api/mcp/heartbeat", json={"pid": 4242},
                      headers={"X-Agent": "test-mcp"}, environ_base=LOCAL)
    assert got.status_code == 200
    row = by_id(client)["mcp"]
    assert row["state"] == "up" and "4242" in row["detail"]
    monkeypatch.setitem(services._beat, "at", services._beat["at"] - services.ALIVE_FOR - 5)
    assert by_id(client)["mcp"]["state"] == "down"


def test_a_heartbeat_does_not_count_as_an_agent_working(client, fresh_services, monkeypatch):
    monkeypatch.setitem(agent._seen, "at", 0.0)
    client.post("/api/mcp/heartbeat", json={}, headers={"X-Agent": "test-mcp"},
                environ_base=LOCAL)
    assert client.get("/api/agent").get_json()["status"]["connected"] is False


def test_a_heartbeat_from_off_the_machine_is_refused(client, fresh_services):
    got = client.post("/api/mcp/heartbeat", json={}, environ_base=FAR_AWAY)
    assert got.status_code == 403


def test_a_tools_own_service_reports_all_three_states(client, fresh_services):
    services.register("on", "Working", check=lambda: (True, "fine"))
    services.register("bad", "Broken", check=lambda: (False, "refused the token"))
    services.register("unset", "Unset", check=lambda: (True, ""),
                      enabled=lambda: (False, "add a token under Settings"))
    services.register("boom", "Exploding", check=lambda: 1 / 0)
    rows = by_id(client)
    assert (rows["on"]["state"], rows["on"]["detail"]) == ("up", "fine")
    assert (rows["bad"]["state"], rows["bad"]["detail"]) == ("down", "refused the token")
    assert (rows["unset"]["state"], rows["unset"]["detail"]) == ("off", "add a token under Settings")
    assert rows["boom"]["state"] == "down" and "division" in rows["boom"]["detail"]


def test_a_slow_service_cannot_hold_the_about_box_open(client, fresh_services, monkeypatch):
    import time
    monkeypatch.setattr(services, "CHECK_TIMEOUT", 0.3)
    services.register("slow", "Slow", check=lambda: (time.sleep(3), (True, ""))[1])
    started = time.monotonic()
    rows = by_id(client)
    assert time.monotonic() - started < 2
    assert rows["slow"]["state"] == "down" and "did not answer" in rows["slow"]["detail"]


def test_the_skill_counts_as_installed_in_a_checkout_that_carries_it(
        client, fresh_services, monkeypatch, tmp_path):
    monkeypatch.setattr(skill_install, "destination", lambda *a: tmp_path / "SKILL.md")
    row = by_id(client)["skill"]
    if skill_install.checkout_copies():               # a checkout: its own copy counts
        assert row["state"] == "up" and "checkout" in row["detail"]
    monkeypatch.setattr(skill_install, "checkout_copies", lambda: [])
    row = by_id(client)["skill"]
    assert row["state"] == "down" and "not installed" in row["detail"]


@pytest.mark.skipif(not identity.WITH_MCP, reason="no MCP server in this tool")
def test_a_bridge_error_is_one_the_mcp_sdk_delivers_to_the_model():
    from mcp.server.mcpserver.exceptions import ToolError as Delivered
    from atl.core import mcp_bridge
    assert issubclass(mcp_bridge.ToolError, Delivered)
    assert issubclass(mcp_bridge.ToolError, ValueError)        # old catches still work
    assert issubclass(mcp_bridge.NotAnswering, ConnectionError)


def test_the_about_box_asks_for_the_services(client):
    js = (PKG / "core" / "static" / "core.js").read_text(encoding="utf-8")
    assert "/api/services" in js


def test_the_page_offers_connect_only_when_there_is_an_mcp_server(client):
    html = client.get("/").get_data(as_text=True)
    assert ('id="core-connect"' in html) is bool(identity.WITH_MCP)


# ------------------------------------------------------------- packaging ----

def test_package_data_ships_what_the_server_reads():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for needed in ('"VERSION"', '"templates/*.html"', '"static/*"', '"skill/*.md"',
                   '"templates/core/*.html"'):
        assert needed in text, f"pyproject package-data is missing {needed}"
    assert f'"{identity.PACKAGE}.core"' in text


def test_version_is_one_number_everywhere():
    wanted = (PKG / "VERSION").read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", wanted)
    manifest = ROOT / "plugin" / ".claude-plugin" / "plugin.json"
    if manifest.exists():
        assert json.loads(manifest.read_text(encoding="utf-8"))["version"] == wanted
    pinned = ROOT / "plugin" / "bin" / "VERSION"
    if pinned.exists():
        assert pinned.read_text(encoding="utf-8").strip() == wanted


# ----------------------------------------------------------------- skill ----

def test_the_skill_ships_with_the_package():
    assert skill_install.packaged().is_file()


def test_every_skill_copy_is_in_step():
    copies = skill_install.checkout_copies()
    assert copies, "a checkout should hold .claude/skills and plugin copies"
    assert skill_install.main(["--check"]) == 0


def test_skill_frontmatter_names_this_tool():
    text = skill_install.packaged().read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert match, "SKILL.md must open with a YAML frontmatter block"
    front = match.group(1)
    assert re.search(r"^name: (.+)$", front, re.M).group(1) == identity.SKILL_NAME
    assert re.search(r"^description: .{40,}$", front, re.M), "describe when to use it"


def test_every_command_the_skill_names_exists():
    """The skill tells an agent what to run; the parser has to accept it."""
    text = skill_install.packaged().read_text(encoding="utf-8")
    documented = set(re.findall(rf"^{re.escape(identity.CLI_COMMAND)} ([a-z][\w-]*)", text, re.M))
    for command in documented:
        with pytest.raises(SystemExit) as done:          # --help exits 0 after printing
            cli.main([command, "--help"])
        assert done.value.code == 0, f"`{identity.CLI_COMMAND} {command}` is not a command"
