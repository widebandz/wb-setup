#!/bin/bash
# A client checkout must be refused before the scoped installer mutates HOME.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMP="$(mktemp -d)"
trap 'rm -rf "$TEMP"' EXIT
CLIENT_HOME="$TEMP/home"
mkdir -p "$CLIENT_HOME/srv/fleetdeck/.git"
printf 'client work\n' > "$CLIENT_HOME/srv/fleetdeck/README"
printf 'ORG=sample\nBRAND=Sample\n' > "$CLIENT_HOME/.sop-vars"
chmod 644 "$CLIENT_HOME/.sop-vars"

if HOME="$CLIENT_HOME" bash "$ROOT/install.sh" --phone-only --no-verify \
     > "$TEMP/output" 2>&1; then
  echo 'phone-only install accepted an existing Fleetdeck checkout' >&2
  exit 1
fi
grep -q 'existing Fleetdeck checkout' "$TEMP/output"
grep -q 'managed customer phone stack needs an isolated bundled source' "$TEMP/output"
test "$(cat "$CLIENT_HOME/srv/fleetdeck/README")" = 'client work'
test "$(stat -f '%Lp' "$CLIENT_HOME/.sop-vars")" = 644
test ! -e "$CLIENT_HOME/.wideband"
test ! -e "$CLIENT_HOME/.claude"
test ! -e "$CLIENT_HOME/Library"
