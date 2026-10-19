# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Atelier-5
"""
ontology.py — the robot as data, for the page and for an agent.

Two halves, as the edge layer keeps them (edge/ontology):
  - the T-Box (tbox/atl.ttl, tbox/atl-concepts.ttl): what a robot, a sensor, a
    topic and a command are, a thin layer over SOSA/SSN; and the SHACL shapes
    (shapes/atl-shapes.ttl): what a robot's description and each request must say;
  - the A-Box of the robot that is connected: its body's gateway serves it at
    GET /robot.ttl (atl-bot-thymio generates it from its contract). The last one
    seen is kept in the twin folder, so the robot can be described while it is off.

    robot(lang)            what the robot is: its sensors, actuators, topics, measurements
    sensors(state, lang)   the live readings, each named and placed from the A-Box
    commands(lang)         what it accepts: route, whether a facilitator confirms it, parameters
    check(name, params)    a request against its command's SHACL shape: [] or what is wrong
"""

from __future__ import annotations

import threading
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pyshacl import validate as shacl
from rdflib import BNode, Graph, Literal, Namespace, RDF, RDFS, URIRef
from rdflib.namespace import SKOS, XSD

from .edge import settings

ATL = Namespace("https://atelier-5.github.io/atl/ontology#")
SOSA = Namespace("http://www.w3.org/ns/sosa/")
SCHEMA = Namespace("https://schema.org/")
SH = Namespace("http://www.w3.org/ns/shacl#")

_lock = threading.Lock()
_cache: Dict[str, Graph] = {}


class NoRobot(Exception):
    """No robot has been connected yet: nothing to describe."""


# -- loading ------------------------------------------------------------------------------

def _load(folder: str) -> Graph:
    if folder not in _cache:
        g = Graph()
        for p in sorted((Path(settings.ONTOLOGY) / folder).glob("*.ttl")):
            g.parse(p, format="turtle")
        _cache[folder] = g
    return _cache[folder]


def tbox() -> Graph:
    return _load("tbox")


def shapes() -> Graph:
    return _load("shapes")


def abox_from(text: str) -> Graph:
    return Graph().parse(data=text, format="turtle")


def conforms(g: Graph) -> Tuple[bool, List[str]]:
    """A graph (an A-Box, a request) against the shapes, with the T-Box's classes and concepts."""
    ok, report, _ = shacl(g + tbox(), shacl_graph=shapes(), inference="rdfs", advanced=True)
    if ok:
        return True, []
    messages = {str(m) for m in report.objects(None, SH.resultMessage)}
    ours = {str(m) for m in shapes().objects(None, SH.message)}
    # a shape's own sentence says it best; pyshacl's generic lines only when no shape has one
    return False, sorted(messages & ours) or sorted(messages)


# -- reading the A-Box ---------------------------------------------------------------------

def label(node: URIRef, lang: str = "en", g: Optional[Graph] = None) -> str:
    """A node's label in `lang`, else in English, else its local name."""
    graphs = [x for x in (g, tbox()) if x is not None]
    for want in (lang, "en"):
        for gr in graphs:
            for p in (SKOS.prefLabel, RDFS.label):
                for o in gr.objects(node, p):
                    if getattr(o, "language", None) == want:
                        return str(o)
    return str(node).rsplit("#", 1)[-1]


def _one(g: Graph, s, p, default=None):
    """One value: a Literal as plain Python (a decimal as a float, so JSON carries it), else the node."""
    for o in g.objects(s, p):
        if isinstance(o, Literal):
            v = o.toPython()
            return float(v) if isinstance(v, Decimal) else v
        return o
    return default


def the_robot(g: Graph) -> URIRef:
    for s in g.subjects(RDF.type, ATL.Thymio2):
        return s
    for s in g.subjects(RDF.type, ATL.Robot):
        return s
    raise NoRobot("this A-Box describes no robot")


def robot(g: Graph, lang: str = "en") -> Dict[str, Any]:
    r = the_robot(g)
    kinds = (ATL.ProximitySensor, ATL.GroundSensor, ATL.Accelerometer, ATL.WheelEncoder, ATL.Motor, ATL.Led)
    parts = []
    for part in sorted(g.objects(r, SOSA.hosts), key=str):
        kind = next((k for k in kinds if (part, RDF.type, k) in g), None)
        topics = [str(_one(g, t, ATL.path)) for p in (ATL.publishesOn, ATL.listensOn) for t in g.objects(part, p)]
        parts.append({
            "id": str(part).rsplit("#", 1)[-1], "kind": label(kind, lang) if kind else "", "device": _one(g, part, ATL.deviceName),
            "index": _one(g, part, ATL.index), "side": _one(g, part, ATL.side),
            "aheadOfCentreM": _one(g, part, ATL.aheadOfCentre), "leftOfCentreM": _one(g, part, ATL.leftOfCentre),
            "range": [_one(g, part, ATL.rawMin), _one(g, part, ATL.rawMax)], "unit": _one(g, part, ATL.unit), "topics": topics,
            "measured": [{"situation": str(_one(g, m, ATL.situation)), "value": _one(g, m, ATL.value), "on": _one(g, m, ATL.measuredOn)}
                         for m in g.objects(part, ATL.measured)],
        })
    return {
        "name": _one(g, r, SCHEMA.name), "kind": label(ATL.Thymio2 if (r, RDF.type, ATL.Thymio2) in g else ATL.Robot, lang),
        "contract": _one(g, r, ATL.contract),
        "limits": {"maxLinearMs": _one(g, r, ATL.maxLinear), "maxAngularRadS": _one(g, r, ATL.maxAngular),
                   "wheelRadiusM": _one(g, r, ATL.wheelRadius), "wheelTrackM": _one(g, r, ATL.wheelTrack)},
        "hosts": parts, "commands": [c["name"] for c in commands(g, lang)],
    }


