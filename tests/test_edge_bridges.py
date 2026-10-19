# SPDX-License-Identifier: GPL-3.0-or-later
"""The bridge of this edge's kind (robot) imports, and says when its
backbone is not there instead of failing."""

from __future__ import annotations

import importlib


def test_the_bridge_imports_without_its_backbone():
    ros2 = importlib.import_module("atl.edge.bridges.ros2")
    assert set(ros2.available()) >= {"available"}
