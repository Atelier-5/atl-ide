# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
firststart.py — what a new edge fetches by itself. Owned by the edge layer.

An edge installed on another computer starts empty. At start, and again when
it is linked, a "first start" job runs every step that is still needed:

    the tool's steps    settings.FIRST_START: models, files, whatever the
                        product needs ((name, needed(), run(progress, cancelled)))
    {tenant} knowledge  after linking: every space's A-Box, by the ordinary
                        sync (once per connection; then Sync keeps it)

Each step is skipped when done, and a failed step does not stop the others:
the next start tries it again.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import cloud, settings
from . import knowledge as kn
from . import sync
from .jobs import Stopped

CHUNK = 1 << 20
Progress = Optional[Callable[[str, float], None]]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, to: Path, what: str, progress: Progress, cancelled: Callable[[], bool],
             span: Tuple[float, float] = (0.0, 1.0)) -> None:
    """A file, in chunks, with progress; Cancel works between chunks."""
    req = urllib.request.Request(url, headers={"User-Agent": settings.TOOL})
    with urllib.request.urlopen(req, timeout=60) as resp, open(to, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        for chunk in iter(lambda: resp.read(CHUNK), b""):
            if cancelled():
                raise Stopped()
            out.write(chunk)
            done += len(chunk)
            if progress and total:
                progress(f"{what}: {done >> 20} of {total >> 20} MB", span[0] + (span[1] - span[0]) * done / total)


def fetch_models(set_name: str, dest: Path, progress: Progress = None,
                 cancelled: Callable[[], bool] = lambda: False, profile: Optional[str] = None) -> Dict[str, Any]:
    """A set of files the cloud offers to linked edges (/edge/v1/models), each
    checked against the SHA-256 the cloud published, then moved into `dest`."""
    files = cloud.call("models", {"set": set_name}, profile).get("files") or []
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"{settings.TOOL}-models-") as tmp:
        for n, f in enumerate(files):
            name = str(f["name"])
            if "/" in name or "\\" in name or name.startswith("."):
                raise RuntimeError(f"refusing a model file name: {name!r}")
            out = Path(tmp) / name
            download(f["url"], out, f"{set_name} ({name})", progress, cancelled,
                     span=(n / max(1, len(files)), (n + 1) / max(1, len(files))))
            if sha256(out) != f["sha256"]:
                raise RuntimeError(f"{name} does not match the SHA-256 {settings.CLOUD_NAME} published")
            shutil.move(str(out), dest / name)
    return {set_name: len(files)}


def _knowledge_needed() -> List[str]:
    return [n for n in cloud.linked_profiles() if not cloud.load_state(n).get("first_start_done")]


def steps() -> List[Tuple[str, Callable[[], bool], Callable[..., Dict[str, Any]]]]:
    out = list(settings.FIRST_START)
    out.append((f"{settings.TENANT_NOUN} knowledge", lambda: bool(_knowledge_needed()), _pull_knowledge))
    return out


def _pull_knowledge(progress: Progress = None, cancelled: Callable[[], bool] = lambda: False) -> Dict[str, Any]:
    kb = kn.KnowledgeBase()
    out = {}
    for name in _knowledge_needed():
        if cancelled():
            raise Stopped()
        out[name] = sync.sync_all(kb, name)
        cloud.update_state({"first_start_done": True}, name)
    return {"knowledge": out}


def needed() -> bool:
    return any(need() for _, need, _ in steps())


def run(spec: Dict[str, Any], progress: Callable[[str, float], None], cancelled: Callable[[], bool]) -> Dict[str, Any]:
    """The first-start job (jobs.JOBS kind "first-start")."""
    out: Dict[str, Any] = {"done": [], "failed": {}}
    for what, need, fn in steps():
        if cancelled():
            raise Stopped()
        if not need():
            continue
        progress(what, 0.0)
        try:
            out.update(fn(progress, cancelled))
            out["done"].append(what)
        except Stopped:
            raise
        except Exception as exc:             # one missing part must not stop the rest
            out["failed"][what] = str(exc)[:300]
    return out
