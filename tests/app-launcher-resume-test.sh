#!/bin/bash
# Exercise the actual launcher decision when bootstrap failed but its guide is live.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
sed -n '/^# An established Mac can host the private guide/,$p' \
  "$ROOT/packaging/app-launcher" > "$TMP/decision"
[ -s "$TMP/decision" ] || { echo 'launcher decision missing' >&2; exit 1; }

check() {
  local name="$1" live="$2" status="$3" identity="$4" tools="$5" expected="$6"
  local home="$TMP/$name" actual
  mkdir -p "$home/.wideband/setup"
  if [ "$status" != - ]; then
    printf '%s\n' "$status" > "$home/.wideband/setup/bootstrap-status"
  fi
  if [ "$identity" = 1 ]; then
    : > "$home/.sop-vars"
  fi
  if ! actual="$(HOME="$home" STATE="$home/.wideband/setup" \
    WB_TEST_LIVE="$live" WB_TEST_TOOLS="$tools" \
    WB_TEST_DECISION="$TMP/decision" bash -c '
      connection_is_live() { [ "$WB_TEST_LIVE" = 1 ]; }
      core_ready() { [ -f "$HOME/.sop-vars" ] && [ "$WB_TEST_TOOLS" = 1 ]; }
      launch_terminal() { printf terminal; }
      launch_background() { printf background; }
      fail() { printf failure; exit 99; }
      . "$WB_TEST_DECISION"
    ')"; then
    echo "$name: launcher decision failed" >&2
    exit 1
  fi
  if [ "$actual" != "$expected" ]; then
    printf '%s: expected %s, got %s\n' "$name" "$expected" "$actual" >&2
    exit 1
  fi
}

check canceled_phone_prompt 1 needs_attention 0 1 terminal
check phone_prompt_still_open 1 collecting_identity 0 1 ''
check failed_partial_bootstrap 1 needs_attention 1 0 terminal
check healthy_live_guide 1 needs_attention 1 1 ''
check fresh_mac 0 - 0 1 terminal
check completed_mac_without_engine 0 - 1 1 background
