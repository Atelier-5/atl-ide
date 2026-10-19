# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
ros2.py — the bridge to ROS 2, the backbone of a robot edge. Owned by the
edge layer.

ROS 2 owns the robot's motion and sensors; this edge observes it and asks it
to do things. Topics and services become MCP tools: reading is free,
publishing or calling a service is a proposal the person confirms, like every
change from the chat. rclpy is imported only when used, so the edge starts
and its tests run where ROS 2 is not installed (source the ROS environment
before starting the edge to enable it).

A robot edge is a CANDIDATE in the cloud-edge blueprint (no product yet):
expect this bridge to grow with the first one.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

_node: Dict[str, Any] = {}
_lock = threading.Lock()


def available() -> Dict[str, Any]:
    try:
        import rclpy  # noqa: F401
        return {"available": True}
    except ImportError:
        return {"available": False, "why": "rclpy is not importable: source the ROS 2 environment before starting the edge"}


def node():
    """One rclpy node for this edge, created on first use."""
    with _lock:
        if "node" not in _node:
            import rclpy
            if not rclpy.ok():
                rclpy.init()
            _node["node"] = rclpy.create_node("atl_edge")
        return _node["node"]


def topics() -> List[Dict[str, Any]]:
    """Every topic the ROS graph knows, with its message types."""
    return [{"name": n, "types": t} for n, t in node().get_topic_names_and_types()]


def services() -> List[Dict[str, Any]]:
    return [{"name": n, "types": t} for n, t in node().get_service_names_and_types()]


def _msg_class(type_name: str):
    from rosidl_runtime_py.utilities import get_message
    return get_message(type_name)


def publish(topic: str, type_name: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """One message on a topic, e.g. publish("/cmd_vel", "geometry_msgs/msg/Twist", {...})."""
    from rosidl_runtime_py.set_message import set_message_fields
    cls = _msg_class(type_name)
    msg = cls()
    set_message_fields(msg, data)
    pub = node().create_publisher(cls, topic, 10)
    pub.publish(msg)
    node().destroy_publisher(pub)
    return {"published": topic}


def add_tools(server: Any) -> None:
    """ROS 2 as MCP tools; publishing goes through act() (a proposal in the panel)."""
    from ..mcp_tools import act

    @server.tool()
    def ros2_status() -> dict:
        """Whether ROS 2 is reachable from this edge."""
        return available()

    @server.tool()
    def ros2_topics() -> list:
        """The robot's topics and their message types."""
        return topics()

    @server.tool()
    def ros2_publish(topic: str, type_name: str, data: dict) -> Any:
        """Publish one message on a topic (a proposal in the chat panel)."""
        return act(f"ROS 2: publish on {topic}", "POST", "/api/ros2/publish",
                   {"topic": topic, "type": type_name, "data": data})
