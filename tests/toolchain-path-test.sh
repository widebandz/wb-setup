#!/bin/bash
# Exercise private toolchain selection without touching a live prefix.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FIXTURE="$(/usr/bin/mktemp -d /tmp/wb-toolchain-test.XXXXXX)"
trap '/bin/rm -rf "$FIXTURE"' EXIT
VERSION=0.7.2-test
TC="$FIXTURE/.wideband/toolchain"
/bin/mkdir -m 700 "$FIXTURE/.wideband" "$TC" "$TC/versions" \
  "$TC/versions/$VERSION" "$TC/versions/$VERSION/bin"

for tool in python3 tmux imsg node; do
  printf '#!/bin/sh\nexit 0\n' > "$TC/versions/$VERSION/bin/$tool"
  /bin/chmod 700 "$TC/versions/$VERSION/bin/$tool"
  /usr/bin/shasum -a 256 "$TC/versions/$VERSION/bin/$tool" \
    | /usr/bin/awk -v name="bin/$tool" '{print $1 "  " name}' \
    >> "$TC/versions/$VERSION/manifest.sha256"
done
/bin/mkdir -m 700 "$TC/versions/$VERSION/lib"
printf 'private runtime resource\n' > "$TC/versions/$VERSION/lib/resource.dat"
/bin/chmod 600 "$TC/versions/$VERSION/lib/resource.dat"
/usr/bin/shasum -a 256 "$TC/versions/$VERSION/lib/resource.dat" \
  | /usr/bin/awk '{print $1 "  lib/resource.dat"}' \
  >> "$TC/versions/$VERSION/manifest.sha256"
/bin/chmod 600 "$TC/versions/$VERSION/manifest.sha256"
printf '%s\n' "$VERSION" > "$TC/active"
/bin/chmod 600 "$TC/active"

resolved="$(HOME="$FIXTURE" WB_TC_REQUIRE_PRIVATE=1 "$ROOT/lib/toolchain-path" python3)"
[ "$resolved" = "$TC/versions/$VERSION/bin/python3" ]
resolved="$(HOME="$FIXTURE" WB_TC_REQUIRE_PRIVATE=1 "$ROOT/lib/toolchain-path" node)"
[ "$resolved" = "$TC/versions/$VERSION/bin/node" ]
if HOME="$FIXTURE" WB_TC_REQUIRE_PRIVATE=1 "$ROOT/lib/toolchain-path" brew >/dev/null 2>&1; then
  echo 'resolver accepted an unlisted package manager' >&2
  exit 1
fi

printf '# altered\n' >> "$TC/versions/$VERSION/bin/python3"
if HOME="$FIXTURE" WB_TC_REQUIRE_PRIVATE=1 "$ROOT/lib/toolchain-path" python3 >/dev/null 2>&1; then
  echo 'resolver accepted a changed core executable' >&2
  exit 1
fi
printf '#!/bin/sh\nexit 0\n' > "$TC/versions/$VERSION/bin/python3"
/bin/chmod 700 "$TC/versions/$VERSION/bin/python3"

printf '# altered\n' >> "$TC/versions/$VERSION/lib/resource.dat"
if HOME="$FIXTURE" WB_TC_REQUIRE_PRIVATE=1 "$ROOT/lib/toolchain-path" python3 >/dev/null 2>&1; then
  echo 'resolver accepted a changed runtime resource' >&2
  exit 1
fi
printf 'private runtime resource\n' > "$TC/versions/$VERSION/lib/resource.dat"
/bin/chmod 600 "$TC/versions/$VERSION/lib/resource.dat"

printf 'unlisted\n' > "$TC/versions/$VERSION/lib/extra.dat"
/bin/chmod 600 "$TC/versions/$VERSION/lib/extra.dat"
if HOME="$FIXTURE" WB_TC_REQUIRE_PRIVATE=1 "$ROOT/lib/toolchain-path" python3 >/dev/null 2>&1; then
  echo 'resolver accepted an unlisted payload file' >&2
  exit 1
fi
/bin/rm "$TC/versions/$VERSION/lib/extra.dat"

/bin/chmod 644 "$TC/active"
if HOME="$FIXTURE" WB_TC_REQUIRE_PRIVATE=1 "$ROOT/lib/toolchain-path" python3 >/dev/null 2>&1; then
  echo 'resolver accepted a public activation file' >&2
  exit 1
fi
/bin/chmod 600 "$TC/active"

/bin/mv "$TC/versions/$VERSION/bin/imsg" "$TC/versions/$VERSION/bin/imsg.real"
/bin/ln -s imsg.real "$TC/versions/$VERSION/bin/imsg"
if HOME="$FIXTURE" WB_TC_REQUIRE_PRIVATE=1 "$ROOT/lib/toolchain-path" python3 >/dev/null 2>&1; then
  echo 'resolver accepted a redirected core executable' >&2
  exit 1
fi

/bin/mkdir -m 700 "$FIXTURE/.wideband/setup"
printf '0.7.1-oldbuild\n' > "$FIXTURE/.wideband/setup/legacy-homebrew-allowed"
/bin/chmod 600 "$FIXTURE/.wideband/setup/legacy-homebrew-allowed"
if ! HOME="$FIXTURE" WB_LIB="$ROOT/lib/bootstrap-homebrew.sh" \
  WB_SENTINEL="$FIXTURE/legacy-probed" /bin/bash -c '
    . "$WB_LIB"
    wb_hb_clt_probe() { : > "$WB_SENTINEL"; WB_HB_CLT_READY=1; }
    wb_hb_prefix_probe() { WB_HB_PREFIX_STATE=healthy; WB_HB_ACL_ENTRY_COUNT=0; WB_HB_FLAGGED=""; }
    if wb_tc_resolve python3; then exit 1; fi
    [ ! -e "$WB_SENTINEL" ]
  '; then
  echo 'resolver bypassed an invalid private activation through legacy Homebrew' >&2
  exit 1
fi

echo 'private toolchain resolver: pass'
