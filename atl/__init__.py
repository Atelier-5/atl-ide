# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Atelier-5
"""atl-ide — atl-ide: the Atelier-5 robotics IDE, a Thymio II twin in Webots over ROS 2

    engine      the engine and its command line, standard library only
    app         the browser front end (Flask), on top of core.server
    mcp_server  MCP tools over stdio, talking to the same web server
    core/       shared with every D-LAB-5 tool; `copier update` maintains it

Keeping everything in a package rather than loose at the repository root is
what lets `pip install` carry the templates, static files, VERSION and the
agent skill along.
"""

from .core.identity import REPO_URL  # noqa: F401
from .core.version import __version__  # noqa: F401
