# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Atelier-5
"""Connects to the generated table's supervisor (extern, over TCP) and saves two pictures:
the overview camera's image, then lists the scene's top nodes.

    webots-controller --protocol=tcp --ip-address=127.0.0.1 --port=1240 --robot-name=atl_sup \
        world_check_controller.py <out-folder>
"""
import sys

from controller import Supervisor

out = sys.argv[1]
sup = Supervisor()
step = int(sup.getBasicTimeStep())
cam = sup.getDevice("overview")
cam.enable(step)
for _ in range(int(1500 / step)):          # 1.5 s: let objects settle and textures load
    if sup.step(step) == -1:
        sys.exit(0)
cam.saveImage(f"{out}/check_overview.png", 95)
sup.step(step)
root = sup.getRoot().getField("children")
names = []
for i in range(root.getCount()):
    n = root.getMFNode(i)
    f = n.getField("name")
    names.append(f"{n.getTypeName()}:{f.getSFString()}" if f else n.getTypeName())
print("CHECK nodes", names, flush=True)
thymio = next(root.getMFNode(i) for i in range(root.getCount())
              if root.getMFNode(i).getField("name") and root.getMFNode(i).getField("name").getSFString() == "thymio_1")
print("CHECK thymio at", [round(v, 4) for v in thymio.getPosition()], flush=True)
for _ in range(10):
    sup.step(step)
