# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
The core every D-LAB-5 tool shares, from the tool template.

    identity       who this tool is (generated from the copier answers)
    version        installed vs published, and how this copy was installed
    server         the Flask blueprint: health, About, update, restart, stop
    skill_install  hand the packaged agent skill over, keep its copies in step
    mcp_bridge     (with MCP) call the web server from an MCP server, autostart it
    workspace      (with workspace folders) the user folder plus shipped samples

Core-owned: `copier update` rewrites these files. Change them in the template,
not here, or the next update will conflict with you.
"""
