#!/usr/bin/env bash
# Start atl-ide, creating the virtualenv on first run and replacing any
# instance already holding the port. Ubuntu 24.04 is PEP-668 managed, so Flask
# has to live in a venv, not in system pip.
#
#   ./run.sh                   start (or restart) on 127.0.0.1:8780
#   ./run.sh --port 9000       somewhere else
#   ./run.sh --stop            shut the running one down and exit
#   ./run.sh --no-update-check any other option goes to the app as it is
#
# Core-owned (D-LAB-5 tool template): `copier update` rewrites this file.
set -euo pipefail
cd "$(dirname "$0")"

# ROS 2 puts /opt/ros on PYTHONPATH for every shell on a DLAB5 workstation, and
# a venv does not override it: its site-packages would shadow ours. Nothing
# here wants ROS, so drop it before Python starts.
unset PYTHONPATH

PORT=8780
BIND=127.0.0.1
STOP_ONLY=0
PASS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --host) BIND="$2"; shift 2 ;;
    --stop) STOP_ONLY=1; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) PASS+=("$1"); shift ;;
  esac
done

stop_server() {
  # ask it to close itself first, so a write in flight can finish
  curl -fsS -X POST "http://127.0.0.1:$PORT/api/shutdown" >/dev/null 2>&1 || true
  sleep 0.4
  # "nothing is listening" is the normal case, not a failure: keep set -e happy
  local holder
  holder=$(ss -ltnp 2>/dev/null | grep ":$PORT " | grep -o 'pid=[0-9]*' |
           cut -d= -f2 | head -1 || true)
  if [ -n "${holder:-}" ]; then
    echo "  killing pid $holder"
    kill "$holder" 2>/dev/null || true
    sleep 0.4
    kill -9 "$holder" 2>/dev/null || true
  fi
  # wait for the port to come free, so the restart does not race the old socket
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    ss -ltn 2>/dev/null | grep -q ":$PORT " || return 0
    sleep 0.3
  done
  echo "  ! port $PORT is still held — start somewhere else with --port"
  return 1
}

if [ "$STOP_ONLY" = 1 ]; then
  stop_server
  echo "  stopped"
  exit 0
fi

# Install on first run, and again whenever requirements.txt changed since: a
# dependency added upstream should not surface as an ImportError after git pull.
if [ ! -x .venv/bin/python ]; then
  echo "  creating .venv ..."
  python3 -m venv .venv
  .venv/bin/python -m pip install --quiet --upgrade pip
fi
# `python -m pip` rather than `.venv/bin/pip`: that wrapper is a generated
# script carrying an absolute shebang, so a venv that was copied from another
# directory has one that points nowhere and fails with "cannot execute:
# required file not found". The module always belongs to the interpreter
# running it.
if ! cmp -s requirements.txt .venv/.requirements.txt; then
  echo "  installing requirements ..."
  .venv/bin/python -m pip install --quiet -r requirements.txt
  cp requirements.txt .venv/.requirements.txt
fi

stop_server
echo "  starting atl-ide on http://$BIND:$PORT"
exec .venv/bin/python -m atl.app --host "$BIND" --port "$PORT" ${PASS[@]+"${PASS[@]}"}
