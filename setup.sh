#!/bin/bash
# Open the resumable Wideband guided installer. bootstrap.sh installs Python;
# this wrapper keeps the entry point memorable and reports the one useful fix
# when it is launched too early.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY=""
command -v python3 >/dev/null 2>&1 && PY="$(command -v python3)"
[ -z "$PY" ] && [ -x /opt/homebrew/bin/python3 ] && PY=/opt/homebrew/bin/python3

if [ -z "$PY" ]; then
  echo "Wideband Setup needs the Python runtime from the Brewfile."
  echo "Let bootstrap.sh finish, then run this command again."
  exit 1
fi

exec "$PY" "$HERE/setup.py" "$@"
