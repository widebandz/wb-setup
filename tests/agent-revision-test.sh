#!/bin/bash
# Verify that a Setup-only rebuild preserves a signed Agent, and that changed
# code or a damaged signature forces a replacement.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(/usr/bin/mktemp -d /tmp/wb-agent-revision-test.XXXXXX)"
trap '/bin/rm -rf "$TMP"' EXIT
. "$ROOT/packaging/agent-revision.sh"

for payload in old new changed; do
  /bin/mkdir -p "$TMP/$payload/agent" "$TMP/$payload/installer"
  for file in WidebandAgent.swift Info.plist entitlements.plist; do
    /bin/cp "$ROOT/agent/$file" "$TMP/$payload/agent/$file"
  done
  /bin/cp "$ROOT/installer/wideband-mark.png" "$TMP/$payload/installer/wideband-mark.png"
done
printf '\n// changed Agent source\n' >> "$TMP/changed/agent/WidebandAgent.swift"

make_app() {
  local path="$1" version="$2" source="$3"
  /bin/mkdir -p "$path/Contents/MacOS" "$path/Contents/Resources"
  /bin/cp "$ROOT/agent/Info.plist" "$path/Contents/Info.plist"
  /usr/bin/plutil -replace CFBundleVersion -string "$version" "$path/Contents/Info.plist"
  /bin/cp "$ROOT/installer/wideband-mark.png" "$path/Contents/Resources/AppIcon.icns"
  /usr/bin/clang -target arm64-apple-macos13.0 "$source" \
    -o "$path/Contents/MacOS/Wideband Agent"
  /usr/bin/codesign --force --options runtime \
    --entitlements "$ROOT/agent/entitlements.plist" --sign - "$path" >/dev/null
}

printf '%s\n' 'int main(void) { return 0; }' > "$TMP/agent.c"
printf '%s\n' 'int main(void) { return 1; }' > "$TMP/changed-agent.c"
make_app "$TMP/old-agent.app" 1 "$TMP/agent.c"
make_app "$TMP/new-agent.app" 2 "$TMP/agent.c"
make_app "$TMP/changed-agent.app" 3 "$TMP/changed-agent.c"

old_revision="$(wb_agent_revision "$TMP/old-agent.app" "$TMP/old" "$TMP")"
new_revision="$(wb_agent_revision "$TMP/new-agent.app" "$TMP/new" "$TMP")"
[ "$old_revision" = "$new_revision" ] || { echo 'package timestamp changed Agent revision' >&2; exit 1; }
[ "$(wb_agent_revision "$TMP/new-agent.app" "$TMP/changed" "$TMP")" != "$new_revision" ] \
  || { echo 'Agent source change did not change revision' >&2; exit 1; }
[ "$(wb_agent_revision "$TMP/changed-agent.app" "$TMP/new" "$TMP")" != "$new_revision" ] \
  || { echo 'compiled Agent change did not change revision' >&2; exit 1; }

# Run the real launcher's Agent decision against private temporary app bundles.
/usr/bin/sed -n '/^# Install the exact app/,/^# Every packaged launch/{/^# Every packaged launch/!p;}' \
  "$ROOT/packaging/app-launcher" > "$TMP/agent-decision.sh"
[ -s "$TMP/agent-decision.sh" ] || { echo 'Agent decision missing' >&2; exit 1; }
STATE="$TMP/state"
TARGET="$TMP/installed-payload"
PREVIOUS_SETUP_APP="$TMP/previous/Wideband Setup.app"
AGENT_TARGET="$TMP/installed/Wideband Agent.app"
AGENT_SOURCE="$TMP/new-agent.app"
PAYLOAD="$TMP/new"
AGENT_MARKER="$STATE/agent-build"
AGENT_REVISION_MARKER="$STATE/agent-revision"
AGENT_CDHASH_MARKER="$STATE/agent-cdhash"
DEACTIVATED="$STATE/deactivated"
BUILD_ID='0.6.0-new'
AGENT_REVISION="$new_revision"
SETUP_APP_INSTALLED='0.6.0-old'
PREVIOUS_PAYLOAD_BUILD='0.6.0-old'
/bin/mkdir -p "$STATE" "$TARGET" "$PREVIOUS_SETUP_APP/Contents/Resources" "$(dirname "$AGENT_TARGET")"
/usr/bin/ditto "$TMP/old" "$TARGET"
/usr/bin/ditto "$TMP/old-agent.app" "$AGENT_TARGET"
/usr/bin/ditto "$TMP/old-agent.app" "$PREVIOUS_SETUP_APP/Contents/Resources/Wideband Agent.app"
printf '%s\n' '0.6.0-old' > "$AGENT_MARKER"
printf '%s\n' '0.6.0-old' > "$PREVIOUS_SETUP_APP/Contents/Resources/build-id.txt"
fail() { echo 'Agent launcher failed' >&2; exit 1; }

