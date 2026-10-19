#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
#
# Put this edge's package and installer where the Atelier-5 cloud offers them for
# download (Settings → Edges → Install an edge on another PC).
#
#     scripts/publish-to-cloud.sh path/to/the-cloud-repository
#
# Builds the wheel, fills in the installers (scripts/install_edge.py.in
# for any OS with Python, scripts/install-edge.sh.in for Linux and macOS) with
# the version and the wheel's SHA-256, and writes them plus release.json into
# <cloud>/backend/edge-release/. Committing and pushing the cloud repo deploys
# them into the Atelier-5 cloud's private release bucket; signed-in admins get
# short-lived links. The cloud's minimum edge version is separate
# (backend edge-shared/http.ts MIN_EDGE_VERSION): raise it after releasing.
set -euo pipefail
cd "$(dirname "$0")/.."
unset PYTHONPATH

CLOUD="${1:?usage: scripts/publish-to-cloud.sh path/to/the-cloud-repository}"
OUT="$CLOUD/backend/edge-release"
[ -d "$CLOUD/backend" ] || { echo "no cloud repository at $CLOUD" >&2; exit 1; }
VERSION="$(tr -d '[:space:]' < atl/VERSION)"

rm -rf build ./*.egg-info              # a stale build/ would put old files into the wheel
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
.venv/bin/python -m pip wheel --quiet --no-deps --wheel-dir "$TMP" .
WHEEL="$(cd "$TMP" && ls atl-"$VERSION"-*.whl)"
SHA="$(sha256sum "$TMP/$WHEEL" | cut -d' ' -f1)"

rm -rf "$OUT"
mkdir -p "$OUT"
cp "$TMP/$WHEEL" "$OUT/"
sed -e "s/@VERSION@/$VERSION/g" -e "s/@WHEEL@/$WHEEL/g" -e "s/@SHA256@/$SHA/g" \
  scripts/install-edge.sh.in > "$OUT/install-atl-ide.sh"
chmod 755 "$OUT/install-atl-ide.sh"
sed -e "s/@VERSION@/$VERSION/g" -e "s/@WHEEL@/$WHEEL/g" -e "s/@SHA256@/$SHA/g" \
  scripts/install_edge.py.in > "$OUT/install_atl.py"
python3 - "$OUT" "$VERSION" "$WHEEL" <<'EOF'
import hashlib, json, os, sys
out, version, wheel = sys.argv[1:]
def entry(name):
    data = open(f"{out}/{name}", "rb").read()
    return {"name": name, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
files = [entry("install_atl.py"), entry("install-atl-ide.sh"), entry(wheel)]
json.dump({"version": version, "name": "atl-ide", "module": "atl", "files": files},
          open(f"{out}/release.json", "w"), indent=2)
EOF
echo "edge $VERSION → $OUT"
ls -l "$OUT"
