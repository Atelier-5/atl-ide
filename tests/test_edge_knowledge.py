# SPDX-License-Identifier: GPL-3.0-or-later
"""The local A-Boxes are checked with the same shapes the cloud uses."""

from __future__ import annotations

import pytest
from rdflib import Literal, Namespace, RDF, URIRef

from atl.edge import knowledge as kn

SCHEMA = Namespace("https://schema.org/")


def test_a_change_the_shapes_refuse_is_not_written(tmp_path):
    kb = kn.KnowledgeBase(tmp_path)
    ok, _ = kn.validate(kb.load("shared"))
    assert ok
    shapes = list((kn.settings.ONTOLOGY / "shapes").glob("*.ttl"))
    if not shapes:
        pytest.skip("no shapes copied into edge/ontology yet")
    cls = next(o for s, p, o in kn._shapes() if str(p).endswith("targetClass"))
    thing = URIRef("https://example.test/id/thing/t-1")
    with pytest.raises(kn.Invalid):
        kb.change("shared", lambda g: g.add((thing, RDF.type, cls)))       # no name: refused
    assert not (tmp_path / "shared.ttl").exists()


def test_files_are_owner_only(tmp_path):
    kb = kn.KnowledgeBase(tmp_path / "abox")
    kb.change("shared", lambda g: None)
    assert oct((tmp_path / "abox").stat().st_mode & 0o777) == "0o700"
    assert oct((tmp_path / "abox" / "shared.ttl").stat().st_mode & 0o777) == "0o600"
