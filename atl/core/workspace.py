# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
workspace.py — two folders of JSON documents, one namespace.

    user    the person's own work. It follows the working directory, because
            they may keep several sets, and the repository ignores it.
    shared  samples that ship with the tool. They travel inside the package,
            so a pip install still opens on something that explains the tool.

A document is addressed by name plus folder. An unqualified read looks in the
user folder first, so a personal copy shadows a shared one of the same name, and
a save goes back to the folder the document came from, so editing a shared
sample updates it rather than quietly forking a copy.

Every document has a version: a short hash of its bytes. A writer that read
version X may only overwrite version X. Anything else means someone else, a
second tab or an agent, saved in between, and the writer has to choose.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from werkzeug.exceptions import BadRequest, NotFound

from . import identity

NAME_RE = re.compile(r"[A-Za-z0-9 _-]{1,64}$")
SUFFIX = ".json"

USER = "user"
SHARED = "shared"
FOLDER_TITLES = {USER: "Mine", SHARED: "Shared"}

PACKAGE_DIR = Path(__file__).resolve().parent.parent
FOLDERS: Dict[str, Path] = {
    USER: Path(identity.WORKSPACE_DIR or "workspace").resolve(),
    SHARED: (PACKAGE_DIR / (identity.SHARED_DIR or "shared")).resolve(),
}


class Conflict(Exception):
    """A save against a version that is no longer on disk."""

    def __init__(self, current_version: str, current: Any):
        super().__init__("changed on disk since it was read")
        self.current_version = current_version
        self.current = current


def configure(user_dir: Optional[str] = None, shared_dir: Optional[str] = None,
              create: bool = True) -> None:
    if user_dir:
        FOLDERS[USER] = Path(user_dir).expanduser().resolve()
    if shared_dir:
        FOLDERS[SHARED] = Path(shared_dir).expanduser().resolve()
    if create:
        for base in FOLDERS.values():
            base.mkdir(parents=True, exist_ok=True)


def folders() -> List[Dict[str, str]]:
    return [{"value": k, "label": FOLDER_TITLES.get(k, k), "path": str(p)}
            for k, p in FOLDERS.items()]


def base_dir(folder: str) -> Path:
    if folder not in FOLDERS:
        raise BadRequest(f"unknown folder '{folder}' — one of " + ", ".join(FOLDERS))
    return FOLDERS[folder]


def doc_path(name: str, folder: str = USER) -> Path:
    """Resolve a name to a file inside one folder, or refuse it."""
    base = base_dir(folder)
    if not NAME_RE.match(name or ""):
        raise BadRequest("a name may only contain letters, digits, space, - and _")
    path = (base / f"{name}{SUFFIX}").resolve()
    if path.parent != base:                # belt and braces after the name check
        raise BadRequest("that name escapes its folder")
    return path


def find(name: str, folder: Optional[str] = None) -> Tuple[Path, str]:
    """The file a name refers to, and the folder it was found in.

    With no folder given, the user's wins over shared. When it exists in
    neither, the answer is where it *would* go, so a caller can 404 with a path.
    """
    if folder:
        return doc_path(name, folder), folder
    for candidate in FOLDERS:
        path = doc_path(name, candidate)
        if path.exists():
            return path, candidate
    return doc_path(name, USER), USER


def version_of(path: Path) -> str:
    """Short content hash: content, not mtime, since two writes inside one
    timestamp tick share an mtime and a restored file can carry an older one."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except OSError:
        return ""


def listing() -> List[Dict[str, Any]]:
    out = []
    for folder, base in FOLDERS.items():
        if not base.is_dir():
            continue
        for path in sorted(base.glob(f"*{SUFFIX}")):
            if path.name.startswith(".") or not NAME_RE.match(path.stem):
                continue
            out.append({"name": path.stem, "folder": folder,
                        "mtime": path.stat().st_mtime, "version": version_of(path)})
    return out


def read(name: str, folder: Optional[str] = None) -> Dict[str, Any]:
    path, where = find(name, folder)
    if not path.exists():
        raise NotFound(f"no document called '{name}' — expected {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BadRequest(f"{path.name} is not readable JSON: {exc}")
    return {"name": name, "folder": where, "version": version_of(path), "data": data}


def write_atomic(path: Path, data: Any) -> None:
    """Write via a temp file and a rename, so a crash never truncates a document."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=SUFFIX)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def save(name: str, data: Any, folder: Optional[str] = None,
         base_version: Optional[str] = None) -> Dict[str, Any]:
    """Write a document. A save with no folder goes where it already lives, or
    to the user folder when it is new. A base_version that no longer matches
    raises Conflict; pass None to overwrite regardless."""
    path, where = find(name, folder)
    if base_version is not None and path.exists():
        current = version_of(path)
        if current != base_version:
            raise Conflict(current, read(name, where)["data"])
    write_atomic(path, data)
    return {"name": name, "folder": where, "version": version_of(path)}


def delete(name: str, folder: Optional[str] = None) -> Dict[str, Any]:
    path, where = find(name, folder)
    if not path.exists():
        raise NotFound(f"no document called '{name}'")
    path.unlink()
    return {"name": name, "folder": where, "deleted": True}
