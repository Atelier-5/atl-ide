# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
skill_install.py — put the agent skill where an agent will find it.

The skill travels inside the package, so a pip or pipx install already has it;
what it does not have is a copy where the agent looks. This command bridges that.

Agents differ only in where they keep instructions: Claude Code reads
~/.claude/skills, Copilot reads .github/copilot-instructions.md, Cursor has its
own rules folder. core.agent knows all of them, so --for names the agent and
this command follows that convention rather than assuming every agent is Claude.

    <tool>-skill                     # where the packaged copy lives
    <tool>-skill --install           # copy it to ~/.claude/skills/<name>
    <tool>-skill --install --for vscode   # as .github/copilot-instructions.md
    <tool>-skill --install --for cursor   # as .cursor/rules/<name>.mdc
    <tool>-skill --install --force
    <tool>-skill --print             # write it to stdout
    <tool>-skill --check [FILE ...]  # have other copies drifted from this one?
    <tool>-skill --sync              # (checkout) rewrite the other copies from it

A checkout holds up to three real copies: the packaged one, which is the source,
.claude/skills/<name>/SKILL.md so an agent working in the repository picks it up
with no setup, and plugin/skills/<name>/SKILL.md for the Claude Code plugin.
They are files, not symlinks, because a symlink does not survive a clone on
Windows: it arrives as a text file holding the target path, and the skill quietly
becomes one line of nonsense. --check with no files checks every copy the
checkout has, and the core tests run it.
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path
from typing import List

from . import identity
from .version import repo_root

SKILL_NAME = identity.SKILL_NAME


def packaged() -> Path:
    """The SKILL.md that shipped with this install."""
    return Path(__file__).resolve().parent.parent / "skill" / "SKILL.md"


def destination(target_id: str = "claude-code") -> Path:
    """Where this agent keeps the instructions it reads.

    Claude Code has ~/.claude/skills; Copilot reads .github/copilot-instructions.md;
    Cursor has its own rules folder. core.agent knows all of them, so the
    convention lives there and this command follows it rather than assuming
    every agent is Claude.
    """
    if target_id != "claude-code":
        from . import agent
        found = agent.target(target_id)
        if found is None or not found.get("instructions"):
            raise KeyError(target_id)
        return Path(str(found["instructions"]["path"]))
    return Path.home() / ".claude" / "skills" / SKILL_NAME / "SKILL.md"


def checkout_copies() -> List[Path]:
    """Where the other copies live in a checkout. Empty for an installed copy."""
    root = repo_root()
    if root is None:
        return []
    copies = [root / ".claude" / "skills" / SKILL_NAME / "SKILL.md"]
    if (root / "plugin").is_dir():
        copies.append(root / "plugin" / "skills" / SKILL_NAME / "SKILL.md")
    return copies


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog=identity.SKILL_COMMAND,
                                 description=__doc__.splitlines()[1])
    ap.add_argument("--install", action="store_true",
                    help="copy the skill where the agent reads it")
    ap.add_argument("--for", dest="agent_id", default="claude-code",
                    metavar="AGENT",
                    help="which agent to install it for: claude-code (default), "
                         "vscode, cursor")
    ap.add_argument("--force", action="store_true",
                    help="overwrite a skill that is already installed")
    ap.add_argument("--print", dest="show", action="store_true",
                    help="write the skill to stdout")
    ap.add_argument("--check", metavar="FILE", nargs="*",
                    help="compare other copies against the packaged one "
                         "(default: every copy in this checkout)")
    ap.add_argument("--sync", action="store_true",
                    help="rewrite the checkout's copies from the packaged one")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)

    src = packaged()
    if not src.exists():
        print(f"  ! the packaged skill is missing: {src}", file=sys.stderr)
        return 1

    if args.check is not None:
        others = [Path(f) for f in args.check] or checkout_copies()
        if not others:
            print("  nothing to compare: not a checkout, and no files given")
            return 0
        bad = 0
        for other in others:
            if not other.exists():
                print(f"  ! no such file: {other}", file=sys.stderr)
                bad += 1
            elif filecmp.cmp(src, other, shallow=False):
                print(f"  in step: {other}")
            else:
                print(f"  ! {other} has drifted from {src}", file=sys.stderr)
                bad += 1
        if bad:
            print(f"  fix with:  {identity.SKILL_COMMAND} --sync", file=sys.stderr)
        return 1 if bad else 0

    if args.sync:
        copies = checkout_copies()
        if not copies:
            print("  ! --sync only makes sense in a checkout", file=sys.stderr)
            return 2
        for copy in copies:
            if copy.exists() and filecmp.cmp(src, copy, shallow=False):
                continue
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, copy)
            print(f"  wrote {copy}")
        return 0

    if args.show:
        sys.stdout.write(src.read_text(encoding="utf-8"))
        return 0

    if not args.install:
        print(src)
        return 0

    try:
        dest = destination(args.agent_id)
    except KeyError:
        # naming an agent we cannot place the skill for is a typo or a client
        # that keeps no instructions file; either way, say which ones work
        from . import agent as agents
        known = [t["id"] for t in agents.targets() if t.get("instructions")]
        print(f"  ! no skill location for '{args.agent_id}' — try: "
              + ", ".join(known), file=sys.stderr)
        return 2
    if dest.exists() and not args.force:
        same = filecmp.cmp(src, dest, shallow=False)
        print(f"  {dest} already exists"
              + (" and matches — nothing to do" if same
                 else " and differs — pass --force to replace it"))
        return 0 if same else 1
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    print(f"  installed to {dest}")
    print("  start a new session for an agent to pick it up")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
