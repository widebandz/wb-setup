#!/bin/bash
set -uo pipefail
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:$HOME/.local/bin"

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
CLIENT_BUILD=""
if [ -f "$STATE/client-package" ]; then
  CLIENT_BUILD="$(sed -n '1p' "$STATE/client-package" 2>/dev/null)"
fi
if [ -f "$HOME/.sop-vars" ]; then
  # Written by the validated Wideband profile renderer or bootstrap itself.
  # shellcheck disable=SC1090
  . "$HOME/.sop-vars"
fi

# The packaged client completes its Terminal foundation before opening the
# guide. A prior identity or Python alone cannot prove this build's bundled
# tools are usable. The build marker makes interrupted runs resume here.
QUICK_READY=0
if [ -f "$HERE/lib/bootstrap-homebrew.sh" ]; then
  # shellcheck source=lib/bootstrap-homebrew.sh
  . "$HERE/lib/bootstrap-homebrew.sh"
fi
if [ -f "$HOME/.sop-vars" ] \
   && command -v wb_tc_resolve >/dev/null 2>&1 \
   && wb_tc_resolve \
   && { [ -z "$CLIENT_BUILD" ] \
        || { [ "$WB_TOOLCHAIN_KIND" = private ] \
             && [ "$WB_TOOLCHAIN_BUILD_ID" = "$CLIENT_BUILD" ]; }; }; then
  QUICK_READY=1
fi
if [ -f "$STATE/client-package" ]; then
  CLI_BUILD="$(sed -n '1p' "$STATE/cli-ready-build" 2>/dev/null)"
  if [ -z "$CLIENT_BUILD" ]; then
    printf '  ✗ Wideband client build ID is missing. Reopen the packaged app.\n' >&2
    exit 1
  fi
  if [ "$CLI_BUILD" != "$CLIENT_BUILD" ] || [ "$QUICK_READY" != 1 ] \
     || [ ! -f "$STATE/cli-ready-build" ] || [ -L "$STATE/cli-ready-build" ]; then
    if [ ! -t 1 ]; then
      printf '  ✗ Wideband needs its visible Terminal bootstrap before the guide opens.\n' >&2
      exit 1
    fi
    printf '\n▩ Wideband CLI install · %s\n' "$CLIENT_BUILD"
    printf '  Checking this login, the private tools, and the saved client identity.\n'
    printf '  This stage can be rerun safely after an interruption.\n\n'
    bash "$HERE/bootstrap.sh" --no-fetch --client --no-ui
    BOOTSTRAP_RC=$?
    if [ "$BOOTSTRAP_RC" -ne 0 ] \
       || [ "$(sed -n '1p' "$STATE/bootstrap-status" 2>/dev/null)" != ready ]; then
      printf '\n  ✗ CLI foundation is incomplete. Fix the reason above, then reopen Wideband Setup.\n' >&2
      exit 1
    fi
    QUICK_READY=0
    if wb_tc_resolve && [ "$WB_TOOLCHAIN_KIND" = private ] \
       && [ "$WB_TOOLCHAIN_BUILD_ID" = "$CLIENT_BUILD" ] \
       && [ -f "$HOME/.sop-vars" ]; then QUICK_READY=1; fi
    if [ "$QUICK_READY" != 1 ]; then
      printf '  ✗ Verified client tools or identity disappeared during bootstrap.\n' >&2
      exit 1
    fi
    if [ ! -x "$HERE/lib/toolchain-path" ]; then
      printf '  ✗ Wideband tool resolver is missing. Reopen the packaged app.\n' >&2
      exit 1
    fi
    for tool in python3 node tmux ttyd imsg; do
      if ! wb_tc_private_bin "$tool"; then
        printf '  ✗ Verified %s is unavailable. Reopen the packaged app.\n' "$tool" >&2
        exit 1
      fi
      printf '  ✓ %s verified\n' "$tool"
    done
    if [ -L "$STATE/cli-ready-build" ] \
       || { [ -e "$STATE/cli-ready-build" ] && [ ! -f "$STATE/cli-ready-build" ]; }; then
      printf '  ✗ Unsafe CLI completion marker.\n' >&2
      exit 1
    fi
    CLI_TEMP="$(/usr/bin/mktemp "$STATE/cli-ready-build.XXXXXX")" \
      || { printf '  ✗ Cannot create CLI completion marker.\n' >&2; exit 1; }
    if ! printf '%s\n' "$CLIENT_BUILD" > "$CLI_TEMP" \
       || ! /bin/chmod 600 "$CLI_TEMP" \
       || ! /bin/mv -f "$CLI_TEMP" "$STATE/cli-ready-build"; then
      /bin/rm -f "$CLI_TEMP" 2>/dev/null || true
      printf '  ✗ Cannot save CLI completion.\n' >&2
      exit 1
    fi
    printf '\n  ✓ Machine foundation ready. Opening the guided setup.\n\n'
  fi
fi
if [ -x "$ENGINE" ] && [ "$QUICK_READY" = 1 ]; then
  export WB_SETUP_ROOT="$HERE"
  exec "$ENGINE" "${SETUP_ARGS[@]+"${SETUP_ARGS[@]}"}"
fi

# Standalone source installs still use the historical bootstrap and setup.sh
# fallback. The packaged client above cannot enter the guide without its
# current-build CLI marker and verified private tools.
if [ ! -x "$ENGINE" ] && [ "$QUICK_READY" = 1 ]; then
  exec bash "$HERE/setup.sh" "${SETUP_ARGS[@]+"${SETUP_ARGS[@]}"}"
fi

if [ -x "$ENGINE" ]; then
  export WB_SETUP_ROOT="$HERE"
  "$ENGINE" "${SETUP_ARGS[@]+"${SETUP_ARGS[@]}"}" &
  ENGINE_PID=$!
  stop_engine() {
    /bin/kill "$ENGINE_PID" 2>/dev/null || true
    wait "$ENGINE_PID" 2>/dev/null || true
  }
  trap stop_engine HUP INT TERM EXIT
  bash "$HERE/bootstrap.sh" --no-fetch --client
  BOOTSTRAP_RC=$?
  if [ "$BOOTSTRAP_RC" -ne 0 ]; then
    case "$(sed -n '1p' "$STATE/bootstrap-status" 2>/dev/null)" in
      needs_independent_toolchain|needs_homebrew_ownership|needs_developer_tools*) ;;
      *) ( umask 077; printf '%s\n' needs_attention > "$STATE/bootstrap-status" ) 2>/dev/null || true ;;
    esac
  fi
  wait "$ENGINE_PID"
  trap - HUP INT TERM EXIT
  exit 0
fi

exec bash "$HERE/bootstrap.sh" --no-fetch --client
