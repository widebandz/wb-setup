#!/bin/bash
# Keep a previously approved Wideband Agent when its permission-bearing code
# and source inputs have not changed across Setup package builds.

wb_agent_valid() {
  local app="$1"
  [ -x "$app/Contents/MacOS/Wideband Agent" ] \
    && [ "$(/usr/libexec/PlistBuddy -c 'Print CFBundleIdentifier' "$app/Contents/Info.plist" 2>/dev/null)" = ai.wideband.agent ] \
    && /usr/bin/codesign --verify --strict "$app" >/dev/null 2>&1
}

wb_agent_cdhash() {
  /usr/bin/codesign -d --verbose=4 "$1" 2>&1 \
    | /usr/bin/sed -n 's/^CDHash=//p'
}

wb_agent_revision() {
  local app="$1" payload="$2" scratch="$3" temp binary_hash signing revision file
  wb_agent_valid "$app" || return 1
  temp="$(/usr/bin/mktemp -d "$scratch/agent-revision.XXXXXX")" || return 1
  /usr/bin/ditto --norsrc --noextattr --noqtn \
    "$app/Contents/MacOS/Wideband Agent" "$temp/Wideband Agent" \
    || { /bin/rm -rf "$temp"; return 1; }
  /usr/bin/codesign --remove-signature "$temp/Wideband Agent" >/dev/null 2>&1 \
    || { /bin/rm -rf "$temp"; return 1; }
  binary_hash="$(/usr/bin/shasum -a 256 "$temp/Wideband Agent" | /usr/bin/awk '{print $1}')"
  /bin/rm -rf "$temp"
  [ -n "$binary_hash" ] || return 1
  signing="$(/usr/bin/codesign -dvv "$app" 2>&1 \
    | /usr/bin/awk '/^(Signature|Authority|TeamIdentifier)=/ {print}')"
  [ -n "$signing" ] || return 1
  for file in agent/WidebandAgent.swift agent/Info.plist agent/entitlements.plist installer/wideband-mark.png; do
    [ -f "$payload/$file" ] || return 1
  done
  revision="$({
    printf '%s\n' 'wideband-agent-revision-v1' "$binary_hash" "$signing"
    for file in agent/WidebandAgent.swift agent/Info.plist agent/entitlements.plist installer/wideband-mark.png; do
      /usr/bin/shasum -a 256 "$payload/$file" | /usr/bin/awk '{print $1}'
    done
  } | /usr/bin/shasum -a 256 | /usr/bin/awk '{print $1}')" || return 1
  [[ "$revision" =~ ^[0-9a-f]{64}$ ]] || return 1
  printf '%s\n' "$revision"
}