old_cdhash="$(wb_agent_cdhash "$AGENT_TARGET")"
. "$TMP/agent-decision.sh"
[ "$(wb_agent_cdhash "$AGENT_TARGET")" = "$old_cdhash" ] \
  && [ "$(cat "$AGENT_REVISION_MARKER")" = "$new_revision" ] \
  || { echo 'migration did not preserve approved Agent' >&2; exit 1; }

# Installing Setup.app by copying it over the old bundle removes the old
# embedded Agent before launch. The old payload and signed Agent remain.
/bin/rm -f "$AGENT_REVISION_MARKER" "$AGENT_CDHASH_MARKER"
/bin/rm -rf "$PREVIOUS_SETUP_APP/Contents/Resources/Wideband Agent.app"
/usr/bin/ditto "$TMP/new-agent.app" "$PREVIOUS_SETUP_APP/Contents/Resources/Wideband Agent.app"
printf '%s\n' "$BUILD_ID" > "$PREVIOUS_SETUP_APP/Contents/Resources/build-id.txt"
. "$TMP/agent-decision.sh"
[ "$(wb_agent_cdhash "$AGENT_TARGET")" = "$old_cdhash" ] \
  && [ "$(cat "$AGENT_REVISION_MARKER")" = "$new_revision" ] \
  || { echo 'in-place Setup replacement rotated approved Agent' >&2; exit 1; }

# A prior Setup bundle that still claims the old build but embeds different
# code is contradictory evidence, so the launcher must replace the Agent.
/bin/rm -f "$AGENT_REVISION_MARKER" "$AGENT_CDHASH_MARKER"
/bin/rm -rf "$PREVIOUS_SETUP_APP/Contents/Resources/Wideband Agent.app"
/usr/bin/ditto "$TMP/changed-agent.app" "$PREVIOUS_SETUP_APP/Contents/Resources/Wideband Agent.app"
printf '%s\n' "$AGENT_INSTALLED" > "$PREVIOUS_SETUP_APP/Contents/Resources/build-id.txt"
. "$TMP/agent-decision.sh"
[ "$(wb_agent_cdhash "$AGENT_TARGET")" = "$(wb_agent_cdhash "$AGENT_SOURCE")" ] \
  || { echo 'conflicting old Setup bundle was trusted' >&2; exit 1; }

# Restore the old Agent and known markers for the normal repeated-launch test.
/bin/rm -rf "$AGENT_TARGET"
/usr/bin/ditto "$TMP/old-agent.app" "$AGENT_TARGET"
printf '%s\n' "$new_revision" > "$AGENT_REVISION_MARKER"
printf '%s\n' "$old_cdhash" > "$AGENT_CDHASH_MARKER"

# Once recorded, the stable revision remains enough after the old Setup
# bundle and payload have been replaced by a newer package.
/bin/rm -rf "$PREVIOUS_SETUP_APP"
/usr/bin/ditto "$TMP/new" "$TARGET"
. "$TMP/agent-decision.sh"
[ "$(wb_agent_cdhash "$AGENT_TARGET")" = "$old_cdhash" ] \
  || { echo 'repeated Setup launch replaced unchanged Agent' >&2; exit 1; }

AGENT_SOURCE="$TMP/changed-agent.app"
PAYLOAD="$TMP/changed"
AGENT_REVISION="$(wb_agent_revision "$AGENT_SOURCE" "$TMP/changed" "$TMP")"
/bin/rm -rf "$STATE/package-backups"
. "$TMP/agent-decision.sh"
changed_cdhash="$(wb_agent_cdhash "$AGENT_TARGET")"
[ "$changed_cdhash" != "$old_cdhash" ] \
  || { echo 'changed Agent was not installed' >&2; exit 1; }

# A self-consistent marker cannot permit reuse of a corrupted signature.
printf 'damage\n' >> "$AGENT_TARGET/Contents/Resources/AppIcon.icns"
AGENT_SOURCE="$TMP/new-agent.app"
PAYLOAD="$TMP/new"
AGENT_REVISION="$new_revision"
/bin/rm -rf "$STATE/package-backups"
. "$TMP/agent-decision.sh"
[ "$(wb_agent_cdhash "$AGENT_TARGET")" = "$(wb_agent_cdhash "$AGENT_SOURCE")" ] \
  && wb_agent_valid "$AGENT_TARGET" \
  || { echo 'damaged Agent was not repaired' >&2; exit 1; }
