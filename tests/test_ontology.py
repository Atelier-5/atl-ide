# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Atelier-5
"""The robot ontology: the T-Box and shapes, a robot's A-Box, and requests checked against them."""

from pathlib import Path

import pytest
from rdflib import Literal, URIRef
from rdflib.namespace import RDF

from atl import ontology as o

ABOX = (Path(__file__).parent / "data" / "thymio_1.ttl").read_text()


@pytest.fixture(scope="module")
def g():
    return o.abox_from(ABOX)


def test_the_thymios_a_box_keeps_the_shapes(g):
    ok, messages = o.conforms(g)
    assert ok, messages


def test_a_robot_without_a_name_or_a_sensor_without_a_topic_is_refused(g):
    broken = o.abox_from(ABOX)
    broken.remove((o.the_robot(broken), o.SCHEMA.name, None))
    broken.remove((URIRef(str(o.ATL) + "prox_3"), o.ATL.publishesOn, None))
    ok, messages = o.conforms(broken)
    assert not ok
    assert "A robot needs a name." in messages and "A sensor publishes on a topic of the contract." in messages


def test_the_robot_described_in_the_persons_language(g):
    r = o.robot(g, "fr")
    assert r["name"] == "thymio_1" and r["contract"] == "atl-thymio/0.1"
    assert r["limits"]["maxLinearMs"] == pytest.approx(0.2001)
    centre = next(h for h in r["hosts"] if h["id"] == "prox_2")
    assert centre["kind"] == "capteur de proximité" and centre["aheadOfCentreM"] == pytest.approx(0.0816)
    assert {"situation": "carton box, 5.25 cm away or more", "value": 0, "on": "twin"} in centre["measured"]
    assert sum(h["kind"] == "capteur de proximité" for h in r["hosts"]) == 7
    assert o.robot(g, "de")["hosts"][0]["kind"] in ("Beschleunigungssensor", "Radgeber", "Bodensensor", "Licht", "Motor", "Abstandssensor")


def test_only_the_emergency_stop_needs_no_confirmation(g):
    cmds = {c["name"]: c for c in o.commands(g)}
    assert set(cmds) == {"drive", "behaviour", "button", "clap", "lift", "led", "estop", "reset", "place"}
    assert [n for n, c in cmds.items() if not c["needsConfirmation"]] == ["estop"]
    drive = {p["key"]: p for p in cmds["drive"]["parameters"]}
    assert drive["linear"]["min"] == -0.2 and drive["linear"]["max"] == 0.2 and drive["angular"]["max"] == 4.0


@pytest.mark.parametrize("name, params", [
    ("drive", {"linear": 0.1, "angular": 0.0}), ("behaviour", {"name": "inspector"}), ("button", {"name": "center"}),
    ("clap", {"n": 3}), ("lift", {"up": True}), ("led", {"r": 1, "g": 0.5, "b": 0}), ("estop", {"on": False}),
    ("place", {"name": "wooden block", "x": -0.3, "y": 0.1}), ("reset", {}),
])
def test_what_the_robot_can_do_is_accepted(g, name, params):
    assert o.check(g, name, params) == []


@pytest.mark.parametrize("name, params, says", [
    ("drive", {"linear": 0.5, "angular": 0.0}, "Forward speed is between -0.2 and 0.2 m/s"),
    ("drive", {"linear": 0.0, "angular": -9.0}, "Turning speed is between -4 and 4 rad/s."),
    ("behaviour", {"name": "dancer"}, "A behaviour is friendly, explorer"),
    ("button", {"name": "up"}, "A button is forward, backward, left, right or center."),
    ("clap", {"n": 4}, "Clap 1, 2 or 3 times."),
    ("led", {"r": 0, "g": 0, "b": 1.5}, "Blue is between 0 and 1."),
    ("place", {"name": "carton box", "x": 0.9, "y": 0.0}, "x is on the table: -0.6 to 0.6 m."),
    ("fly", {}, "'fly' is not a command of this robot"),
    ("drive", {"speed": 1}, "drive takes no speed"),
])
def test_what_it_cannot_do_is_refused_in_words(g, name, params, says):
    errors = o.check(g, name, params)
    assert errors and any(says in e for e in errors), errors


def test_the_last_robot_seen_describes_it_while_it_is_off(tmp_path):
    def fails():
        raise ConnectionError("the gateway is off")
    with pytest.raises(o.NoRobot):
        o.Robots(fails, lambda: tmp_path).abox()
    o.Robots(lambda: ABOX, lambda: tmp_path).abox()                     # seen once: kept
    assert o.the_robot(o.Robots(fails, lambda: tmp_path).abox()).endswith("thymio_1")
