#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Atelier-5
"""
engine.py — the engine of atl-ide, and its command line.

Standard library only, so the command line works without Flask, MCP or a
network. The web page and the MCP server call into this module; neither
re-implements what it does.

This is the template's sample domain: a *note* is a JSON object with a title,
a body and tags. Replace it with your own. Keep the shape: pure functions that
take and return plain data, errors as a list of messages, and a main() whose
subcommands the skill documents (tests/test_core.py checks that every command
SKILL.md names really exists).

    atl-ide validate note.json
    atl-ide summarise note.json
    python3 -m atl.engine summarise note.json   # the same, from a checkout
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

TITLE_MAX = 120


def validate(note: Any) -> List[str]:
    """Everything wrong with a note, as messages a person can act on. Empty is valid."""
    if not isinstance(note, dict):
        return ["a note must be a JSON object"]
    errors = []
    title = note.get("title")
    if not isinstance(title, str) or not title.strip():
        errors.append("title is required")
    elif len(title) > TITLE_MAX:
        errors.append(f"title is {len(title)} characters; keep it to {TITLE_MAX}")
    if not isinstance(note.get("body", ""), str):
        errors.append("body must be text")
    tags = note.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        errors.append("tags must be a list of strings")
    return errors


def summarise(note: Dict[str, Any]) -> Dict[str, Any]:
    """What is in a note, in numbers."""
    body = note.get("body", "") or ""
    return {
        "title": note.get("title", ""),
        "words": len(body.split()),
        "lines": body.count("\n") + 1 if body else 0,
        "tags": sorted(set(note.get("tags", []))),
    }


def _load(path: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"  ! cannot read {path}: {exc.strerror}")
    except ValueError as exc:
        raise SystemExit(f"  ! {path} is not JSON: {exc}")


def main(argv: List[str] | None = None) -> int:
    from .core.version import __version__

    ap = argparse.ArgumentParser(prog="atl-ide",
                                 description=__doc__.strip().splitlines()[0])
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="check a note and list what is wrong")
    p.add_argument("file")
    p = sub.add_parser("summarise", help="count what is in a note")
    p.add_argument("file")

    args = ap.parse_args(argv)
    note = _load(args.file)
    errors = validate(note)
    if args.command == "validate":
        for message in errors:
            print(f"  ! {message}", file=sys.stderr)
        if not errors:
            print("  valid")
        return 1 if errors else 0
    if errors:
        for message in errors:
            print(f"  ! {message}", file=sys.stderr)
        return 1
    json.dump(summarise(note), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
