#!/bin/bash
# Activate the exact bundled tool payload without using or changing Homebrew.
# macOS /bin/bash 3.2 only; runs as the console user from app-launcher.
set -euo pipefail

[ "$#" -eq 2 ] || { echo "toolchain installer needs source and build ID" >&2; exit 2; }
SOURCE="$1"
BUILD_ID="$2"
case "$BUILD_ID" in
  ''|*[!A-Za-z0-9._-]*) echo "invalid toolchain build ID" >&2; exit 2 ;;
esac
[[ "$BUILD_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$ ]] \
  || { echo "invalid toolchain build ID" >&2; exit 2; }
[ -d "$SOURCE" ] && [ ! -L "$SOURCE" ] && [ -f "$SOURCE/manifest.sha256" ] \
  && [ ! -L "$SOURCE/manifest.sha256" ] \
  || { echo "bundled toolchain is missing or unsafe" >&2; exit 1; }
SOURCE_COUNT="$(/usr/bin/find "$SOURCE" -type f ! -path "$SOURCE/manifest.sha256" -print \
  | /usr/bin/wc -l | /usr/bin/tr -d ' ')"
MANIFEST_COUNT="$(/usr/bin/wc -l < "$SOURCE/manifest.sha256" | /usr/bin/tr -d ' ')"
[ -z "$(/usr/bin/find "$SOURCE" -mindepth 1 \
    \( -type l -o ! \( -type f -o -type d \) \) -print -quit)" ] \
  && [ "$SOURCE_COUNT" = "$MANIFEST_COUNT" ] \
  && ( cd "$SOURCE" && /usr/bin/shasum -a 256 -c manifest.sha256 >/dev/null 2>&1 ) \
  || { echo "bundled toolchain failed its complete checksum check" >&2; exit 1; }

HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib/bootstrap-homebrew.sh
. "$HERE/bootstrap-homebrew.sh"
wb_hb_identity_probe
[ "$WB_HB_IDENTITY_SAFE" = 1 ] && [ "$WB_HB_ARCH" = arm64 ] \
  && [ "$WB_HB_CONSOLE_USER" = "$WB_HB_USER" ] \
  || { echo "toolchain needs the intended Apple Silicon login" >&2; exit 1; }

umask 077
ROOT="$HOME/.wideband/toolchain"
VERSIONS="$ROOT/versions"
for directory in "$HOME/.wideband" "$ROOT" "$VERSIONS"; do
  if [ -e "$directory" ] || [ -L "$directory" ]; then
    wb_tc_safe_owned "$directory" d \
      || { echo "private toolchain parent is unsafe" >&2; exit 1; }
  else
    /bin/mkdir -m 700 "$directory"
  fi
done

ACTIVE="$ROOT/active"
OLD_BUILD=""
if [ -e "$ACTIVE" ] || [ -L "$ACTIVE" ]; then
  wb_tc_safe_owned "$ACTIVE" f 600 \
    || { echo "existing toolchain activation is unsafe" >&2; exit 1; }
  OLD_BUILD="$(/usr/bin/sed -n '1p' "$ACTIVE")"
  [[ "$OLD_BUILD" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$ ]] \
    || { echo "existing toolchain activation is invalid" >&2; exit 1; }
fi

DEST="$VERSIONS/$BUILD_ID"
STAGE=""
cleanup() {
  if [ -n "$STAGE" ] && [ -d "$STAGE" ] && [ ! -L "$STAGE" ]; then
    /bin/rm -rf -- "$STAGE"
  fi
}
trap cleanup EXIT INT TERM

if [ -e "$DEST" ] || [ -L "$DEST" ]; then
  [ -d "$DEST" ] && [ ! -L "$DEST" ] \
    || { echo "existing toolchain version path is unsafe" >&2; exit 1; }
  /usr/bin/cmp -s "$SOURCE/manifest.sha256" "$DEST/manifest.sha256" \
    || { echo "existing toolchain version differs from this app" >&2; exit 1; }
  WB_TOOLCHAIN_PREFIX="$DEST"
  WB_TOOLCHAIN_BIN="$DEST/bin"
  wb_tc_safe_owned "$DEST" d && wb_tc_safe_owned "$DEST/manifest.sha256" f 600 \
    && wb_tc_manifest_verify \
    || { echo "existing toolchain version failed verification" >&2; exit 1; }
else
  STAGE="$(/usr/bin/mktemp -d "$VERSIONS/.stage.$BUILD_ID.XXXXXX")"
  /usr/bin/ditto "$SOURCE" "$STAGE"
  /usr/bin/find "$STAGE" -type d -exec /bin/chmod 700 {} +
  /usr/bin/find "$STAGE" -type f -exec /bin/chmod 600 {} +
  for tool in python3 tmux imsg node npm ttyd; do
    [ -f "$STAGE/bin/$tool" ] && [ ! -L "$STAGE/bin/$tool" ] \
      || { echo "bundled tool is missing" >&2; exit 1; }
    /bin/chmod 700 "$STAGE/bin/$tool"
  done
  /usr/bin/find "$STAGE" -type f \( -name '*.so' -o -name '*.dylib' \) \
    -exec /bin/chmod 700 {} +
  WB_TOOLCHAIN_PREFIX="$STAGE"
  WB_TOOLCHAIN_BIN="$STAGE/bin"
  wb_tc_manifest_verify \
    || { echo "bundled toolchain manifest failed verification" >&2; exit 1; }
  for tool in python3 tmux imsg node npm ttyd; do
    wb_tc_private_bin "$tool" \
      || { echo "bundled toolchain executable failed verification" >&2; exit 1; }
  done
  /bin/mv "$STAGE" "$DEST"
  STAGE=""
fi

NEXT="$(/usr/bin/mktemp "$ROOT/.active.XXXXXX")"
printf '%s\n' "$BUILD_ID" > "$NEXT"
/bin/chmod 600 "$NEXT"
/bin/mv -f "$NEXT" "$ACTIVE"
if ! WB_TC_REQUIRE_PRIVATE=1 wb_tc_resolve python3; then
  if [ -n "$OLD_BUILD" ]; then
    NEXT="$(/usr/bin/mktemp "$ROOT/.active.XXXXXX")"
    printf '%s\n' "$OLD_BUILD" > "$NEXT"
    /bin/chmod 600 "$NEXT"
    /bin/mv -f "$NEXT" "$ACTIVE"
  else
    /bin/rm -f -- "$ACTIVE"
  fi
  echo "toolchain activation failed verification; previous selection restored" >&2
  exit 1
fi
printf 'Wideband toolchain ready: %s\n' "$BUILD_ID"
