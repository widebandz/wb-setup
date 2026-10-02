#!/bin/bash
# Exercise the real launcher transition from older owned install directories.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FIXTURE="$(/usr/bin/mktemp -d /tmp/wb-launcher-private-root.XXXXXX)"
trap '/bin/rm -rf "$FIXTURE"' EXIT
SNIPPET="$FIXTURE/prepare-dirs.sh"
/usr/bin/sed -n '/^LAUNCH_STAGE="private install directories"$/,/^if \[\[ "\$NATIVE_PID"/{/^if \[\[ "\$NATIVE_PID"/!p;}' \
  "$ROOT/packaging/app-launcher" > "$SNIPPET"
[ -s "$SNIPPET" ]

for condition in old fresh; do
  HOME_DIR="$FIXTURE/$condition"
  /bin/mkdir -m 700 "$HOME_DIR"
  if [ "$condition" = old ]; then
    /bin/mkdir -m 755 "$HOME_DIR/.wideband"
    /bin/mkdir -m 755 "$HOME_DIR/.wideband/setup"
  fi
  HOME="$HOME_DIR" TARGET="$HOME_DIR/srv/wb-setup" \
    STATE="$HOME_DIR/.wideband/setup" /bin/bash -c '
      fail() { exit 99; }
      . "$1"
    ' _ "$SNIPPET"
  [ "$(/usr/bin/stat -f '%Lp' "$HOME_DIR/.wideband")" = 700 ]
  [ "$(/usr/bin/stat -f '%Lp' "$HOME_DIR/.wideband/setup")" = 700 ]
  HOME="$HOME_DIR" /bin/bash -c '
    . "$1/lib/bootstrap-homebrew.sh"
    wb_hb_identity_probe
    wb_tc_safe_owned "$HOME/.wideband" d
    wb_tc_safe_owned "$HOME/.wideband/setup" d
  ' _ "$ROOT"
done

echo 'launcher private root: pass'
