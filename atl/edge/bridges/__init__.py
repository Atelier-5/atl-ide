# SPDX-License-Identifier: GPL-3.0-or-later
"""Bridges from this edge to the backbone it runs on: Node-RED for an IoT
edge, ROS 2 for a robot. Each imports without its backbone installed and says
so through available(), so the edge starts (and its tests run) anywhere."""
