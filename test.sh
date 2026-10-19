#!/usr/bin/env bash
# Run the test suite, with a workstation's ROS 2 environment kept out of it.
# ROS puts /opt/ros on PYTHONPATH and registers pytest plugins there that fail
# to import without ROS's own dependencies; neither belongs in this project.
#
#   ./test.sh                     everything under tests/
#   ./test.sh tests/test_core.py -k skill
#
# Core-owned (D-LAB-5 tool template): `copier update` rewrites this file.
set -euo pipefail
cd "$(dirname "$0")"
unset PYTHONPATH
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1

if [ ! -x .venv/bin/python ]; then
  echo "  creating .venv ..."
  python3 -m venv .venv
  .venv/bin/python -m pip install --quiet --upgrade pip
fi
# `python -m pip`, not `.venv/bin/pip`: that wrapper is a generated script with
# an absolute shebang, so a venv copied in from another directory has one that
# points nowhere. The module always belongs to the interpreter running it.
cat requirements.txt requirements-dev.txt > .venv/.test-requirements.new
if ! cmp -s .venv/.test-requirements.new .venv/.test-requirements.txt; then
  echo "  installing requirements ..."
  .venv/bin/python -m pip install --quiet -r requirements.txt -r requirements-dev.txt
  mv .venv/.test-requirements.new .venv/.test-requirements.txt
  # run.sh keeps its own stamp; the runtime set is now installed too
  cp requirements.txt .venv/.requirements.txt
else
  rm -f .venv/.test-requirements.new
fi
exec .venv/bin/python -m pytest "${@:-tests/}"
