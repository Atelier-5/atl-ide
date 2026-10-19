<p align="center"><img src="docs/ui-table-live.png" alt="atl-ide: the Table screen, live: the camera above the table, the Thymio's sensors, the six behaviours" width="760"></p>

# atl-ide: the Atelier-5 robotics IDE

🇬🇧 A Thymio II on a virtual table: watch what it senses, drive it, start its built-in behaviours. Try it. Break it. Fix it. Show it.
🇫🇷 Un Thymio II sur une table virtuelle : observe ce qu'il perçoit, conduis-le, lance ses comportements. Essayer. Démonter. Réparer. Montrer.
🇩🇪 Ein Thymio II auf einem virtuellen Tisch: sieh, was er wahrnimmt, fahre ihn, starte seine Verhalten. Probieren. Zerlegen. Reparieren. Zeigen.

**v0.1 · Discover**: one Thymio II on a white table (1.2 × 0.8 m, open edges) with a black line, a carton box and a wooden block.

## Run it

It needs **Webots R2025a** (`sudo snap install webots`), **Docker** and the robot's body, the image of
[atl-bot-thymio](https://github.com/Atelier-5/atl-bot-thymio) (ROS 2 Kilted, so it runs on any host):

```bash
(cd ../atl-bot-thymio && docker build -f docker/Dockerfile -t atl-bot-thymio:kilted .)
./run.sh                 # http://127.0.0.1:8780 → Start the simulation
./test.sh                # the tests: no Webots, no Docker
```

**Start the simulation** writes the table (`atl/world.py` → `mydocs/twin/`), opens it in Webots, starts the
robot's body in its container and waits until the sensors report. Closing the Webots window stops it all.

## How it works

The page talks only to this app; the app talks HTTP to the body's **gateway** on 127.0.0.1:8781; the gateway
speaks ROS 2 to the Webots drivers. The drawing is in the app, under **How it works** (`/how`), and the robot's
ontology under **Data model** (`/model`): both are Archify drawings made from `docs/`.

| Screen | |
|---|---|
| **Table** | the camera above the table; the Thymio from above with its 7 + 2 sensors and LED; readings and rolling plots; the six behaviours; drive, the robot's buttons, clap, lift; E-stop and reset |
| **Scene**, **Program** | the table's world; Blockly for the robot and the scene comes later |
| **Link**, **Chat** | the Atelier-5 cloud (later) and an agent, whose actions a facilitator confirms |

Sensor names stay hidden until a facilitator shows them: the group discovers first, names come after.
In English, French and German (`atl/i18n/`), from the D-LAB-5 tool and edge templates, as
[digitalhome-twin-edge-WormBed-5](https://github.com/DigitalHome-cloud/digitalhome-twin-edge-WormBed-5).

## License
GPL-3.0-or-later. The name "Atelier-5" and its logos are reserved for modified versions (GPLv3 §7(e),
see [atl-hub/TRADEMARKS.md](https://github.com/Atelier-5/atl-hub/blob/main/TRADEMARKS.md)).
