#!/bin/bash
# Exercise the packaged-tool activation and rollback boundary in an empty home.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FIXTURE="$(/usr/bin/mktemp -d /tmp/wb-tool-install.XXXXXX)"
cleanup() {
  /usr/bin/find "$FIXTURE" -type d -exec /bin/chmod u+w {} +
  /bin/rm -rf "$FIXTURE"
}
trap cleanup EXIT
HOME_DIR="$FIXTURE/home"
SOURCE="$FIXTURE/source"
/bin/mkdir -m 700 "$HOME_DIR" "$SOURCE" "$SOURCE/bin" "$SOURCE/lib" "$SOURCE/lib/python3.11"

for tool in python3 tmux imsg node npm ttyd; do
  printf '#!/bin/sh\nprintf "%%s\\n" "%s"\n' "$tool" > "$SOURCE/bin/$tool"
  /bin/chmod 755 "$SOURCE/bin/$tool"
done
printf 'runtime resource\n' > "$SOURCE/lib/resource.dat"
printf 'stdlib resource\n' > "$SOURCE/lib/python3.11/module.py"
/bin/chmod 644 "$SOURCE/lib/resource.dat"
/usr/bin/find "$SOURCE" -type f ! -name manifest.sha256 -print | /usr/bin/sort | while IFS= read -r file; do
  relative="${file#"$SOURCE"/}"
  /usr/bin/shasum -a 256 "$file" | /usr/bin/awk -v path="$relative" '{print $1 "  " path}'
done > "$SOURCE/manifest.sha256"
/bin/chmod 644 "$SOURCE/manifest.sha256"

HOME="$HOME_DIR" /bin/bash "$ROOT/lib/install-toolchain.sh" "$SOURCE" 0.8.0-first >/dev/null
ACTIVE="$HOME_DIR/.wideband/toolchain/active"
[ "$(/usr/bin/sed -n '1p' "$ACTIVE")" = 0.8.0-first ]
SELECTED="$(HOME="$HOME_DIR" WB_TC_REQUIRE_PRIVATE=1 "$ROOT/lib/toolchain-path" python3)"
[ "$SELECTED" = "$HOME_DIR/.wideband/toolchain/versions/0.8.0-first/bin/python3" ]
[ "$("$SELECTED")" = python3 ]
[ "$(/usr/bin/stat -f '%Lp' "$HOME_DIR/.wideband/toolchain/versions/0.8.0-first/lib/python3.11")" = 500 ]

# A second package can stage and switch without deleting the previous one.
HOME="$HOME_DIR" /bin/bash "$ROOT/lib/install-toolchain.sh" "$SOURCE" 0.8.0-second >/dev/null
[ "$(/usr/bin/sed -n '1p' "$ACTIVE")" = 0.8.0-second ]
[ -x "$HOME_DIR/.wideband/toolchain/versions/0.8.0-first/bin/python3" ]

# Changed source cannot replace an already selected version. The old pointer
# remains intact even when an adversarial package reuses the same build ID.
printf 'altered\n' >> "$SOURCE/lib/resource.dat"
if HOME="$HOME_DIR" /bin/bash "$ROOT/lib/install-toolchain.sh" "$SOURCE" 0.8.0-second >/dev/null 2>&1; then
  echo 'installer accepted a changed same-ID package' >&2
  exit 1
fi
[ "$(/usr/bin/sed -n '1p' "$ACTIVE")" = 0.8.0-second ]

# A damaged installed runtime must fail closed, rather than falling back to a
# different profile's Homebrew or reporting that the installer is ready.
printf 'altered\n' >> "$HOME_DIR/.wideband/toolchain/versions/0.8.0-second/lib/resource.dat"
if HOME="$HOME_DIR" WB_TC_REQUIRE_PRIVATE=1 "$ROOT/lib/toolchain-path" python3 >/dev/null 2>&1; then
  echo 'resolver accepted an altered active runtime' >&2
  exit 1
fi

echo 'private toolchain activation: pass'
