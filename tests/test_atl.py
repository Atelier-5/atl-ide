# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Atelier-5
"""Tests for the sample engine and routes. Replace them along with the sample."""

from __future__ import annotations

import pytest

from atl import app as web
from atl import engine as engine
from atl.core import version
from atl.core import workspace as ws

NOTE = {"title": "Kick-off", "body": "one two\nthree", "tags": ["b", "a", "b"]}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(version, "UPDATE_CHECK", False)
    monkeypatch.setitem(ws.FOLDERS, ws.USER, tmp_path / "user")
    monkeypatch.setitem(ws.FOLDERS, ws.SHARED, tmp_path / "shared")
    ws.configure()
    web.app.config["TESTING"] = True
    return web.app.test_client()


def test_a_good_note_is_valid():
    assert engine.validate(NOTE) == []


@pytest.mark.parametrize("bad, message", [
    ([], "JSON object"),
    ({"body": "x"}, "title is required"),
    ({"title": "x" * 200}, "keep it to"),
    ({"title": "t", "tags": "a,b"}, "list of strings"),
])
def test_a_bad_note_says_what_is_wrong(bad, message):
    assert any(message in e for e in engine.validate(bad))


def test_summary_counts():
    assert engine.summarise(NOTE) == {"title": "Kick-off", "words": 3, "lines": 2, "tags": ["a", "b"]}


def test_cli_summarises_a_file(tmp_path, capsys):
    path = tmp_path / "n.json"
    path.write_text('{"title": "t", "body": "a b"}', encoding="utf-8")
    assert engine.main(["summarise", str(path)]) == 0
    assert '"words": 2' in capsys.readouterr().out


def test_summarise_route_refuses_an_invalid_note(client):
    got = client.post("/api/summarise", json={"note": {"body": "no title"}})
    assert got.status_code == 400 and "title is required" in got.get_json()["errors"]


def test_save_read_and_list(client):
    saved = client.put("/api/notes/kick-off", json={"note": NOTE}).get_json()
    assert saved["folder"] == "user"
    got = client.get("/api/notes/kick-off").get_json()
    assert got["data"] == NOTE and got["version"] == saved["version"]
    assert [n["name"] for n in client.get("/api/notes").get_json()] == ["kick-off"]


def test_a_stale_save_is_refused_with_the_current_note(client):
    first = client.put("/api/notes/n", json={"note": NOTE}).get_json()
    client.put("/api/notes/n", json={"note": {**NOTE, "title": "theirs"},
                                     "base_version": first["version"]})
    clash = client.put("/api/notes/n", json={"note": {**NOTE, "title": "mine"},
                                             "base_version": first["version"]})
    assert clash.status_code == 409
    assert clash.get_json()["note"]["title"] == "theirs"


def test_a_name_cannot_escape_its_folder(client):
    assert client.get("/api/notes/..%2F..%2Fetc").status_code in (400, 404)
    assert client.put("/api/notes/a.b", json={"note": NOTE}).status_code == 400


def test_the_shared_samples_ship():
    from pathlib import Path
    shipped = Path(web.__file__).resolve().parent / "shared"
    assert list(shipped.glob("*.json")), "the package should carry at least one sample"
