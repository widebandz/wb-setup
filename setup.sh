#!/bin/bash
# Open the resumable Wideband guided installer with its verified Python.
set -uo pipefail
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:$HOME/.local/bin"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$(/bin/bash "$HERE/lib/toolchain-path" python3 2>/dev/null)" || PY=""

if [ -z "$PY" ]; then
  echo "Wideband Setup needs a verified private or approved legacy Python runtime."
  echo "Reopen the current installer package, then run this command again."
  exit 1
fi

export PATH="${PY%/python3}:/usr/bin:/bin:/usr/sbin:/sbin:$HOME/.local/bin"
exec "$PY" "$HERE/setup.py" "$@"
