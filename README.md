# atl-ide

**v0.1.0** · GPL-3.0 · [releases](https://github.com/Atelier-5/atl-ide/releases)

atl-ide: the Atelier-5 robotics IDE, a Thymio II twin in Webots over ROS 2.

<!-- Generated from the D-LAB-5 tool template. Rewrite the parts about notes;
     keep the install, update and agent sections accurate. scripts/release.py
     updates every v-pin in this file. -->

## Use it

```bash
./run.sh                 # http://127.0.0.1:8780
./run.sh --port 9000     # somewhere else
./run.sh --stop          # shut it down
```

The first run creates `.venv` and installs the requirements. Any other option
goes straight to the app, e.g. `./run.sh --no-update-check`.

The header has **About**, which shows the installed version, checks github.com
for a newer one and links to the repository. On a pip or pipx install it can
**update itself**: it runs pip against the latest tag, shows what pip said, and
restarts into the new version only if that worked. From a source checkout it
tells you to `git pull` instead. The check is one request for a text file. It
sends nothing about you, is cached for six hours, and is skipped silently when
there is no network. `--no-update-check` turns it off. **Restart** and **Stop**
are only accepted from this machine.

Notes live in two folders: `mydocs/` for your own, which git
ignores and which follows the working directory, and the samples that ship
inside the package. A save goes back to the folder the note came from.

## Installing without a clone

**A release tarball**: needs neither git nor pip.

```bash
curl -L https://github.com/Atelier-5/atl-ide/archive/refs/tags/v0.1.0.tar.gz | tar xz
cd atl-ide-0.1.0
./run.sh
```

**Or install it**, with no source tree to keep:

```bash
pipx install git+https://github.com/Atelier-5/atl-ide@v0.1.0
atl-ide-web                 # the page
atl-ide summarise note.json # the command line
atl-ide-mcp                 # the MCP server, for agents
atl-ide-skill --install     # the agent skill, into ~/.claude/skills
```

Every command has a `python3 -m` twin that needs nothing on PATH:

| command | the same thing as a module |
|---|---|
| `atl-ide` | `python3 -m atl.engine` |
| `atl-ide-web` | `python3 -m atl.app` |
| `atl-ide-mcp` | `python3 -m atl.mcp_server` |
| `atl-ide-skill` | `python3 -m atl.core.skill_install` |

## Updating an install

**From the page:** *About → Update and restart*.

**From the command line**, name the new tag. `--upgrade` alone will not move a
pinned tag:

```bash
pip install --upgrade git+https://github.com/Atelier-5/atl-ide@v0.1.0
pipx install --force git+https://github.com/Atelier-5/atl-ide@v0.1.0
```

If you copied the skill with `--install`, refresh it afterwards:
`atl-ide-skill --install --force`.

## For agents

**As a Claude Code plugin** you get the skill and the MCP server in one step:

```
/plugin marketplace add ERP-LAB-5/python-tool-template
/plugin install atl-ide@erp-lab-5
```

On first use the plugin installs the version it pins into its own venv under
`~/.local/share/dlab5-tools/atl-ide/` and runs the MCP server from there.
It needs `python3` on PATH.

**From a checkout**, `.mcp.json` registers the MCP server for this repository.

**For any other agent, press Agent** in the header. It writes the JSON for
Claude Code, VS Code (GitHub Copilot), Cursor or Claude Desktop with the real
paths already filled in — each client keeps the same server under a slightly
different key, in a different file — and either copies it or writes the file
for you, keeping any other servers already registered there. The panel also
shows whether an agent is currently working on this server.

MCP itself is the standard, so the server is written once and every client
speaks to it unchanged; only that small config file differs between them. What
no page can do is *start* one: a stdio server is spawned by its client, lives on
that client's pipes and dies with it, so there is nothing to start or stop from
the browser.

The MCP server starts the web server if it is not running, and both work on the
same files, so an agent's save shows up for the person at the browser.

[**The skill**](atl/skill/SKILL.md) ships inside the package.
`atl-ide-skill --install` copies it to `~/.claude/skills` for agents
that don't use the plugin, and `--install --for vscode` writes it as
`.github/copilot-instructions.md` instead (`--for cursor` for Cursor's rules
folder). A checkout has identical copies in
`.claude/skills/atl-ide/` and `plugin/skills/atl-ide/`. They are
real files rather than symlinks, because symlinks don't survive a clone on
Windows. `atl-ide-skill --check` confirms they are in step, and
`--sync` rewrites them from the packaged copy.

## Development

```bash
./test.sh                # the suite, with ROS 2's PYTHONPATH kept out of it
```

This repository was generated from
[ERP-LAB-5/python-tool-template](https://github.com/ERP-LAB-5/python-tool-template).
`atl/core/`, the launchers, `test.sh`, `tests/test_core.py`,
`scripts/release.py` and `plugin/bin/launch_mcp.py` belong to the template. Take its fixes with
`copier update` rather than editing them here. Everything else belongs to this tool.

Releasing:

```bash
python3 scripts/release.py 0.2.0 -F notes.txt --push
```

It bumps `VERSION` everywhere it appears, updates this README's pins, syncs the
skill copies, commits, tags, pushes, and creates the GitHub release.

## Licence

GPL-3.0-or-later. © 2026 Atelier-5 — *Twin. Experiment. Automate.*
See [LICENSE](LICENSE).
