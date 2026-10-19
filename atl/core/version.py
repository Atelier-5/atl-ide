# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
version.py — what is installed, what is published, and how this copy got here.

The installed version is the VERSION file beside the package, and nothing else:
pyproject reads the same file, so the two cannot disagree.

"Published" is that same file on the default branch, fetched raw rather than
through the GitHub API. The API allows 60 unauthenticated calls an hour per
address, which a few restarts could plausibly spend; raw.githubusercontent has
no such budget. Nothing about the user, the machine or their data is sent.
Releasing is therefore one edit, and the check cannot disagree with what shipped.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

from . import identity

PACKAGE_DIR = Path(__file__).resolve().parent.parent

LATEST_URL = (f"https://raw.githubusercontent.com/{identity.GITHUB_ORG}/"
              f"{identity.REPO_NAME}/{identity.DEFAULT_BRANCH}/"
              f"{identity.PACKAGE}/VERSION")
CHECK_EVERY = 6 * 60 * 60           # seconds; the answer changes rarely
UPDATE_CHECK = True                 # --no-update-check turns it off

_latest: Dict[str, object] = {"version": None, "at": 0.0, "error": None}


def read_version() -> str:
    try:
        return (PACKAGE_DIR / "VERSION").read_text(encoding="utf-8").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


__version__ = read_version()


def version_tuple(text: str) -> Tuple[int, ...]:
    """A comparable version, tolerant of a leading v and of junk after it."""
    parts = re.findall(r"\d+", (text or "").strip().lstrip("vV"))[:4]
    return tuple(int(p) for p in parts) or (0,)


def fetch_latest() -> Optional[str]:
    """The published version, or None when we could not reach it.

    Any failure is a None: no network, DNS down, a proxy in the way, GitHub
    having a bad day. None of those are worth an error in the user's face.
    """
    import urllib.request           # local: the CLI path never needs it
    try:
        req = urllib.request.Request(
            LATEST_URL, headers={"User-Agent": f"{identity.TOOL_NAME}/{__version__}"})
        with urllib.request.urlopen(req, timeout=4) as res:
            text = res.read(64).decode("utf-8", "replace").strip()
        return text if re.match(r"v?\d+(\.\d+)*$", text) else None
    except Exception:               # noqa: BLE001 - offline is not an error here
        return None


def latest_version(force: bool = False) -> Dict[str, object]:
    """Cached view of what is published, refreshed at most every CHECK_EVERY."""
    if not UPDATE_CHECK:
        return {"version": None, "checked": False, "disabled": True, "error": None}
    now = time.time()
    if force or (now - float(_latest["at"] or 0)) > CHECK_EVERY:
        found = fetch_latest()
        # keep the last good answer if this attempt failed, rather than
        # flapping between "0.3.0 available" and "offline" on a flaky link
        if found or not _latest["version"]:
            _latest["version"] = found
        _latest["at"] = now
        _latest["error"] = None if found else "could not reach github.com"
    return {"version": _latest["version"], "checked": True,
            "error": _latest["error"], "disabled": False}


def install_kind() -> str:
    """How this copy was installed, which decides how it can be updated.

    A checkout updates with git and has a working tree the user can see; an
    installed copy lives in site-packages, where pip is the only sane way in.
    """
    parts = PACKAGE_DIR.parts
    return "installed" if any(
        d in parts for d in ("site-packages", "dist-packages")) else "checkout"


def repo_root() -> Optional[Path]:
    """The checkout this package sits in, or None for an installed copy."""
    if install_kind() == "installed":
        return None
    root = PACKAGE_DIR.parent
    return root if (root / "pyproject.toml").is_file() else None
