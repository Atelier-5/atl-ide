# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
knowledge.py — this edge's A-Boxes: what its tenant knows, one Turtle file
per space (<data>/abox/<space slug>.ttl), checked with the same SHACL shapes
the cloud uses (settings.ONTOLOGY, a copy of the cloud's packages/ontology).
Owned by the edge layer.

A product builds its own vocabulary on this (minting ids, labels …) in its
own module; this one only stores, validates and hands graphs to sync.py.
Real A-Boxes are personal data: they stay in the data folder (0700/0600),
never in the repository.
"""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

from rdflib import Graph, Namespace

from . import settings

SHARED = "shared"                 # the slug of a tenant's shared space
GRAPH_NAME = re.compile(r"[a-z][a-z0-9-]{0,39}")
SH = Namespace("http://www.w3.org/ns/shacl#")


class Invalid(Exception):
    """The shapes refused a change; nothing was written."""

    def __init__(self, messages: List[str]):
        super().__init__("; ".join(messages) or "invalid")
        self.messages = messages


def data_dir() -> Path:
    """Where this edge keeps its own files: $<ENV>_EDGE_DATA, else the tool's
    user folder when the base template made one, else ~/.local/share/<tool>."""
    env = os.environ.get(f"{settings.ENV}_EDGE_DATA")
    if env:
        return Path(env).expanduser()
    try:
        from ..core import workspace as ws
        return Path(ws.FOLDERS[ws.USER])
    except (ImportError, AttributeError, KeyError):
        return Path.home() / ".local" / "share" / settings.TOOL


def _ttl(folder: str, pick: Callable[[str], bool]) -> Graph:
    g = Graph()
    d = Path(settings.ONTOLOGY) / folder
    for p in sorted(d.glob("*.ttl")) if d.is_dir() else []:
        if pick(p.name):
            g.parse(p, format="turtle")
    return g


_cache: dict = {}


def _shapes() -> Graph:
    if "shapes" not in _cache:
        _cache["shapes"] = _ttl("shapes", lambda n: True)
    return _cache["shapes"]


def _concepts() -> Graph:
    """The concept schemes travel with the data, so a type can be checked
    against its scheme (as the cloud does)."""
    if "concepts" not in _cache:
        _cache["concepts"] = _ttl("tbox", lambda n: "concept" in n)
    return _cache["concepts"]


def validate(g: Graph) -> Tuple[bool, List[str]]:
    """An A-Box against the shapes. No shapes (an ontology not copied yet):
    everything passes, and the cloud is still the one that decides."""
    shapes = _shapes()
    if len(shapes) == 0:
        return True, []
    from pyshacl import validate as shacl
    data = Graph()
    for t in g:
        data.add(t)
    for t in _concepts():
        data.add(t)
    ok, report, _ = shacl(data, shacl_graph=shapes, inference="none")
    if ok:
        return True, []
    return False, sorted({str(m) for m in report.objects(None, SH.resultMessage)})


class KnowledgeBase:
    """The A-Box graphs of this edge. One writer at a time."""

    def __init__(self, directory: Optional[Path] = None):
        self.dir = Path(directory) if directory else data_dir() / "abox"
        self._lock = threading.Lock()

    def _path(self, name: str) -> Path:
        if not GRAPH_NAME.fullmatch(name or ""):
            raise ValueError("a graph name is lowercase letters, digits and -")
        return self.dir / f"{name}.ttl"

    def graphs(self) -> List[str]:
        """The local A-Boxes, the shared space's first."""
        names = sorted(p.stem for p in self.dir.glob("*.ttl")) if self.dir.is_dir() else []
        return sorted(names or [SHARED], key=lambda n: (n != SHARED, n))

    def load(self, name: str) -> Graph:
        g = Graph()
        path = self._path(name)
        if path.exists():
            g.parse(path, format="turtle")
        return g

    def _save(self, name: str, g: Graph) -> None:
        self.dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.dir, 0o700)
        path = self._path(name)
        tmp = path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(g.serialize(format="turtle").encode())
        os.replace(tmp, path)

    def change(self, name: str, apply: Callable[[Graph], Any]) -> Any:
        """Load, apply, validate, save; or refuse with the shapes' messages."""
        with self._lock:
            g = self.load(name)
            result = apply(g)
            ok, messages = validate(g)
            if not ok:
                raise Invalid(messages)
            self._save(name, g)
            return result
