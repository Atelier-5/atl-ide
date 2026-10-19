# The edge layer

atl-ide is an **edge**: a robot with a ROS 2 backbone
that links to the Atelier-5 cloud, a site made from
[template-dlab5-cloud](https://github.com/d-lab-5/template-dlab5-cloud). It was made in
two steps: the ERP-LAB-5 python-tool-template (the base), then the
[template-dlab5-edge](https://github.com/d-lab-5/template-dlab5-edge) layer.
The patterns both follow are the blueprint `cloud-edge-platform.ttl` in
blueprinting-dlab5-net.

## Who owns what

| | Owner | `copier update` |
|---|---|---|
| `atl/core/` | the base | rewritten — leave it alone |
| `app.py`, `mcp_server.py`, `templates/`, `static/`, `pyproject.toml` | the tool | kept; `scripts/edge-wire.py` added the layer's lines once |
| `atl/edge/*.py`, `edge/static/`, `edge/bridges/`, `scripts/install*`, `scripts/publish-to-cloud.sh`, `tests/test_edge_*.py` | the edge layer | rewritten — change `settings.py` instead |
| `atl/edge/settings.py`, `edge/ontology/`, `__main__.py` | the tool | written once, then kept |

Update each separately:

```bash
copier update --trust                                   # the base
copier update --trust -a .copier-answers.edge.yml       # the edge layer
```

## What the layer does

| Module | |
|---|---|
| `edge/cloud.py` | links to clouds with the device flow (an admin of the workshop approves a code), one **connection** per cloud (sandbox, stage, prod); version header and 426; a bare 410 is a revoke, a 410 with an error code is one item gone; tokens renewed 30 days before expiry by a keeper that runs at start and twice a day, and a failed renewal shows on the page |
| `edge/knowledge.py`, `edge/sync.py` | one A-Box per group in `<data>/abox/`, checked with the cloud's SHACL shapes; three-way merge with every linked cloud; a fact with one value (settings.SINGLE_VALUED) is a conflict the person resolves |
| `edge/jobs.py` | background work with progress and Cancel: `JOBS.register(kind, run)` for the tool's own |
| `edge/firststart.py` | what a new edge fetches by itself: settings.FIRST_START steps, `fetch_models(set)` from the cloud (`/edge/v1/models`, SHA-256 checked), and the workshop's knowledge after linking |
| `edge/chat.py` | the chat panel: a local Claude Code with only this edge's MCP tools; changes are proposals the person confirms; only settings.CHAT_ALLOWED can be proposed |
| `edge/routes.py` | `/api/cloud…`, `/api/jobs…`, `/api/knowledge…`, `/api/chat…`; and the **guard**: this server answers to localhost only (DNS rebinding), refuses writes from other sites, and cannot be framed |
| `edge/mcp_tools.py` | `connections`, `jobs`, `cancel_job`, `knowledge`, `sync_knowledge`, `link`; `act()` makes a change or, in the chat panel, proposes it |
| `edge/bridges/ros2.py` | ROS 2 topics and services as tools: reading is free, publishing is a proposal. Source the ROS environment before starting the edge |

## Releasing to the cloud

```bash
scripts/publish-to-cloud.sh ../the-cloud-repository   # wheel + installers + release.json
```

Commit and push the cloud repository: its Settings → Edges then offers the
installer and package (15-minute links, SHA-256 checked). Raise the cloud's
`MIN_EDGE_VERSION` only after the new edge is out.

## Private stays private

The edge decides what leaves it. Keep biometrics, raw sensor data and
anything the workshop marks private out of the A-Boxes and out of
tool answers; the chat sees only what the tools answer.

## The drawings: How it works, Data model

Both are Archify drawings (`~/.claude/skills/archify`), served at `/how` and `/model` and linked from the rail.
Edit the source in `docs/`, then render it into `atl/static/`:

```bash
A=~/.claude/skills/archify/bin/archify.mjs
node $A finalize architecture docs/how-it-works.architecture.json atl/static/how.html --quality showcase --json
node $A finalize class docs/data-model.class.json atl/static/model.html --quality showcase --json
```
