#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Atelier-5
"""
world.py — writes the virtual table, the first starting world of Atelier-5 (Discover).

The world is generated, never edited by hand, so later starting worlds are
variations of the same generator. Standard library only.

    python3 -m atl.world --out mydocs/twin          # table.wbt, table.json, table_top.png

What it writes:

    table.wbt       a Webots R2025a world: a room, a white table with open edges,
                    a black line loop painted into the table top, a carton box and a
                    wooden block, one Thymio II "thymio_1" and a supervisor carrying
                    the overview camera ("atl_sup"). Both robots run <extern> controllers, which
                    connect from the atl-bot-* container over TCP.
    table.json      the same scene as data, for the bot (reset poses, the line) and the app
    table_top.png   the table top's texture, with the line in it: a Thymio's ground
                    sensors see colour, so the line is paint, not a raised strip
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import zlib
from pathlib import Path
from typing import Any, Dict, List, Tuple

ASSETS = "https://raw.githubusercontent.com/cyberbotics/webots/R2025a/projects"
THYMIO_PROTO = f"{ASSETS}/robots/mobsya/thymio/protos/Thymio2.proto"

# The scene, as the spec proposes it (defaults, adjustable). Lengths in metres.
SCENE: Dict[str, Any] = {
    "room": {"size": [4.0, 4.0], "wallHeight": 1.2},
    "table": {"size": [1.2, 0.8], "height": 0.75, "thickness": 0.03},
    "line": {"width": 0.04, "centre": [-0.30, 0.0], "size": [0.40, 0.56], "cornerRadius": 0.15},
    "objects": [
        {"name": "carton box", "size": [0.10, 0.16, 0.10], "position": [0.25, 0.0], "mass": 0.15,
         "colour": [0.76, 0.60, 0.42]},
        {"name": "wooden block", "size": [0.05, 0.10, 0.05], "position": [0.30, -0.25], "yaw": 0.6, "mass": 0.30,
         "colour": [0.60, 0.42, 0.25]},
    ],
    "robot": {"name": "thymio_1", "position": [0.0, 0.0], "yaw": 0.0},
    "camera": {"name": "overview", "height": 0.90, "width": 640, "pixels": 480, "fieldOfView": 1.25},
    "supervisor": "atl_sup",
    "texture": [2048, 1024],     # table-top texture in pixels: powers of two, so Webots does not rescale it
}

# Robot names stay short (8 characters at most). Webots (the snap) keeps its IPC
# path under the user's home, which leaves about 12 characters for a robot's
# name; a longer one is replaced by a hash, and a remote <extern> controller
# asking for the plain name is then refused ("not in the list of robots").
MAX_ROBOT_NAME = 8


# -- the table top's texture --------------------------------------------------

def _rounded_rect_distance(x: float, y: float, cx: float, cy: float, w: float, h: float, r: float) -> float:
    """Distance from (x, y) to the outline of a rounded rectangle (centre, size, corner radius)."""
    qx, qy = abs(x - cx) - (w / 2 - r), abs(y - cy) - (h / 2 - r)
    outside = math.hypot(max(qx, 0.0), max(qy, 0.0))
    inside = min(max(qx, qy), 0.0)
    return abs(outside + inside - r)


def _png(width: int, height: int, rows: List[bytes]) -> bytes:
    """A minimal RGB PNG (8 bits per channel)."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + row for row in rows)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def table_top_png(scene: Dict[str, Any]) -> bytes:
    """The white table top with the black line loop, seen from above (+x right, +y up)."""
    tw, th = scene["table"]["size"]
    W, H = scene["texture"]
    line = scene["line"]
    (cx, cy), (lw, lh), r, half = line["centre"], line["size"], line["cornerRadius"], line["width"] / 2
    white, black = bytes([245, 245, 242]), bytes([20, 20, 20])
    rows = []
    for j in range(H):
        y = th / 2 - (j + 0.5) * th / H         # image row 0 is the table's far edge (+y)
        row = bytearray()
        for i in range(W):
            x = -tw / 2 + (i + 0.5) * tw / W
            row += black if _rounded_rect_distance(x, y, cx, cy, lw, lh, r) <= half else white
        rows.append(bytes(row))
    return _png(W, H, rows)