def sensors(g: Graph, state: Dict[str, Any], lang: str = "en") -> Dict[str, Any]:
    """The live readings of /state, named and placed: each value with the sensor it comes from."""
    by_topic: Dict[str, List[Dict[str, Any]]] = {}
    for part in robot(g, lang)["hosts"]:
        for t in part["topics"]:
            by_topic.setdefault(t, []).append(part)
    out: Dict[str, Any] = {"connected": state.get("connected"), "contract": state.get("contract"), "readings": []}
    for key, topic in (("prox", "/thymio_1/prox/horizontal"), ("ground", "/thymio_1/prox/ground"), ("acc", "/thymio_1/acc"),
                       ("wheels", "/thymio_1/wheels")):
        values = state.get(key) or []
        for part in sorted(by_topic.get(topic, []), key=lambda p: p["index"] if p["index"] is not None else 0):
            i = part["index"]
            value = values if i is None else (values[i] if i < len(values) else None)
            out["readings"].append({"sensor": part["id"], "kind": part["kind"], "side": part["side"], "topic": topic,
                                    "value": value, "unit": part["unit"], "range": part["range"]})
    for k in ("imu", "odom", "pose", "behaviour", "estop", "lifted", "led"):
        out[k] = state.get(k)
    return out


def commands(g: Graph, lang: str = "en") -> List[Dict[str, Any]]:
    r = the_robot(g)
    out = []
    for cmd in sorted(g.objects(r, ATL.accepts), key=str):
        req = _one(g, cmd, ATL.requestClass)
        params = []
        for shape in shapes().subjects(SH.targetClass, req) if req is not None else []:
            for prop in shapes().objects(shape, SH.property):
                path = _one(shapes(), prop, SH.path)
                params.append({
                    "key": str(_one(tbox(), path, ATL.jsonKey, str(path).rsplit("#", 1)[-1])), "label": label(path, lang),
                    "min": _one(shapes(), prop, SH.minInclusive), "max": _one(shapes(), prop, SH.maxInclusive),
                    "required": (_one(shapes(), prop, SH.minCount, 0) or 0) > 0,
                    "rule": str(_one(shapes(), prop, SH.message, "")),
                })
        out.append({"name": str(_one(g, cmd, SCHEMA.name)), "label": label(req, lang) if req is not None else "",
                    "route": _one(g, cmd, ATL.route), "needsConfirmation": bool(_one(g, cmd, ATL.needsConfirmation, True)),
                    "parameters": params})
    return out


# -- checking a request --------------------------------------------------------------------

def _concept(scheme: URIRef, notation: str) -> Optional[URIRef]:
    for c in tbox().subjects(SKOS.inScheme, scheme):
        if str(_one(tbox(), c, SKOS.notation)) == notation:
            return c
    return None


def check(g: Graph, name: str, params: Dict[str, Any]) -> List[str]:
    """[] when the robot accepts `name` with these parameters, else what is wrong, in words."""
    cmds = {c["name"]: c for c in commands(g)}
    if name not in cmds:
        return [f"{name!r} is not a command of this robot: one of {', '.join(sorted(cmds))}"]
    cmd = next(c for c in g.objects(the_robot(g), ATL.accepts) if str(_one(g, c, SCHEMA.name)) == name)
    req_class = _one(g, cmd, ATL.requestClass)
    req = Graph()
    node = BNode()
    req.add((node, RDF.type, req_class))
    key_to_path = {}
    for shape in shapes().subjects(SH.targetClass, req_class):
        for prop in shapes().objects(shape, SH.property):
            path = _one(shapes(), prop, SH.path)
            key_to_path[str(_one(tbox(), path, ATL.jsonKey, ""))] = path
    unknown = sorted(set(params) - set(key_to_path))
    if unknown:
        return [f"{name} takes no {', '.join(unknown)}: it takes {', '.join(sorted(key_to_path)) or 'nothing'}"]
    for key, value in params.items():
        path = key_to_path[key]
        if path == ATL.behaviour:
            req.add((node, path, _concept(ATL.Behaviours, str(value)) or Literal(str(value))))
        elif path == ATL.button:
            req.add((node, path, _concept(ATL.Buttons, str(value)) or Literal(str(value))))
        elif isinstance(value, bool):
            req.add((node, path, Literal(value, datatype=XSD.boolean)))
        elif isinstance(value, int):
            req.add((node, path, Literal(value, datatype=XSD.integer)))
        elif isinstance(value, float):
            req.add((node, path, Literal(value, datatype=XSD.decimal)))
        else:
            req.add((node, path, Literal(str(value))))
    ok, messages = conforms(req)
    return [] if ok else messages


# -- the connected robot's A-Box -------------------------------------------------------------

class Robots:
    """The A-Box of the robot this PC simulates: fetched from its gateway, kept in the twin folder."""

    def __init__(self, fetch, cache_dir):
        self.fetch, self.cache_dir = fetch, cache_dir           # fetch() -> Turtle text, or raises

    def abox(self) -> Graph:
        cache = Path(self.cache_dir()) / "robot.ttl"
        with _lock:
            try:
                text = self.fetch()
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(text, encoding="utf-8")
            except Exception:                                   # the body is off: the last one seen
                if not cache.exists():
                    raise NoRobot("no robot has been connected yet: start the simulation once") from None
                text = cache.read_text(encoding="utf-8")
        return abox_from(text)
