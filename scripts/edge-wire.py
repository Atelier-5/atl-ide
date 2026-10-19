#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
edge-wire.py — wire the edge layer into this tool's own files. Run by
Copier after `copier copy|update` of template-dlab5-edge; safe to run again.

The base template owns pyproject.toml, app.py, mcp_server.py and the page, so
the layer cannot ship them. This adds, once each, what the layer needs, and
SAYS what it could not do instead of guessing:

    pyproject.toml     rdflib and pyshacl; the edge packages and their files
    requirements.txt   the same two, for ./test.sh and ./run.sh
    app.py             edge_routes.install(app); start_background() in main()
    mcp_server.py      add_edge_tools(server)
    the page           the Connections and Chat panels
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PKG = "atl"
ROOT = Path(__file__).resolve().parents[1]
todo: list[str] = []


def patch(path: Path, marker: str, edit) -> None:
    if not path.exists():
        todo.append(f"{path.relative_to(ROOT)} is missing: wire the edge layer in by hand (docs/edge.md)")
        return
    text = path.read_text()
    if marker in text:
        return
    new = edit(text)
    if new is None or new == text:
        todo.append(f"{path.relative_to(ROOT)}: could not find where to add {marker!r} (docs/edge.md)")
        return
    path.write_text(new)
    print(f"  wired {path.relative_to(ROOT)}")


def pyproject(text: str):
    out = text
    for dep in ('"rdflib>=7.0"', '"pyshacl>=0.26"'):
        if dep.split(">")[0] not in out:
            out, n = re.subn(r"(dependencies = \[)([^\]]*)\]", lambda m: f"{m.group(1)}{m.group(2)}, {dep}]", out, count=1)
            if not n:
                return None
    out, n = re.subn(r'(packages = \[)([^\]]*)\]',
                     lambda m: f'{m.group(1)}{m.group(2)}, "{PKG}.edge", "{PKG}.edge.bridges"]', out, count=1)
    if not n:
        return None
    data = f'"{PKG}.edge" = ["static/*", "ontology/*/*.ttl", "ontology/*.ttl"]  # edge layer\n'
    out, n = re.subn(r"(\[tool\.setuptools\.package-data\]\n)", lambda m: m.group(1) + data, out, count=1)
    return out if n else None


def requirements(text: str):
    """./test.sh and ./run.sh install from here, not from pyproject.toml."""
    out = text if text.endswith("\n") or not text else text + "\n"
    return out + "# edge layer\nrdflib>=7.0\npyshacl>=0.26\n"


def app_py(text: str):
    a = "app = server.create_app(__name__)\n"
    if a not in text or "    return server.serve(" not in text:
        return None
    text = text.replace(a, a + "\nfrom .edge import routes as edge_routes  # edge layer\nedge_routes.install(app)\n", 1)
    return text.replace("    return server.serve(", "    edge_routes.start_background()  # edge layer\n    return server.serve(", 1)


def mcp_py(text: str):
    a = "web.add_core_tools(server)\n"
    if a not in text:
        return None
    return text.replace(a, a + "\nfrom .edge.mcp_tools import add_edge_tools  # edge layer\nadd_edge_tools(server)\n", 1)


def page(text: str):
    if "</main>" not in text:
        return None
    panels = ('  <section id="edge-connections" class="panel"></section>  <!-- edge layer -->\n'
              '  <section id="edge-chat" class="panel"></section>\n')
    assets = ('<link rel="stylesheet" href="/edge-static/edge.css">\n'
              '<script src="/edge-static/edge.js" defer></script>\n')
    text = text.replace("</main>", panels + "</main>", 1)
    return text.replace("</body>", assets + "</body>", 1) if "</body>" in text else text + assets


patch(ROOT / "pyproject.toml", f'"{PKG}.edge"', pyproject)
patch(ROOT / "requirements.txt", "pyshacl", requirements)
patch(ROOT / PKG / "app.py", "edge_routes.install(app)", app_py)
patch(ROOT / PKG / "mcp_server.py", "add_edge_tools(server)", mcp_py)
patch(ROOT / PKG / "templates" / "index.html", "edge-connections", page)

if todo:
    print("\n  edge-wire: by hand, please —")
    for t in todo:
        print(f"    - {t}")
sys.exit(0)
