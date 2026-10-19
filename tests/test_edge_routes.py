# SPDX-License-Identifier: GPL-3.0-or-later
"""The edge layer wired into the tool: its routes answer, this machine only,
and the chat can propose only what settings allow."""

from __future__ import annotations

import pytest

from atl.app import app
from atl.edge import settings


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ATL_IDE_EDGE_STATE", str(tmp_path / "cloud.json"))
    monkeypatch.setenv("ATL_IDE_EDGE_DATA", str(tmp_path / "data"))
    return app.test_client()


def test_the_connections_answer_without_a_token(client):
    r = client.get("/api/cloud")
    assert r.status_code == 200
    assert r.get_json()["linked"] is False and "device_token" not in r.get_data(as_text=True)


def test_another_host_name_is_refused(client):
    # DNS rebinding: a page whose own name resolves to 127.0.0.1
    assert client.get("/api/cloud", headers={"Host": "evil.example:8780"}).status_code == 403
    assert client.get("/api/cloud", headers={"Host": "127.0.0.1:8780"}).status_code == 200


def test_a_write_from_another_site_is_refused(client):
    r = client.post("/api/cloud/use", json={"profile": "prod"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_nobody_may_frame_the_page(client):
    r = client.get("/api/cloud")
    assert r.headers["X-Frame-Options"] == "DENY"


def test_the_chat_proposes_only_what_settings_allow(client):
    ok = client.post("/api/chat/proposals", json={"summary": "sync", "method": "POST", "path": "/api/knowledge/sync", "body": {}})
    assert ok.status_code == 201
    bad = client.post("/api/chat/proposals", json={"summary": "x", "method": "POST", "path": "/api/shutdown", "body": {}})
    assert bad.status_code == 400
    assert ("POST", r"/api/knowledge/sync") in settings.CHAT_ALLOWED


def test_linking_needs_an_address(client):
    r = client.post("/api/cloud/link", json={})
    assert r.status_code == 400


def test_knowledge_lists_the_local_a_boxes(client):
    r = client.get("/api/knowledge")
    assert r.status_code == 200 and r.get_json()["graphs"][0]["name"] == "shared"


def test_the_panels_are_served(client):
    assert client.get("/edge-static/edge.js").status_code == 200
