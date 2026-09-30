#!/bin/bash
# Read-only downloaded-app check. Runs before app-launcher creates client files.
set -uo pipefail
export PATH=/usr/bin:/bin:/usr/sbin:/sbin

[ "$#" -eq 3 ] || exit 2
APP="$1"
PAYLOAD="$2"
BUILD_ID="$3"

stop() {
  printf '%s\n' "$1" >&2
  exit 1
}

[[ "$BUILD_ID" =~ ^[0-9]+\.[0-9]+\.[0-9]+-[0-9]{14}$ ]] \
  || stop "This installer has an invalid build identifier."
[ "$(/usr/bin/uname -m)" = arm64 ] \
  || stop "Wideband Setup needs an Apple Silicon Mac."
OS_MAJOR="$(/usr/bin/sw_vers -productVersion | /usr/bin/cut -d. -f1)"
case "$OS_MAJOR" in ''|*[!0-9]*) stop "Could not identify the macOS version." ;; esac
[ "$OS_MAJOR" -ge 14 ] \
  || stop "Update this Mac to macOS 14 or newer before using this client installer."

UID_N="$(/usr/bin/id -u)"
[ "$UID_N" -gt 0 ] && [ -d "$HOME" ] && [ ! -L "$HOME" ] \
  && [ "$(/usr/bin/stat -f '%u' "$HOME" 2>/dev/null)" = "$UID_N" ] \
  && [ "$(/usr/bin/stat -f '%Su' /dev/console 2>/dev/null)" = "$(/usr/bin/id -un)" ] \
  || stop "Sign in to a normal macOS account that owns its home folder."

[ -d "$APP" ] && [ ! -L "$APP" ] && [ -d "$PAYLOAD" ] \
  && [ ! -L "$PAYLOAD" ] \
  || stop "The downloaded Wideband app payload is missing or redirected."
/usr/bin/codesign --verify --strict "$APP" >/dev/null 2>&1 \
  || stop "The downloaded Wideband app failed its integrity check."
TOOLS="$PAYLOAD/vendor/toolchain"
[ -d "$TOOLS" ] && [ ! -L "$TOOLS" ] \
  && [ -f "$TOOLS/manifest.sha256" ] && [ ! -L "$TOOLS/manifest.sha256" ] \
  || stop "This Wideband download is missing its independent tool payload."
[ -z "$(/usr/bin/find "$TOOLS" -type l -print -quit 2>/dev/null)" ] \
  || stop "The tool payload contains a redirected file."
EXPECTED="$(/usr/bin/wc -l < "$TOOLS/manifest.sha256" 2>/dev/null | /usr/bin/tr -d ' ')"
ACTUAL="$(/usr/bin/find "$TOOLS" -type f ! -name manifest.sha256 -print 2>/dev/null | /usr/bin/wc -l | /usr/bin/tr -d ' ')"
[ -n "$EXPECTED" ] && [ "$EXPECTED" = "$ACTUAL" ] \
  && ( cd "$TOOLS" && /usr/bin/shasum -a 256 -c manifest.sha256 >/dev/null 2>&1 ) \
  || stop "The independent tool payload failed its checksum check."

for TARGET in "$HOME/Applications" "$HOME/srv" "$HOME/srv/wb-setup" \
              "$HOME/.wideband" "$HOME/.wideband/setup" \
              "$HOME/.wideband/toolchain" "$HOME/.wideband/toolchain/versions"; do
  if [ -e "$TARGET" ] || [ -L "$TARGET" ]; then
    [ -d "$TARGET" ] && [ ! -L "$TARGET" ] \
      && [ "$(/usr/bin/stat -f '%u' "$TARGET" 2>/dev/null)" = "$UID_N" ] \
      || stop "A Wideband install directory is redirected or owned by another account."
  fi
done
for TARGET in "$HOME/Applications/Wideband Setup.app" \
              "$HOME/Applications/Wideband Agent.app"; do
  if [ -e "$TARGET" ] || [ -L "$TARGET" ]; then
    [ -d "$TARGET" ] && [ ! -L "$TARGET" ] \
      && [ "$(/usr/bin/stat -f '%u' "$TARGET" 2>/dev/null)" = "$UID_N" ] \
      || stop "An existing Wideband app path needs owner review before upgrade."
  fi
done

PAYLOAD_KIB="$(/usr/bin/du -sk "$PAYLOAD" | /usr/bin/awk '{print $1}')"
FREE_KIB="$(/bin/df -k "$HOME" | /usr/bin/awk 'NR == 2 {print $4}')"
case "$PAYLOAD_KIB:$FREE_KIB" in *[!0-9:]*|:*|*:) stop "Could not measure available disk space." ;; esac
NEEDED_KIB=$((PAYLOAD_KIB * 3 + 524288))
[ "$FREE_KIB" -ge "$NEEDED_KIB" ] \
  || stop "Free more disk space before installing Wideband Setup and its rollback copy."

# Another login's Homebrew is inventory, never a repair target. Port owners
# and account permissions are checked by their own phases before activation.
printf '%s\n' "downloaded_app=ready" "tool_payload=ready" "platform=ready" "disk=ready"
