#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
release.py — publish a version of atl-ide in one step.

    python3 scripts/release.py 0.2.0 --dry-run          # show what would change
    python3 scripts/release.py 0.2.0 -F notes.txt        # commit + tag, body from a file
    python3 scripts/release.py 0.2.0 -F notes.txt --push # ... and publish it

A release is the same edit in several places, and a hand-made one tends to miss
one of them: a README that still says the old tag, a plugin that pins the
previous version, a GitHub release nobody created. This makes them one step:

  1. refuse unless the tree is clean, on main, and ./test.sh passes
  2. write the version into atl/VERSION, plugin/.claude-plugin/plugin.json
     and plugin/bin/VERSION (the MCP launcher's pin)
  3. rewrite the README's install pins (**vX**, @vX, the tarball URL and folder)
     and refuse if an old pin is left
  4. bring the skill's copies in step with the packaged one
  5. commit "Release X.Y.Z" and tag vX.Y.Z
  6. with --push: push both, then `gh release create` so releases never lag tags

Standard library only, so it runs without the venv.
Core-owned (D-LAB-5 tool template): `copier update` rewrites this file.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = "atl"
REPO = "atl-ide"
BRANCH = "main"
SEMVER = re.compile(r"\d+\.\d+\.\d+")


def run(*cmd: str, check: bool = True, capture: bool = True) -> str:
    done = subprocess.run(cmd, cwd=ROOT, text=True,
                          capture_output=capture, check=False)
    if check and done.returncode != 0:
        detail = (done.stderr or done.stdout or "").strip() if capture else ""
        raise SystemExit(f"  ! {' '.join(cmd)} failed ({done.returncode})"
                         + (f"\n{detail}" if detail else ""))
    return (done.stdout or "").strip() if capture else ""


def say(text: str) -> None:
    print(text, flush=True)


def pins(text: str, new: str) -> str:
    """Every install pin in the README, pointed at the new version."""
    v = r"\d+\.\d+\.\d+"
    text = re.sub(rf"\*\*v{v}\*\*", f"**v{new}**", text)
    text = re.sub(rf"@v{v}\b", f"@v{new}", text)
    text = re.sub(rf"/refs/tags/v{v}\.tar\.gz", f"/refs/tags/v{new}.tar.gz", text)
    text = re.sub(rf"\b{re.escape(REPO)}-{v}\b", f"{REPO}-{new}", text)
    return text


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("version", help="the new version, X.Y.Z")
    ap.add_argument("-F", "--message-file",
                    help="commit body: what changed and why, and how it was verified")
    ap.add_argument("--push", action="store_true",
                    help="push the commit and tag, then create the GitHub release")
    ap.add_argument("--dry-run", action="store_true", help="change nothing")
    ap.add_argument("--skip-tests", action="store_true",
                    help="for a docs-only release; say so in the notes")
    ap.add_argument("--allow-branch", action="store_true",
                    help=f"release from a branch other than {BRANCH}")
    args = ap.parse_args()

    new = args.version.lstrip("vV")
    if not SEMVER.fullmatch(new):
        raise SystemExit(f"  ! {args.version} is not X.Y.Z")

    version_file = ROOT / PACKAGE / "VERSION"
    old = version_file.read_text(encoding="utf-8").strip()
    if tuple(map(int, new.split("."))) <= tuple(map(int, old.split("."))):
        raise SystemExit(f"  ! {new} is not newer than {old}")

    # ---------------------------------------------------------- preflight --
    # A dry run lists what would stop the release and carries on, so it can be
    # read before the tree is ready; a real run stops at the first problem.
    problems = []
    if run("git", "status", "--porcelain"):
        problems.append("the working tree is not clean; commit or stash first")
    branch = run("git", "rev-parse", "--abbrev-ref", "HEAD")
    if branch != BRANCH and not args.allow_branch:
        problems.append(f"on {branch}, not {BRANCH} (--allow-branch to insist)")
    if run("git", "tag", "--list", f"v{new}"):
        problems.append(f"tag v{new} already exists")
    if args.push and not shutil.which("gh"):
        problems.append("--push needs the GitHub CLI (gh) to create the release")
    for problem in problems:
        say(f"  {'would refuse' if args.dry_run else '!'}: {problem}")
    if problems and not args.dry_run:
        raise SystemExit(1)
    if not args.skip_tests and not args.dry_run:
        say("  running ./test.sh ...")
        run("bash", "./test.sh", "-q", capture=False)

    # ------------------------------------------------------------- edits --
    readme = ROOT / "README.md"
    edits = {version_file: f"{new}\n"}
    manifest = ROOT / "plugin" / ".claude-plugin" / "plugin.json"
    if manifest.exists():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["version"] = new
        edits[manifest] = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    pinned = ROOT / "plugin" / "bin" / "VERSION"
    if pinned.exists():
        edits[pinned] = f"{new}\n"
    if readme.exists():
        text = readme.read_text(encoding="utf-8")
        edits[readme] = pins(text, new)
        # a changelog line may name the old version on purpose, so this warns
        # rather than refuses: read the lines and decide
        for number, line in enumerate(edits[readme].splitlines(), 1):
            if re.search(rf"\bv?{re.escape(old)}\b", line):
                say(f"  note: README.md:{number} still says {old}: {line.strip()[:90]}")

    for path, content in edits.items():
        rel = path.relative_to(ROOT)
        if path.read_text(encoding="utf-8") == content:
            say(f"  unchanged  {rel}")
            continue
        say(f"  {'would write' if args.dry_run else 'write'}  {rel}")
        if not args.dry_run:
            path.write_text(content, encoding="utf-8")

    if args.dry_run:
        say(f"  dry run: {old} -> {new}, nothing written")
        return 0

    # skill_install is standard library only, so the system python can run it
    sync = [sys.executable, "-m", f"{PACKAGE}.core.skill_install", "--sync"]
    subprocess.run(sync, cwd=ROOT, check=True, env={**os.environ, "PYTHONPATH": str(ROOT)})

    # ------------------------------------------------------ commit and tag --
    run("git", "add", "-A")
    msg = [f"Release {new}"]
    if args.message_file:
        msg += ["", Path(args.message_file).read_text(encoding="utf-8").strip()]
    run("git", "commit", "-q", "-m", "\n".join(msg))
    run("git", "tag", "-a", f"v{new}", "-m", f"Release {new}")
    say(f"  committed and tagged v{new}")

    if not args.push:
        say(f"  publish with:  git push origin {branch} v{new} && "
            f"gh release create v{new} --generate-notes")
        return 0

    run("git", "push", "origin", branch, f"v{new}", capture=False)
    notes = ["--notes-file", args.message_file] if args.message_file else ["--generate-notes"]
    run("gh", "release", "create", f"v{new}", "--title", f"v{new}", *notes, capture=False)
    say(f"  released v{new}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