def line_path(scene: Dict[str, Any], points_per_corner: int = 8) -> List[Tuple[float, float]]:
    """The line's centre as a closed polyline on the table (for the app's drawing and for tests)."""
    (cx, cy), (w, h), r = scene["line"]["centre"], scene["line"]["size"], scene["line"]["cornerRadius"]
    pts = []
    corners = [(cx + w / 2 - r, cy + h / 2 - r, 0), (cx - w / 2 + r, cy + h / 2 - r, 90),
               (cx - w / 2 + r, cy - h / 2 + r, 180), (cx + w / 2 - r, cy - h / 2 + r, 270)]
    for ox, oy, start in corners:
        for k in range(points_per_corner + 1):
            a = math.radians(start + 90 * k / points_per_corner)
            pts.append((round(ox + r * math.cos(a), 4), round(oy + r * math.sin(a), 4)))
    return pts


# -- the Webots world ---------------------------------------------------------

def _box_solid(name: str, size: List[float], centre: List[float], colour: List[float], mass: float = 0.0,
               yaw: float = 0.0, roughness: float = 0.8) -> str:
    sx, sy, sz = size
    physics = f"\n  physics Physics {{\n    density -1\n    mass {mass}\n  }}" if mass else ""
    return f'''Solid {{
  translation {centre[0]:.4f} {centre[1]:.4f} {centre[2]:.4f}
  rotation 0 0 1 {yaw:.4f}
  name "{name}"
  children [
    Shape {{
      appearance PBRAppearance {{
        baseColor {colour[0]} {colour[1]} {colour[2]}
        roughness {roughness}
        metalness 0
      }}
      geometry Box {{
        size {sx} {sy} {sz}
      }}
    }}
  ]
  boundingObject Box {{
    size {sx} {sy} {sz}
  }}{physics}
}}'''


