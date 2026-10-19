# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Atelier-5
"""The world generator: the virtual table (starting world 0, Discover)."""

import copy
import json
import struct

import pytest

from atl import world


def test_writes_the_three_files(tmp_path):
    names = sorted(p.name for p in world.write(tmp_path))
    assert names == ["table.json", "table.wbt", "table_top.png"]


def test_world_is_r2025a_with_both_extern_robots(tmp_path):
    world.write(tmp_path)
    wbt = (tmp_path / "table.wbt").read_text()
    assert wbt.startswith("#VRML_SIM R2025a utf8")
    assert 'EXTERNPROTO "https://raw.githubusercontent.com/cyberbotics/webots/R2025a/' in wbt
    assert wbt.count('controller "<extern>"') == 2
    assert 'name "thymio_1"' in wbt and 'name "atl_sup"' in wbt and "supervisor TRUE" in wbt
    assert "webots://" not in wbt          # the snap has no local asset library


def test_texture_is_a_power_of_two_png(tmp_path):
    world.write(tmp_path)
    head = (tmp_path / "table_top.png").read_bytes()[:24]
    assert head[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", head[16:24])
    assert (w & (w - 1), h & (h - 1)) == (0, 0)


def test_robot_names_fit_webots_snap_ipc_limit():
    scene = copy.deepcopy(world.SCENE)
    scene["supervisor"] = "atl_supervisor"       # 14 characters: Webots would hash it
    with pytest.raises(ValueError, match="longer than 8"):
        world.world_wbt(scene)


def test_line_and_objects_lie_on_the_table():
    tw, th = world.SCENE["table"]["size"]
    half_line = world.SCENE["line"]["width"] / 2
    for x, y in world.line_path(world.SCENE):
        assert abs(x) + half_line < tw / 2 and abs(y) + half_line < th / 2
    for o in world.SCENE["objects"]:
        x, y = o["position"]
        assert abs(x) < tw / 2 and abs(y) < th / 2


def test_line_is_painted_where_the_path_says():
    scene = world.SCENE
    tw, th = scene["table"]["size"]
    W, H = scene["texture"]
    x, y = world.line_path(scene)[0]                  # a point on the line's centre
    i, j = int((x + tw / 2) / tw * W), int((th / 2 - y) / th * H)
    assert world._rounded_rect_distance(x, y, *scene["line"]["centre"], *scene["line"]["size"],
                                        scene["line"]["cornerRadius"]) < 1e-3
    assert 0 <= i < W and 0 <= j < H


def test_table_json_carries_reset_poses(tmp_path):
    world.write(tmp_path)
    data = json.loads((tmp_path / "table.json").read_text())
    assert data["robot"]["name"] == "thymio_1" and data["robot"]["z"] == pytest.approx(0.7505)
    assert {o["name"] for o in data["objects"]} == {"carton box", "wooden block"}
    assert len(data["line"]["path"]) > 20 and data["supervisor"] == "atl_sup"


def test_generator_is_deterministic(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    world.write(a)
    world.write(b)
    for name in ("table.wbt", "table.json", "table_top.png"):
        assert (a / name).read_bytes() == (b / name).read_bytes()
