#!/bin/bash
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
STATE="$HOME/.wideband/setup"
CONNECTION="$STATE/connection.json"
ENGINE="$HERE/.wideband-setup-engine"
SETUP_ARGS=()

NATIVE_PID="$(sed -n '1p' "$STATE/native-shell-pid" 2>/dev/null)"
if [ "${1:-}" = "--embedded" ] \
   || { [[ "$NATIVE_PID" =~ ^[0-9]+$ ]] && /bin/kill -0 "$NATIVE_PID" 2>/dev/null; }; then
  export WB_SETUP_EMBEDDED=1
  SETUP_ARGS+=(--no-open)
fi
if [ -f "$STATE/terminal-hosted" ]; then
  export WB_SETUP_TERMINAL_HOSTED=1
fi

if [ -f "$STATE/client-package" ]; then
  export WB_SETUP_CLIENT_MODE=1
fi
if [ -f "$HOME/.sop-vars" ]; then
  # Written by the validated Wideband profile renderer or bootstrap itself.
  # shellcheck disable=SC1090
  . "$HOME/.sop-vars"
fi

# The packaged engine makes the guide available before Homebrew or Command Line
# Tools exist. It also avoids invoking macOS's /usr/bin/python3 developer-tools
# stub, which otherwise opens an unrelated install dialog on a bare Mac.
if [ -x "$ENGINE" ] && { [ -f "$CONNECTION" ] || { [ -x /opt/homebrew/bin/python3 ] && [ -f "$HOME/.sop-vars" ]; }; }; then
  export WB_SETUP_ROOT="$HERE"
  exec "$ENGINE" "${SETUP_ARGS[@]}"
fi

# Brew's Python is the boundary between a genuinely bare Mac and a machine
# capable of running the guided UI. A partial/first build stays in bootstrap;
# an established build goes straight back to its saved installer state.
if [ ! -x "$ENGINE" ] && [ -x /opt/homebrew/bin/python3 ] && [ -f "$HOME/.sop-vars" ]; then
  exec bash "$HERE/setup.sh" "${SETUP_ARGS[@]}"
fi

if [ -x "$ENGINE" ]; then
  export WB_SETUP_ROOT="$HERE"
  "$ENGINE" "${SETUP_ARGS[@]}" &
  ENGINE_PID=$!
  stop_engine() {
    /bin/kill "$ENGINE_PID" 2>/dev/null || true
    wait "$ENGINE_PID" 2>/dev/null || true
  }
  trap stop_engine HUP INT TERM EXIT
  bash "$HERE/bootstrap.sh" --no-fetch --client
  BOOTSTRAP_RC=$?
  if [ "$BOOTSTRAP_RC" -ne 0 ]; then
    ( umask 077; printf '%s\n' needs_attention > "$STATE/bootstrap-status" ) 2>/dev/null || true
  fi
  wait "$ENGINE_PID"
  trap - HUP INT TERM EXIT
  exit 0
fi

exec bash "$HERE/bootstrap.sh" --no-fetch --client
