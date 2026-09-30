#!/bin/bash
# The client entry points must not inherit another login's Homebrew paths.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
for file in "$ROOT/setup.sh" "$ROOT/verify.sh" "$ROOT/doctor.sh" \
            "$ROOT"/loops/* "$ROOT"/imessage/plists/*.plist.tmpl \
            "$ROOT"/templates/launchagents/*.plist.tmpl; do
  if /usr/bin/grep -Eq '/opt/homebrew|/usr/local/bin' "$file"; then
    echo "foreign package-manager path remains in ${file#"$ROOT"/}" >&2
    exit 1
  fi
done

for file in "$ROOT"/imessage/plists/*.plist.tmpl \
            "$ROOT"/templates/launchagents/*.plist.tmpl; do
  /usr/bin/plutil -lint "$file" >/dev/null
  /usr/bin/grep -q '/usr/bin:/bin' "$file" \
    || { echo "system PATH missing in ${file#"$ROOT"/}" >&2; exit 1; }
done
for file in "$ROOT"/imessage/plists/*.plist.tmpl \
            "$ROOT/templates/launchagents/cost-watch.plist.tmpl"; do
  /usr/bin/grep -q '<string>__PYTHON__</string>' "$file" \
    || { echo "absolute Python placeholder missing in ${file#"$ROOT"/}" >&2; exit 1; }
done

FIXTURE="$(/usr/bin/mktemp -d /tmp/wb-client-path-test.XXXXXX)"
trap '/bin/rm -R "$FIXTURE"' EXIT
/bin/mkdir "$FIXTURE/fake-bin"
cat > "$FIXTURE/fake-bin/python3" <<'SH'
#!/bin/sh
: > "$WB_TEST_SENTINEL"
SH
cat > "$FIXTURE/fake-bin/tmux" <<'SH'
#!/bin/sh
: > "$WB_TEST_SENTINEL"
SH
/bin/chmod 700 "$FIXTURE/fake-bin/python3" "$FIXTURE/fake-bin/tmux"
if HOME="$FIXTURE" PATH="$FIXTURE/fake-bin:/usr/bin:/bin" \
   WB_TEST_SENTINEL="$FIXTURE/foreign-ran" /bin/bash "$ROOT/setup.sh" --help \
   >/dev/null 2>&1; then
  echo 'setup.sh accepted an unverified Python' >&2
  exit 1
fi
if HOME="$FIXTURE" PATH="$FIXTURE/fake-bin:/usr/bin:/bin" \
   WB_TEST_SENTINEL="$FIXTURE/foreign-ran" /bin/bash "$ROOT/loops/tmux-boot" \
   >/dev/null 2>&1; then
  echo 'tmux-boot accepted an unverified tmux' >&2
  exit 1
fi
[ ! -e "$FIXTURE/foreign-ran" ] \
  || { echo 'a fake PATH binary ran before toolchain verification' >&2; exit 1; }

TC="$FIXTURE/.wideband/toolchain"
VERSION=0.7.2-client-test
/bin/mkdir -m 700 "$FIXTURE/.wideband" "$TC" "$TC/versions" \
  "$TC/versions/$VERSION" "$TC/versions/$VERSION/bin"
for tool in python3 tmux imsg node npm ttyd; do
  printf '#!/bin/sh\nexit 0\n' > "$TC/versions/$VERSION/bin/$tool"
  /bin/chmod 700 "$TC/versions/$VERSION/bin/$tool"
  /usr/bin/shasum -a 256 "$TC/versions/$VERSION/bin/$tool" \
    | /usr/bin/awk -v name="bin/$tool" '{print $1 "  " name}' \
    >> "$TC/versions/$VERSION/manifest.sha256"
done
/bin/chmod 600 "$TC/versions/$VERSION/manifest.sha256"
printf '%s\n' "$VERSION" > "$TC/active"
/bin/chmod 600 "$TC/active"
HOME="$FIXTURE" PATH="$FIXTURE/fake-bin:/usr/bin:/bin" \
  WB_TEST_SENTINEL="$FIXTURE/foreign-ran" /bin/bash "$ROOT/verify.sh" --quick --json \
  > "$FIXTURE/verification.json"
/usr/bin/python3 - "$FIXTURE/verification.json" <<'PY'
import json, sys
report = json.load(open(sys.argv[1], encoding="utf-8"))
assert report["summary"]["failed"] == 0, report["checks"]
assert {"python3", "tmux", "node", "npm", "ttyd"} <= {
    item["message"].split()[-1] for item in report["checks"]
    if item["status"] == "pass" and item["id"] == "P3-CLI"
}
assert any(item["id"] == "P6-IMSG" and item["status"] == "pass"
           for item in report["checks"])
assert any(item["id"] == "P4-TSSERVE" and item["status"] == "skip"
           for item in report["checks"])
PY
[ ! -e "$FIXTURE/foreign-ran" ]

echo 'client legacy paths: pass'
