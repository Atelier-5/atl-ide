# SPDX-License-Identifier: GPL-3.0-or-later
"""Three-way merge of A-Boxes: both sides' additions survive, a fact that may
have one value is a conflict until the person picks."""

from __future__ import annotations

from rdflib import Literal, URIRef

from atl.edge import sync

NAME = URIRef("https://schema.org/name")
KNOWS = URIRef("https://schema.org/knows")
A, B, C = (URIRef(f"https://example.test/id/thing/{x}") for x in "abc")


def test_additions_on_both_sides_and_a_removal_merge():
    base = {(A, KNOWS, B), (A, KNOWS, C)}
    mine = {(A, KNOWS, B), (A, KNOWS, C), (B, KNOWS, C)}          # added here
    theirs = {(A, KNOWS, B), (C, KNOWS, A)}                         # removed A knows C there, added C knows A
    merged, conflicts = sync.merge(base, mine, theirs)
    assert conflicts == []
    assert merged == {(A, KNOWS, B), (B, KNOWS, C), (C, KNOWS, A)}


def test_two_names_for_one_thing_are_a_conflict_until_resolved():
    base = set()
    mine, theirs = {(A, NAME, Literal("Printer"))}, {(A, NAME, Literal("3D printer"))}
    merged, conflicts = sync.merge(base, mine, theirs)
    assert len(conflicts) == 1 and conflicts[0]["mine"] == ["Printer"] and conflicts[0]["theirs"] == ["3D printer"]
    merged, conflicts = sync.merge(base, mine, theirs, {conflicts[0]["key"]: "theirs"})
    assert conflicts == [] and merged == theirs


def test_one_label_per_language_is_not_a_conflict():
    label = URIRef("http://www.w3.org/2004/02/skos/core#prefLabel")
    mine, theirs = {(A, label, Literal("Printer", lang="en"))}, {(A, label, Literal("Drucker", lang="de"))}
    merged, conflicts = sync.merge(set(), mine, theirs)
    assert conflicts == [] and len(merged) == 2