def world_wbt(scene: Dict[str, Any]) -> str:
    for name in (scene["robot"]["name"], scene["supervisor"]):
        if len(name) > MAX_ROBOT_NAME:
            raise ValueError(f"robot name {name!r} is longer than {MAX_ROBOT_NAME} characters (see MAX_ROBOT_NAME)")
    room, table = scene["room"], scene["table"]
    (tw, th), top_z, t = table["size"], table["height"], table["thickness"]
    (rw, rd), wall_h = room["size"], room["wallHeight"]
    parts = [f'''#VRML_SIM R2025a utf8
# Atelier-5, starting world 0 "Discover": one Thymio II on the virtual table.
# GENERATED by atl/world.py: do not edit by hand, change the generator instead.

EXTERNPROTO "{THYMIO_PROTO}"

WorldInfo {{
  info [
    "Atelier-5 - Try it. Break it. Fix it. Show it."
  ]
  title "Atelier-5: the virtual table"
  basicTimeStep 16
}}
Viewpoint {{
  orientation -0.24 0.24 0.94 1.63
  position 0.05 -1.55 1.55
}}
Background {{
  skyColor [
    0.86 0.87 0.88
  ]
}}
DirectionalLight {{
  direction -0.35 0.45 -1
  intensity 2.2
  castShadows TRUE
}}
PointLight {{
  location 0 0 2.2
  intensity 1.2
  attenuation 0 0 1
}}''']
    # room: floor and four neutral walls
    parts.append(_box_solid("floor", [rw, rd, 0.02], [0, 0, -0.01], [0.72, 0.70, 0.66], roughness=1))
    for k, (cx, cy, sx, sy) in enumerate([(0, rd / 2, rw, 0.05), (0, -rd / 2, rw, 0.05),
                                          (rw / 2, 0, 0.05, rd), (-rw / 2, 0, 0.05, rd)]):
        parts.append(_box_solid(f"wall {k + 1}", [sx, sy, wall_h], [cx, cy, wall_h / 2], [0.90, 0.89, 0.86], roughness=1))
    # table: textured top (the line is in the texture), four legs; open edges
    parts.append(f'''Solid {{
  translation 0 0 {top_z - t / 2:.4f}
  name "table top"
  children [
    Shape {{
      appearance PBRAppearance {{
        baseColorMap ImageTexture {{
          url [
            "table_top.png"
          ]
          filtering 1
        }}
        roughness 0.6
        metalness 0
      }}
      geometry Box {{
        size {tw} {th} {t}
      }}
    }}
  ]
  boundingObject Box {{
    size {tw} {th} {t}
  }}
}}''')
    leg = 0.04
    for k, (sx, sy) in enumerate([(1, 1), (-1, 1), (1, -1), (-1, -1)]):
        parts.append(_box_solid(f"table leg {k + 1}", [leg, leg, top_z - t],
                                [sx * (tw / 2 - 0.06), sy * (th / 2 - 0.06), (top_z - t) / 2], [0.55, 0.55, 0.55]))
    # movable objects
    for o in scene["objects"]:
        sx, sy, sz = o["size"]
        parts.append(_box_solid(o["name"], o["size"], [o["position"][0], o["position"][1], top_z + sz / 2],
                                o["colour"], mass=o["mass"], yaw=o.get("yaw", 0.0)))
    # the robot
    rb = scene["robot"]
    parts.append(f'''Thymio2 {{
  translation {rb["position"][0]} {rb["position"][1]} {top_z + 0.0005:.4f}
  rotation 0 0 1 {rb["yaw"]}
  name "{rb["name"]}"
  controller "<extern>"
}}''')
    # the supervisor: overview camera above the table; lift and reset are its job
    cam = scene["camera"]
    # looking straight down with image-right along +x and image-up along +y, like the page's top view:
    # camera axes (forward x, left y, up z) = world (-z, -x, +y), i.e. 120 degrees about (-1, 1, 1)
    parts.append(f'''Robot {{
  translation 0 0 {top_z + cam["height"]:.4f}
  rotation -0.5774 0.5774 0.5774 2.0944
  name "{scene["supervisor"]}"
  controller "<extern>"
  supervisor TRUE
  children [
    Camera {{
      name "{cam["name"]}"
      fieldOfView {cam["fieldOfView"]}
      width {cam["width"]}
      height {cam["pixels"]}
    }}
  ]
}}''')
    return "\n".join(parts) + "\n"


def table_json(scene: Dict[str, Any]) -> Dict[str, Any]:
    """The scene as data: what the bot needs to reset it, and what the app draws."""
    top_z = scene["table"]["height"]
    return {
        "world": "discover/table", "version": 1,
        "table": scene["table"], "line": {**scene["line"], "path": line_path(scene)},
        "objects": [{**o, "z": top_z + o["size"][2] / 2} for o in scene["objects"]],
        "robot": {**scene["robot"], "z": top_z + 0.0005},
        "supervisor": scene["supervisor"], "camera": scene["camera"],
        "units": "metres; positions are on the table, x along its length, y across, origin at its centre",
    }


def write(out: Path, scene: Dict[str, Any] = SCENE) -> List[Path]:
    """Write table.wbt, table.json and table_top.png into out (created if needed)."""
    out.mkdir(parents=True, exist_ok=True)
    files = {"table.wbt": world_wbt(scene).encode(), "table.json": (json.dumps(table_json(scene), indent=2) + "\n").encode(),
             "table_top.png": table_top_png(scene)}
    written = []
    for name, data in files.items():
        (out / name).write_bytes(data)
        written.append(out / name)
    return written


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="atl-ide world", description="Write the virtual table (starting world 0, Discover).")
    ap.add_argument("--out", default="mydocs/twin", help="folder for table.wbt, table.json, table_top.png")
    args = ap.parse_args(argv)
    for p in write(Path(args.out)):
        print(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
