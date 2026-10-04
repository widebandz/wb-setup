#!/bin/bash
# Exercise the actual launcher decision when bootstrap failed but its guide is live.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
sed -n '/^if connection_is_live; then/,$p' \
  "$ROOT/packaging/app-launcher" > "$TMP/decision"
[ -s "$TMP/decision" ] || { echo 'launcher decision missing' >&2; exit 1; }
sed -n '/^cli_ready() {/,/^}/p' \
  "$ROOT/packaging/app-launcher" > "$TMP/cli-ready"
[ -s "$TMP/cli-ready" ] || { echo 'CLI gate missing' >&2; exit 1; }

check() {
  local name="$1" live="$2" status="$3" identity="$4" tools="$5" cli="$6" expected="$7"
  local home="$TMP/$name" actual
  mkdir -p "$home/.wideband/setup"
  if [ "$status" != - ]; then
    printf '%s\n' "$status" > "$home/.wideband/setup/bootstrap-status"
  fi
  if [ "$identity" = 1 ]; then
    : > "$home/.sop-vars"
  fi
  if [ "$cli" = 1 ]; then
    printf '%s\n' test-build > "$home/.wideband/setup/cli-ready-build"
  fi
  if ! actual="$(HOME="$home" STATE="$home/.wideband/setup" \
    WB_TEST_LIVE="$live" WB_TEST_TOOLS="$tools" \
    WB_TEST_DECISION="$TMP/decision" bash -c '
      connection_is_live() { [ "$WB_TEST_LIVE" = 1 ]; }
      core_ready() { [ -f "$HOME/.sop-vars" ] && [ "$WB_TEST_TOOLS" = 1 ]; }
      cli_ready() { [ "$(sed -n 1p "$STATE/cli-ready-build" 2>/dev/null)" = test-build ] && core_ready; }
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

check canceled_phone_prompt 1 needs_attention 0 1 0 terminal
check phone_prompt_still_open 1 collecting_identity 0 1 0 ''
check failed_partial_bootstrap 1 needs_attention 1 0 0 terminal
check healthy_live_guide 1 needs_attention 1 1 1 ''
check fresh_mac 0 - 0 1 0 terminal
check unpacked_private_tools 0 - 1 1 0 terminal
check completed_mac_without_engine 0 - 1 1 1 background

MARKER_HOME="$TMP/real-cli-ready"
mkdir -p "$MARKER_HOME/.wideband/setup"
printf '%s\n' test-build > "$MARKER_HOME/.wideband/setup/cli-ready-build"
HOME="$MARKER_HOME" STATE="$MARKER_HOME/.wideband/setup" BUILD_ID=test-build \
  WB_TEST_GATE="$TMP/cli-ready" bash -c '
    core_ready() { WB_TOOLCHAIN_KIND="$WB_TEST_KIND"; WB_TOOLCHAIN_BUILD_ID="$WB_TEST_BUILD"; return 0; }
    . "$WB_TEST_GATE"
    WB_TEST_KIND=private; WB_TEST_BUILD=test-build; cli_ready || exit 1
    WB_TEST_KIND=legacy_homebrew; ! cli_ready || exit 2
    WB_TEST_KIND=private; WB_TEST_BUILD=old-build; ! cli_ready || exit 4
    WB_TEST_BUILD=test-build
    rm "$STATE/cli-ready-build"
    printf "%s\n" test-build > "$STATE/other-file"
    ln -s "$STATE/other-file" "$STATE/cli-ready-build"
    WB_TEST_KIND=private; ! cli_ready || exit 3
  '
