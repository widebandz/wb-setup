#!/bin/bash
# selftest.sh — invariants of THIS REPO, not of the machine it built.
#
# verify.sh asks "is this Mac set up?". This asks "is the installer still
# honest?" — the properties that quietly rot as steps get added:
#
#   1. bootstrap.sh stays inside the bare-Mac tool budget
#   2. the vendored status line is byte-identical to a working one
#   3. no secrets, no operator identity, in a public repo
#   4. no loop hardcodes identity
#   5. every loop has a plist template
#   6. verify.sh IDs and TROUBLESHOOTING.md sections match, BOTH ways
#   7. doctor.sh diagnoses and never mutates
#   8. generated help is current
#   9. guided-installer manifest and JSON verification contract agree
#  10. source syntax parses
#  11. the agent-session-memory skill stays discoverable
#
# Exit code is the number of failures.
set -uo pipefail

# The release suite is also run from inside the sealed app bundle. Importing
# setup.py must never create __pycache__ beside the signed resources and thereby
# invalidate the artifact merely by testing it.
export PYTHONDONTWRITEBYTECODE=1

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PASS=0; FAIL=0

ok() { printf '  ✓ %s\n' "$*"; PASS=$((PASS+1)); }
no() { printf '  ✗ %s\n' "$*"; FAIL=$((FAIL+1)); }
head_() { printf '\n\033[1m%s\033[0m\n' "$*"; }

echo "▩ wb-setup selftest — $HERE"

# ── 1. bare-Mac tool budget ──────────────────────────────────────────────────
# Everything before the Homebrew step may use macOS system binaries but no
# package-managed executable. A bare macOS has no usable git or python3 — those
# paths can be CLT stubs that pop a dialog and block.
#
# Strings and comments are stripped first, and only COMMAND POSITION counts:
# `--no-brew` as a flag name and `command -v brew` as a guard are both fine,
# and a naive token grep flags them, which trains people to ignore this check.
head_ "1 · bare-Mac tool budget"
FORBIDDEN='git|python3|python|jq|node|npm|brew|gh|tmux|sqlite3|launchctl|tailscale|code'
hits="$(
  awk '/^# ── 3\. Homebrew/{exit} {print}' "$HERE/bootstrap.sh" \
  | sed -e "s/'[^']*'//g" -e 's/"[^"]*"//g' -e 's/#.*$//' \
  | grep -nE "(^|[;&|(]|\\\$\()[[:space:]]*($FORBIDDEN)[[:space:]]" \
  | grep -vE 'command[[:space:]]+-v'
)"
if [ -z "$hits" ]; then
  ok "no out-of-budget binary is invoked before Homebrew"
else
  no "out-of-budget invocations before Homebrew:"
  printf '      %s\n' "$hits"
fi

if bash - "$HERE/lib/bootstrap-homebrew.sh" <<'SH' >/dev/null 2>&1
set -u
. "$1"
WB_HB_CLT_SELECTED_EXISTS=0
WB_HB_CLT_DEFAULT_INSTALLED=0
WB_HB_CLT_SELECTED_WORKS=0
WB_HB_CLT_DEFAULT_WORKS=0
wb_hb_classify_clt
[ "$WB_HB_CLT_STATE" = missing ]
WB_HB_CLT_DEFAULT_INSTALLED=1
wb_hb_classify_clt
[ "$WB_HB_CLT_STATE" = incompatible ]
WB_HB_CLT_DEFAULT_WORKS=1
wb_hb_classify_clt
[ "$WB_HB_CLT_STATE" = installed_not_selected ]
WB_HB_CLT_SELECTED_EXISTS=1
WB_HB_CLT_SELECTED_WORKS=1
wb_hb_classify_clt
[ "$WB_HB_CLT_STATE" = ready ]
WB_HB_USER=clientuser
WB_HB_PREFIX_MARKER=1
WB_HB_PREFIX_OWNER=old-owner
WB_HB_PREFIX_WRITABLE=0
WB_HB_NONWRITABLE=/opt/homebrew
WB_HB_MISMATCH_COUNT=1
WB_HB_NONWRITABLE_DIR_COUNT=1
wb_hb_classify_prefix
[ "$WB_HB_PREFIX_STATE" = wrong_owner ]
WB_HB_PREFIX_OWNER=clientuser
WB_HB_MISMATCH_COUNT=0
wb_hb_classify_prefix
[ "$WB_HB_PREFIX_STATE" = not_writable ]
WB_HB_PREFIX_WRITABLE=1
WB_HB_NONWRITABLE=""
WB_HB_NONWRITABLE_DIR_COUNT=0
wb_hb_classify_prefix
[ "$WB_HB_PREFIX_STATE" = healthy ]
WB_HB_PREFIX_MARKER=0
wb_hb_classify_prefix
[ "$WB_HB_PREFIX_STATE" = unrecognized ]
WB_HB_ARCH=arm64
WB_HB_PREFIX=/opt/homebrew
WB_HB_PREFIX_MARKER=1
WB_HB_PREFIX_STATE=wrong_owner
WB_HB_MISMATCH_COUNT=1
WB_HB_IDENTITY_SAFE=1
WB_HB_ADMIN=1
WB_HB_CONSOLE_USER=clientuser
WB_HB_ACL_ENTRY_COUNT=1
WB_HB_FLAGGED=""
! wb_hb_repair_available
WB_HB_ACL_ENTRY_COUNT=0
WB_HB_FLAGGED=/opt/homebrew:uchg
! wb_hb_repair_available
SH
then
  ok "Homebrew guard distinguishes CLT and post-upgrade prefix states"
else
  no "Homebrew guard cannot classify post-upgrade CLT or prefix states"
fi

HB_FIXTURE="$(mktemp -d /tmp/wb-homebrew-selftest.XXXXXX)"
/bin/mkdir -p "$HB_FIXTURE/prefix/bin" "$HB_FIXTURE/prefix/Library/Homebrew"
printf '#!/bin/sh\nexit 0\n' > "$HB_FIXTURE/prefix/bin/brew"
: > "$HB_FIXTURE/prefix/Library/Homebrew/brew.sh"
/bin/chmod 755 "$HB_FIXTURE/prefix/bin/brew"
/bin/chmod 555 "$HB_FIXTURE/prefix"
if bash - "$HERE/lib/bootstrap-homebrew.sh" "$HB_FIXTURE" <<'SH' >/dev/null 2>&1
set -u
. "$1"
fixture="$2"
WB_HB_USER="$(id -un)"
WB_HB_UID="$(id -u)"
WB_HB_IDENTITY_SAFE=1
WB_HB_ARCH=arm64
WB_HB_ADMIN=1
WB_HB_CONSOLE_USER="$WB_HB_USER"
wb_hb_prefix_probe "$fixture/prefix"
[ "$WB_HB_PREFIX_STATE" = not_writable ]
! wb_hb_repair_available
chmod 755 "$fixture/prefix"
ln -s "$fixture/prefix" "$fixture/redirected-prefix"
wb_hb_prefix_probe "$fixture/redirected-prefix"
[ "$WB_HB_PREFIX_STATE" = unsafe_symlink ]
! wb_hb_repair_available
SH
then
  ok "Homebrew guard refuses nonstandard and symlinked repair targets"
else
  no "Homebrew guard accepted an unsafe repair target"
fi
/bin/chmod -R u+rwX "$HB_FIXTURE" 2>/dev/null || true
/usr/bin/find "$HB_FIXTURE" -depth -delete 2>/dev/null || true

if grep -q -- '--diagnose-homebrew' "$HERE/bootstrap.sh" \
   && grep -q 'needs_developer_tools' "$HERE/bootstrap.sh" \
   && grep -q 'needs_developer_tools_selection' "$HERE/bootstrap.sh" \
   && grep -q 'needs_developer_tools_update' "$HERE/bootstrap.sh" \
   && grep -q 'needs_homebrew_ownership' "$HERE/bootstrap.sh" \
   && grep -q '/usr/bin/find /opt/homebrew -xdev ! -uid' "$HERE/lib/bootstrap-homebrew.sh" \
   && grep -q '/usr/sbin/chown -h' "$HERE/lib/bootstrap-homebrew.sh" \
   && grep -q '/usr/bin/find /opt/homebrew -xdev -type d -uid' "$HERE/lib/bootstrap-homebrew.sh" \
   && grep -q 'WB_HB_ACL_ENTRY_COUNT' "$HERE/lib/bootstrap-homebrew.sh" \
   && grep -q 'WB_HB_FLAGGED' "$HERE/lib/bootstrap-homebrew.sh" \
   && ! grep -qE 'chown[[:space:]]+-R.*(/opt/homebrew|\$WB_HB_PREFIX)' "$HERE/bootstrap.sh" "$HERE/lib/bootstrap-homebrew.sh"; then
  ok "Homebrew recovery is diagnostic-first and never runs a broad recursive chown"
else
  no "Homebrew recovery can mutate an unverified or overly broad target"
fi

# ── 2. status line fidelity ──────────────────────────────────────────────────
# The argument for shipping this as a file rather than regenerating it from a
# prompt is that it is solved. That argument only holds if it stays identical.
head_ "2 · status line"
SL="$HERE/dotfiles/statusline-command.sh"
if [ ! -f "$SL" ]; then
  no "dotfiles/statusline-command.sh missing"
else
  grep -q "\$'" "$SL" \
    && ok "colors use \$'...' — real ESC bytes, not literal backslashes" \
    || no "colors are not \$'...' — they will print literally"
  grep -q 'context_window' "$SL" \
    && ok "reads context_window (the whole reason for the custom line)" \
    || no "no context_window segment"
  grep -q 'jq' "$SL" \
    && ok "parses with jq (declared in the Brewfile)" \
    || no "does not use jq — check the Brewfile still needs it"
fi

# ── 3. nothing identity-shaped in a public repo ──────────────────────────────
head_ "3 · public-repo hygiene"
LEAK='\+1[0-9]{10}|[0-9]{3}-[0-9]{3}-[0-9]{4}|sk-[A-Za-z0-9]{20}|ghp_[A-Za-z0-9]{20}|-----BEGIN [A-Z ]*PRIVATE KEY'
found="$(grep -rInE "$LEAK" "$HERE" \
          --exclude-dir=.git --exclude='selftest.sh' --exclude='*.example' 2>/dev/null \
        | grep -viE '\+15551234567|555-|example')"
[ -z "$found" ] && ok "no phone numbers, keys or tokens" \
                || { no "possible secret or identity:"; printf '      %s\n' "$found"; }

found="$(grep -rIlniE 'brainwave|tailacfa70' "$HERE" \
          --exclude-dir=.git --exclude='selftest.sh' 2>/dev/null)"
[ -z "$found" ] && ok "no operator hostnames" \
                || { no "machine-specific identity leaked into:"; printf '      %s\n' "$found"; }

if grep -q 'chmod 600 "$VARS"' "$HERE/bootstrap.sh" \
   && grep -q 'chmod 600 "$VARS"' "$HERE/install.sh"; then
  ok "operator identity is forced to mode 0600"
else
  no "~/.sop-vars is not forced private by bootstrap and install"
fi

# ── 4 + 5. the loops ─────────────────────────────────────────────────────────
# The invariant is "no loop hardcodes identity", NOT "every loop reads
# ~/.sop-vars". A loop with no identity in it at all — tmux-boot, healthcheck —
# satisfies the intent more completely than one that reads the file. Testing for
# the file rather than for the property failed those two and was wrong to.
head_ "4 · no loop hardcodes identity"
IDENT='\+1[0-9]{10}|/Users/[a-z]|[a-z0-9-]+\.ts\.net|@[a-z0-9-]+\.(com|ai|io)'
NEEDS='OPERATOR_PHONE|GH_USER|GIT_EMAIL|WORK_REPO|GRAPH_PACK|\$ORG|\$BRAND'
for f in "$HERE"/loops/*; do
  [ -f "$f" ] || continue
  b="$(basename "$f")"
  lit="$(sed -e "s/'[^']*'//g" -e 's/#.*$//' "$f" | grep -nEo "$IDENT" | head -3)"
  if [ -n "$lit" ]; then
    no "$b contains an identity literal: $(printf '%s' "$lit" | tr '\n' ' ')"
  elif grep -qE "$NEEDS" "$f"; then
    grep -q 'sop-vars' "$f" \
      && ok "$b needs identity and reads ~/.sop-vars" \
      || no "$b references identity vars but never reads ~/.sop-vars"
  else
    ok "$b is identity-free"
  fi
done

head_ "5 · every loop is schedulable"
for f in "$HERE"/loops/*; do
  [ -f "$f" ] || continue
  b="$(basename "$f")"
  [ -f "$HERE/templates/launchagents/$b.plist.tmpl" ] \
    && ok "$b has a plist template" \
    || no "$b has no plist template — it would never run"
done

# ── 6. the guide cannot drift ────────────────────────────────────────────────
# verify.sh emits a stable ID per failure; TROUBLESHOOTING.md has a section per
# ID. Checked BOTH ways on purpose. A one-way check (every ID has a section)
# still lets the guide accumulate sections for checks that no longer exist,
# which is the quieter half of drift: nobody notices documentation for a
# failure that can no longer happen, and it slowly teaches the wrong thing.
head_ "6 · verify IDs ↔ guide sections"
if [ ! -f "$HERE/TROUBLESHOOTING.md" ]; then
  no "TROUBLESHOOTING.md missing"
else
  # IDs raised by verify.sh: the first argument to every no() call.
  ids="$(grep -oE '(^|\s)no [A-Z0-9]+-[A-Z]+' "$HERE/verify.sh" \
         | awk '{print $NF}' | sort -u)"
  # IDs documented in the guide: `## P0-FDA — …`
  docs="$(grep -oE '^## [A-Z0-9]+-[A-Z]+' "$HERE/TROUBLESHOOTING.md" \
         | awk '{print $2}' | sort -u)"
  # A section may cover two related checks (P7-CONF / P7-TPM share one), so
  # also accept IDs named in a combined heading.
  docs="$(printf '%s\n%s\n' "$docs" \
          "$(grep -oE '^## ([A-Z0-9]+-[A-Z]+ / )+[A-Z0-9]+-[A-Z]+' "$HERE/TROUBLESHOOTING.md" \
             | sed 's/^## //;s| / |\n|g')" | grep . | sort -u)"

  undocumented="$(comm -23 <(printf '%s\n' "$ids") <(printf '%s\n' "$docs"))"
  orphaned="$(comm -13 <(printf '%s\n' "$ids") <(printf '%s\n' "$docs"))"

  [ -z "$undocumented" ] \
    && ok "every verify.sh ID has a guide section ($(printf '%s' "$ids" | grep -c .) IDs)" \
    || { no "raised by verify.sh, absent from the guide:"; printf '      %s\n' $undocumented; }

  [ -z "$orphaned" ] \
    && ok "no guide section documents a check that no longer exists" \
    || { no "documented but never raised:"; printf '      %s\n' $orphaned; }
fi

# ── 7. doctor.sh diagnoses, never fixes ──────────────────────────────────────
# A diagnostic that repairs as it runs destroys the evidence of what was
# broken. Enforced statically rather than by convention.
head_ "7 · doctor.sh is read-only"
if [ ! -f "$HERE/doctor.sh" ]; then
  no "doctor.sh missing"
else
  mut="$(sed -e "s/'[^']*'//g" -e 's/#.*$//' "$HERE/doctor.sh" \
        | grep -nE '(^|[;&|(]|\$\()[[:space:]]*(cp|mv|rm|install|launchctl (bootstrap|bootout|load|unload)|brew install|npm install|git clone|chmod|mkdir)[[:space:]]')"
  [ -z "$mut" ] && ok "no mutating command in doctor.sh" \
                || { no "doctor.sh mutates:"; printf '      %s\n' "$mut"; }
fi

# ── 8. help.html is generated, not hand-edited ───────────────────────────────
# The client page embeds the guide, which would be a fourth copy of the failure
# knowledge if it were maintained by hand. Regenerate to a temp file and compare:
# a stale help.html fails here rather than quietly shipping advice that no
# longer matches TROUBLESHOOTING.md.
head_ "8 · help.html is current"
if [ ! -f "$HERE/help.html" ]; then
  no "help.html missing — run: python3 render-help.py"
elif ! command -v python3 >/dev/null 2>&1; then
  ok "help.html present (no python3 to re-render and compare)"
else
  tmp="$(mktemp)"
  if python3 "$HERE/render-help.py" "$tmp" >/dev/null 2>&1; then
    cmp -s "$tmp" "$HERE/help.html" \
      && ok "help.html matches TROUBLESHOOTING.md" \
      || no "help.html is STALE — run: python3 render-help.py"
  else
    no "render-help.py failed to run"
  fi
  rm -f "$tmp"
fi

# ── 9. guided installer ──────────────────────────────────────────────────────
head_ "9 · guided installer"
MANIFEST="$HERE/installer/manifest.json"
if [ ! -f "$MANIFEST" ]; then
  no "installer/manifest.json missing"
elif ! command -v python3 >/dev/null 2>&1; then
  no "python3 missing — cannot validate the installer manifest"
else
  if python3 - "$MANIFEST" <<'PY' >/dev/null 2>&1
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
assert data["schema_version"] == 1
assert len(data["stages"]) == 6
steps = [step for stage in data["stages"] for step in stage["steps"]]
ids = [step["id"] for step in steps]
assert len(ids) == len(set(ids))
assert all(step.get("actor") in {"operator", "client", "machine", "agent"} for step in steps)
assert all(step.get("type") in {"automatic", "guided", "interview", "verification", "onboarding"} for step in steps)
clients = [step for step in steps if step.get("actor") == "client"]
assert clients
assert all(step.get("client_phase") in {"now", "handoff", "later"} for step in clients)
assert all(step.get("client_guide", {}).get("intro") for step in clients)
assert all(step.get("client_guide", {}).get("instructions") for step in clients)
assert all(isinstance(step.get("client_priority", 1000), int) for step in clients)
frontloaded = sorted(enumerate(clients), key=lambda pair: (pair[1].get("client_priority", 1000), pair[0]))
assert [step["id"] for _, step in frontloaded[:6]] == [
    "identify.name-your-system",
    "prepare.create-accounts",
    "prepare.complete-setup-assistant",
    "connect.messages",
    "connect.full-disk-access",
    "identify.authenticate-agent",
]
now = [step for _, step in frontloaded if step.get("client_phase") == "now"]
order = [step["id"] for step in now]
assert order.index("connect.imessage-bind") < order.index("connect.background-items") < order.index("prove.messaging")
background = next(step for step in now if step["id"] == "connect.background-items")
assert "P6-IMSGSERVICES" in background["checks"]
bind = next(step for step in now if step["id"] == "connect.imessage-bind")
assert "open_login_items" in [item["action"] for item in bind["client_guide"]["actions"]]
PY
  then
    ok "manifest parses and every client step has popup guidance"
  else
    no "manifest schema, IDs, or client-guide contract is invalid"
  fi

  if python3 - "$MANIFEST" "$HERE" <<'PY' >/dev/null 2>&1
import json, pathlib, sys
manifest = json.load(open(sys.argv[1], encoding="utf-8"))
root = pathlib.Path(sys.argv[2])
release = manifest["release"]
memory = (root / "BUILD-MEMORY.md").read_text(encoding="utf-8")
changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
readme = (root / "README.md").read_text(encoding="utf-8")
agents = (root / "AGENTS.md").read_text(encoding="utf-8")
assert f"- Release: **{release}**." in memory
assert "## Runtime architecture" in memory
assert "## Security and privacy invariants" in memory
assert "## Release and test procedure" in memory
assert f"## {release} —" in changelog
assert f"**Current release:** {release}." in readme
assert "BUILD-MEMORY.md" in agents
PY
  then
    ok "release documentation and durable agent memory match the manifest"
  else
    no "release documentation or durable agent memory is missing or stale"
  fi

  if python3 - "$HERE/setup.py" <<'PY' >/dev/null 2>&1
import importlib.util, pathlib, sys, tempfile
source = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("wb_setup_app", source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
with tempfile.TemporaryDirectory() as directory:
    root = pathlib.Path(directory)
    store = module.StateStore(root / "state")
    assert store.path.stat().st_mode & 0o777 == 0o600
    private = root / "private.md"
    module.write_private(private, "complete\n")
    assert private.read_text(encoding="utf-8") == "complete\n"
    assert private.stat().st_mode & 0o777 == 0o600
    module.write_private(store.directory / "bootstrap-status", "needs_admin_password\n")
    original = module.bootstrap_is_ready
    module.bootstrap_is_ready = lambda: False
    assert module.bootstrap_status(store.directory) == "needs_admin_password"
    module.write_private(store.directory / "bootstrap-status", "needs_developer_tools\n")
    assert module.bootstrap_status(store.directory) == "needs_developer_tools"
    module.write_private(store.directory / "bootstrap-status", "needs_developer_tools_selection\n")
    assert module.bootstrap_status(store.directory) == "needs_developer_tools_selection"
    module.write_private(store.directory / "bootstrap-status", "needs_developer_tools_update\n")
    assert module.bootstrap_status(store.directory) == "needs_developer_tools_update"
    module.write_private(store.directory / "bootstrap-status", "needs_homebrew_ownership\n")
    assert module.bootstrap_status(store.directory) == "needs_homebrew_ownership"
    module.bootstrap_is_ready = original
PY
  then
    ok "installer state and generated private artifacts use mode 0600"
  else
    no "installer private-state permission contract failed"
  fi

  if python3 - "$HERE/setup.py" <<'PY' >/dev/null 2>&1
import importlib.util, json, pathlib, sys, tempfile, threading, urllib.error, urllib.request
source = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("wb_setup_loopback", source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
with tempfile.TemporaryDirectory() as directory:
    store = module.StateStore(pathlib.Path(directory) / "state")
    app = module.SetupApp(store, "test-build")
    module.Handler.app = app
    server = module.LoopbackHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert server.server_address[0] == "127.0.0.1"
        assert server.server_name == "localhost"
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            urllib.request.urlopen(base + "/api/health", timeout=1)
            raise AssertionError("health endpoint accepted a missing token")
        except urllib.error.HTTPError as error:
            assert error.code == 401
        headers = {"X-Wideband-Token": app.token}
        health = json.load(urllib.request.urlopen(urllib.request.Request(base + "/api/health", headers=headers), timeout=1))
        assert health["status"] == "ok"
        assert health["pid"] > 0
        assert health["release"] == module.MANIFEST["release"]
        assert health["build_id"] == "test-build"
        try:
            urllib.request.urlopen(base + "/api/phone-link", timeout=1)
            raise AssertionError("phone link endpoint accepted a missing token")
        except urllib.error.HTTPError as error:
            assert error.code == 401
        phone_link = json.load(urllib.request.urlopen(
            urllib.request.Request(base + "/api/phone-link", headers=headers), timeout=1
        ))
        assert phone_link["status"] == "waiting" and "url" not in phone_link
        state = json.load(urllib.request.urlopen(urllib.request.Request(base + "/api/state", headers=headers), timeout=1))
        assert state["connection"] == {
            "host": "127.0.0.1",
            "port": server.server_address[1],
            "release": module.MANIFEST["release"],
            "build_id": "test-build",
            "started_at": app.started_at,
        }
        def fake_live_checks():
            report = {
                "generated_at": module.now(),
                "checks": [{"id": "P0-AX", "status": "pass", "message": "Accessibility live"}],
            }
            store.update(lambda data: data.update({"live_checks": report}))
            return report
        app.refresh_live_checks = fake_live_checks
        request = urllib.request.Request(
            base + "/api/live-checks", data=b"{}", method="POST",
            headers={**headers, "Content-Type": "application/json"},
        )
        focused = json.load(urllib.request.urlopen(request, timeout=1))
        assert focused["verification_rollup"]["P0-AX"] == "pass"
        assert focused["verification"]["summary"] == {"passed": 1, "failed": 0, "skipped": 0}
        shutdown = urllib.request.Request(
            base + "/api/shutdown", data=b"{}", method="POST",
            headers={**headers, "Content-Type": "application/json"},
        )
        assert json.load(urllib.request.urlopen(shutdown, timeout=1))["status"] == "stopping"
        thread.join(timeout=2)
        assert not thread.is_alive()
    finally:
        server.server_close()
PY
  then
    ok "authenticated loopback API reports real state and merges focused live checks"
  else
    no "installer loopback status contract failed"
  fi

  if python3 - "$HERE/setup.py" <<'PY' >/dev/null 2>&1
import importlib.util, json, pathlib, subprocess, sys, tempfile, time
source = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("wb_setup_lifecycle", source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
with tempfile.TemporaryDirectory() as directory:
    state = pathlib.Path(directory) / "state"
    state.mkdir()
    (state / "payload-build").write_text("old-build\n", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, str(source), "--state-dir", str(state), "--port", "0", "--no-open"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        connection_path = state / "connection.json"
        for _ in range(100):
            if connection_path.is_file():
                break
            assert process.poll() is None
            time.sleep(0.05)
        assert connection_path.is_file()
        connection = json.loads(connection_path.read_text(encoding="utf-8"))
        assert connection["release"] == module.MANIFEST["release"]
        assert connection["build_id"] == "old-build"
        assert module.live_connection(state, module.MANIFEST["release"], "old-build")
        assert module.live_connection(state, module.MANIFEST["release"], "new-build") is None
        process.wait(timeout=3)
        assert not connection_path.exists()
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=3)
PY
  then
    ok "relaunch keeps a matching server and safely replaces a stale build"
  else
    no "stale local-server replacement contract failed"
  fi

  manifest_checks="$(python3 - "$MANIFEST" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
print("\n".join(sorted({check for stage in data["stages"] for step in stage["steps"] for check in step.get("checks", [])})))
PY
)"
  live_checks="$(grep -oE '(^|\s)no [A-Z0-9]+-[A-Z]+' "$HERE/verify.sh" | awk '{print $NF}' | sort -u)"
  unknown_checks="$(comm -23 <(printf '%s\n' "$manifest_checks") <(printf '%s\n' "$live_checks"))"
  [ -z "$unknown_checks" ] \
    && ok "every manifest check ID is raised by verify.sh" \
    || { no "manifest references checks verify.sh never raises:"; printf '      %s\n' $unknown_checks; }

  manifest_actions="$(python3 - "$MANIFEST" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
actions = {step["action"] for stage in data["stages"] for step in stage["steps"] if step.get("action")}
actions |= {
    item["action"]
    for stage in data["stages"]
    for step in stage["steps"]
    for item in step.get("client_guide", {}).get("actions", [])
}
print("\n".join(sorted(actions)))
PY
)"
  allowed_actions="$(printf '%s\n' \
    generate_build_record open_accessibility open_anthropic open_apple_id \
    open_claude_auth open_full_disk_access open_github open_interview open_login_items \
    open_mail open_messages open_remote_login open_screen_recording open_screen_sharing open_supabase \
    open_tailscale_account open_tailscale_download open_vercel request_accessibility \
    request_full_disk_access request_messages_automation request_screen_recording reveal_wideband_agent \
    run_doctor run_install run_imessage_install run_imessage_init run_imessage_bind \
    run_first_goal_apply run_first_goal_check run_phone_install run_selftest run_verify_full run_verify_quick \
    run_verify_imessage | tr ' ' '\n' | sort -u)"
  unknown_actions="$(comm -23 <(printf '%s\n' "$manifest_actions") <(printf '%s\n' "$allowed_actions"))"
  [ -z "$unknown_actions" ] \
    && ok "every manifest action is allowlisted" \
    || { no "manifest references actions the runner does not allow:"; printf '      %s\n' $unknown_actions; }

  if python3 - "$HERE/setup.py" <<'PY' >/dev/null 2>&1
import importlib.util, pathlib, sys
spec = importlib.util.spec_from_file_location("wb_setup_frozen_commands", pathlib.Path(sys.argv[1]))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
commands = module.JobRunner.COMMANDS
python = "/opt/homebrew/bin/python3"
assert commands["run_imessage_init"][0] == python
assert commands["run_imessage_bind"][:3] == ["/usr/bin/open", "-W", "-n"]
assert commands["run_imessage_bind"][3].endswith("/Applications/Wideband Agent.app")
assert commands["run_imessage_bind"][4:7] == ["--args", "run-background-task", python]
assert commands["run_first_goal_apply"][0] == python
assert commands["run_first_goal_check"][0] == python
assert all(sys.executable not in commands[action] for action in (
    "run_imessage_init", "run_imessage_bind", "run_first_goal_apply", "run_first_goal_check"
))
PY
  then
    ok "packaged actions use proven Homebrew Python, not the frozen setup engine"
  else
    no "a packaged action may invoke the frozen setup engine as Python"
  fi

  if python3 - "$HERE/bootstrap.sh" <<'PY' >/dev/null 2>&1
import pathlib, sys
text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
client = text.split("collect_client_identity() {", 1)[1].split("\nask()", 1)[0]
assert 'native_ask OPERATOR_PHONE' in client
assert 'native_ask GH_USER' not in client and 'native_ask WORK_REPO' not in client
assert 'collect_client_identity' in text.split('if [ "$CLIENT_MODE" = "1" ] && [ -x /usr/bin/osascript ]; then', 1)[1]
assert 'BREWFILE="$ROOT/Brewfile.quick"' in text
handoff = text.split('# ── handoff', 1)[1]
client_ready = handoff.split('elif [ "$CLIENT_MODE" = "1" ]', 1)[1].split('bootstrap_status ready', 1)[0]
assert all(f'/opt/homebrew/bin/{tool}' in client_ready for tool in ('brew', 'python3', 'tmux', 'imsg'))
assert '/opt/homebrew/bin/git' not in client_ready and '/opt/homebrew/bin/jq' not in client_ready
preflight = text.split('# ── preflight', 1)[1].split('case "$ROOT"', 1)[0]
assert 'bootstrap_status unsupported_macos' in preflight
PY
  then
    ok "client bootstrap asks only owner phone and selects Brewfile.quick"
  else
    no "client bootstrap regressed to optional identity prompts or full Brewfile"
  fi

  if python3 "$HERE/tests/bootstrap-handoff-test.py" >/dev/null 2>&1; then
    ok "embedded bootstrap handoff keeps the native guide in front"
  else
    no "embedded bootstrap handoff may open a duplicate browser guide"
  fi

  if [ -s "$HERE/installer/wideband-mark.png" ] \
     && [ -s "$HERE/installer/fonts/inter-latin.woff2" ] \
     && [ -s "$HERE/installer/fonts/orbitron-latin.woff2" ] \
     && grep -q 'wideband-mark.png' "$HERE/installer/index.html"; then
    ok "client guide uses the canonical Wideband mark and local brand fonts"
  else
    no "Wideband brand assets are missing from the client guide"
  fi

  if python3 - "$MANIFEST" <<'PY' >/dev/null 2>&1
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
steps = {
    step["id"]: step
    for stage in data["stages"]
    for step in stage["steps"]
}
instructions = " ".join(steps["connect.remote-login"]["client_guide"]["instructions"])
assert "Turn off Allow full disk access for remote users" in instructions
assert "Only these users" in instructions
assert "Remove the Administrators group" in instructions
PY
  then
    ok "Remote Login guide enforces least-privilege access"
  else
    no "Remote Login guide is missing least-privilege instructions"
  fi

  if python3 - "$MANIFEST" <<'PY' >/dev/null 2>&1
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
steps = {
    step["id"]: step
    for stage in data["stages"]
    for step in stage["steps"]
}
guide = steps["connect.automation-dialog"]["client_guide"]
assert [item["action"] for item in guide["actions"]] == [
    "open_messages", "request_messages_automation"
]
assert all(item.get("message") for item in guide["actions"])
assert "does not read or send any message or conversation content" in guide["privacy"]
PY
  then
    ok "Messages consent guide handles app first-run before the TCC prompt"
  else
    no "Messages consent guide is missing its two-stage handoff"
  fi

  if python3 - "$MANIFEST" "$HERE/agent/WidebandAgent.swift" <<'PY' >/dev/null 2>&1
import json, pathlib, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
source = pathlib.Path(sys.argv[2]).read_text(encoding="utf-8")
steps = {
    step["id"]: step
    for stage in data["stages"]
    for step in stage["steps"]
}
assert [item["action"] for item in steps["connect.accessibility"]["client_guide"]["actions"]] == [
    "request_accessibility", "open_accessibility"
]
assert [item["action"] for item in steps["connect.screen-recording"]["client_guide"]["actions"]] == [
    "request_screen_recording", "open_screen_recording"
]
assert "permissionRegistrationGracePeriod: TimeInterval = 5" in source
accessibility = source.split("private func requestAccessibility()", 1)[1].split("private func screenCaptureGranted()", 1)[0]
screen_capture = source.split("private func requestScreenCapture()", 1)[1].split("private func fullDiskGranted()", 1)[0]
assert "openSettings(" not in accessibility
assert "openSettings(" not in screen_capture
PY
  then
    ok "permission requests keep the branded macOS alert visible and provide settings fallbacks"
  else
    no "permission request can be hidden by System Settings or lacks a recovery button"
  fi

  if python3 - "$MANIFEST" <<'PY' >/dev/null 2>&1
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
steps = [step for stage in data["stages"] for step in stage["steps"]]
frontloaded = sorted(
    (step for step in steps if step.get("actor") == "client"),
    key=lambda step: (step.get("client_priority", 1000), steps.index(step)),
)[:6]
assert all(step["client_guide"].get("purpose") for step in frontloaded)
assert all(step["client_guide"].get("success") for step in frontloaded)
PY
  then
    ok "frontloaded permissions explain purpose and an observable success state"
  else
    no "a frontloaded permission is missing purpose or success coaching"
  fi

  if grep -q 'id="readiness-grid"' "$HERE/installer/index.html" \
     && grep -q 'id="save-state"' "$HERE/installer/index.html" \
     && grep -q 'id="support-dialog"' "$HERE/installer/index.html" \
     && grep -q 'id="completion-record"' "$HERE/installer/index.html" \
     && grep -q 'responsibility-strip' "$HERE/installer/index.html" \
     && grep -q 'function renderReadiness' "$HERE/installer/app.js" \
     && grep -q 'function runSupportJob' "$HERE/installer/app.js" \
     && grep -q 'function monitorGuideStep' "$HERE/installer/app.js" \
     && grep -q '/api/live-checks' "$HERE/installer/app.js"; then
    ok "client UI exposes ownership, live permission guidance, completion, repair, and support"
  else
    no "client readiness or recovery UI is incomplete"
  fi

  if grep -q 'id="connection-alert"' "$HERE/installer/index.html" \
     && grep -q 'id="status-dialog"' "$HERE/installer/index.html" \
     && grep -q 'Machine verified' "$HERE/installer/index.html" \
     && grep -q 'function evidenceLabel' "$HERE/installer/app.js" \
     && grep -q 'function pollState' "$HERE/installer/app.js" \
     && grep -q 'needs_admin_password' "$HERE/installer/app.js" \
     && grep -q 'needs_developer_tools_selection' "$HERE/installer/app.js" \
     && grep -q 'needs_developer_tools_update' "$HERE/installer/app.js" \
     && grep -q 'setView(viewMode, false)' "$HERE/installer/app.js"; then
    ok "client UI distinguishes proof sources, polls live state, and explains reconnection"
  else
    no "client connection or honest-status guidance is incomplete"
  fi

  if grep -Fq 'to count accounts' "$HERE/agent/WidebandAgent.swift" \
     && ! grep -Fq 'to get name' "$HERE/agent/WidebandAgent.swift"; then
    ok "Messages consent uses a real harmless Apple Event"
  else
    no "Messages consent can be falsely satisfied without an Apple Event"
  fi

  background_templates_ok=0
  if python3 - "$HERE" <<'PY' >/dev/null 2>&1
import glob, plistlib, sys
root = sys.argv[1]
paths = glob.glob(root + "/templates/launchagents/*.plist.tmpl")
assert paths
for path in paths:
    with open(path, "rb") as handle:
        arguments = plistlib.load(handle)["ProgramArguments"]
    assert arguments[:2] == ["__AGENT_EXECUTABLE__", "run-background-task"]
PY
  then
    background_templates_ok=1
  fi
  if [ "$background_templates_ok" = 1 ] \
     && grep -q '__AGENT_EXECUTABLE__.*agent_e' "$HERE/install.sh" \
     && grep -q 'run-background-task' "$HERE/agent/WidebandAgent.swift"; then
    ok "all standing jobs use the branded Wideband Agent entry point"
  else
    no "a standing job can still appear as a generic runtime"
  fi

  if /usr/bin/plutil -lint "$HERE/agent/Info.plist" "$HERE/agent/entitlements.plist" >/dev/null 2>&1 \
     && grep -q 'WidebandAgent.swift' "$HERE/packaging/build-app.sh" \
     && grep -q 'Wideband Agent.app' "$HERE/packaging/app-launcher"; then
    if command -v xcrun >/dev/null 2>&1; then
      xcrun swiftc -parse-as-library -typecheck -target arm64-apple-macos13.0 \
        -framework AppKit -framework ApplicationServices -framework Carbon -framework CoreGraphics \
        "$HERE/agent/WidebandAgent.swift" >/dev/null 2>&1 \
        && ok "Wideband Agent permission helper compiles" \
        || no "Wideband Agent permission helper does not compile"
    else
      ok "Wideband Agent permission helper is packaged (compile deferred)"
    fi
  else
    no "Wideband Agent permission helper packaging is incomplete"
  fi

  if [ -f "$HERE/packaging/WidebandSetupLauncher.swift" ] \
     && [ -f "$HERE/packaging/UpdateFeed.swift" ] \
     && grep -q 'WidebandSetupLauncher.swift' "$HERE/packaging/build-app.sh" \
     && grep -q 'UpdateFeed.swift' "$HERE/packaging/build-app.sh" \
     && grep -q 'RESOURCES/app-launcher' "$HERE/packaging/build-app.sh" \
     && grep -q 'wb-setup-engine' "$HERE/packaging/build-app.sh" \
     && ! grep -q 'codesign --force --options runtime --sign -.*wb-setup-engine' "$HERE/packaging/build-app.sh" \
     && grep -q 'engine unexpectedly enables hardened runtime library validation' "$HERE/packaging/build-app.sh" \
     && grep -q 'launch_terminal' "$HERE/packaging/app-launcher" \
     && grep -q 'launch_background' "$HERE/packaging/app-launcher" \
     && grep -q 'WB_SETUP_NATIVE_PID' "$HERE/packaging/app-launcher" \
     && grep -q 'WKWebView' "$HERE/packaging/WidebandSetupLauncher.swift" \
     && grep -q 'expectedBuildID' "$HERE/packaging/WidebandSetupLauncher.swift" \
     && grep -q 'activeConnection' "$HERE/packaging/WidebandSetupLauncher.swift" \
     && grep -q 'Would you like to check for updates when Wideband Setup starts?' "$HERE/packaging/WidebandSetupLauncher.swift" \
     && grep -q 'https://os.wideband.ai/version' "$HERE/packaging/Info.plist" \
     && grep -q 'WB_SETUP_ROOT' "$HERE/packaging/run-setup.command"; then
    if command -v xcrun >/dev/null 2>&1; then
      xcrun swiftc -parse-as-library -typecheck -target arm64-apple-macos13.0 \
        -framework AppKit -framework WebKit \
        "$HERE/packaging/UpdateFeed.swift" \
        "$HERE/packaging/WidebandSetupLauncher.swift" >/dev/null 2>&1 \
        && ok "Wideband Setup embedded native guide compiles" \
        || no "Wideband Setup embedded native guide does not compile"
    else
      ok "Wideband Setup native launcher and bare-Mac engine are packaged (compile deferred)"
    fi
  else
    no "Wideband Setup launcher or bare-Mac engine packaging is incomplete"
  fi

  if bash "$HERE/tests/app-launcher-resume-test.sh" >/dev/null 2>&1; then
    ok "Wideband Setup resumes a failed bootstrap without duplicating an active prompt"
  else
    no "Wideband Setup launcher cannot resume a failed bootstrap safely"
  fi

  if bash "$HERE/tests/agent-revision-test.sh" >/dev/null 2>&1; then
    ok "Setup-only updates preserve the approved Agent and changed code replaces it"
  else
    no "Wideband Agent revision migration or replacement failed"
  fi

  if command -v xcrun >/dev/null 2>&1; then
    UPDATE_TEST_BIN="$(mktemp /tmp/wb-update-feed-test.XXXXXX)"
    if xcrun swiftc -parse-as-library -target arm64-apple-macos13.0 \
         "$HERE/packaging/UpdateFeed.swift" "$HERE/tests/update-feed-tests.swift" \
         -o "$UPDATE_TEST_BIN" >/dev/null 2>&1 \
       && "$UPDATE_TEST_BIN" >/dev/null 2>&1; then
      ok "update feed accepts only the pinned Wideband endpoint and release repository"
    else
      no "update feed validation or version comparison failed"
    fi
    /bin/rm -f "$UPDATE_TEST_BIN"
  else
    ok "update feed validation test is present (compile deferred)"
  fi

  if [ -f "$HERE/updates/version.json" ]; then
    if feed_check="$(python3 - "$HERE" <<'PY'
import hashlib, importlib.util, json, pathlib, plistlib, sys
root = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("release_feed", root / "updates" / "release_feed.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
feed = json.loads((root / "updates" / "version.json").read_text(encoding="utf-8"))
module.validate_feed(feed)
manifest = json.loads((root / "installer" / "manifest.json").read_text(encoding="utf-8"))
assert feed["latest"]["version"] == manifest["release"]
artifact = root / "dist" / feed["latest"]["artifact_name"]
app = root / "dist" / "Wideband Setup.app"
if app.is_dir():
    build_id = (app / "Contents" / "Resources" / "build-id.txt").read_text().strip()
    if build_id != feed["latest"]["build_id"]:
        print("unpublished-pilot")
    elif artifact.is_file():
        with (app / "Contents" / "Info.plist").open("rb") as handle:
            info = plistlib.load(handle)
        assert info["CFBundleShortVersionString"] == feed["latest"]["version"]
        assert artifact.stat().st_size == feed["latest"]["size_bytes"]
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == feed["latest"]["sha256"]
        print("exact-artifact")
    else:
        print("no-local-artifact")
else:
    print("no-local-app")
PY
    )" 2>/dev/null; then
      case "$feed_check" in
        exact-artifact)
          ok "published update feed matches the manifest and exact local release artifact" ;;
        unpublished-pilot)
          ok "published update feed matches the manifest; exact artifact check skipped for unpublished local pilot" ;;
        no-local-artifact|no-local-app)
          ok "published update feed matches the manifest (no local release artifact to compare)" ;;
        *)
          no "published update feed check returned an unknown result" ;;
      esac
    else
      no "published update feed is invalid or stale"
    fi
  elif grep -q -- "--exclude 'updates/'" "$HERE/packaging/build-app.sh"; then
    ok "release feed is intentionally excluded from the client payload"
  else
    no "update feed is missing without a packaging boundary"
  fi

  if [ -f "$HERE/.github/workflows/publish-update-feed.yml" ] \
     && grep -q 'updates/build_site.py' "$HERE/.github/workflows/publish-update-feed.yml" \
     && grep -q 'actions/deploy-pages@' "$HERE/.github/workflows/publish-update-feed.yml"; then
    ok "GitHub Pages publishes only a validated update site"
  elif [ ! -d "$HERE/.git" ] && grep -q -- "--exclude '.github/'" "$HERE/packaging/build-app.sh"; then
    ok "release workflow is intentionally excluded from the client payload"
  else
    no "update feed deployment workflow is missing or bypasses validation"
  fi

  if grep -q -- '--sign-identity' "$HERE/packaging/build-app.sh" \
     && grep -q 'notarytool submit' "$HERE/packaging/build-app.sh" \
     && grep -q 'stapler validate' "$HERE/packaging/build-app.sh" \
     && grep -q 'ARTIFACT_STEM="Wideband-Setup-unsigned"' "$HERE/packaging/build-app.sh"; then
    ok "release builder supports Developer ID signing, notarization, stapling, and unsigned pilots"
  else
    no "release builder lacks a complete signed/notarized path"
  fi

  if grep -q 'x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension' \
       "$HERE/packaging/Open Privacy & Security.html" \
     && grep -q 'Open Privacy & Security.html' "$HERE/packaging/build-app.sh" \
     && grep -q 'Privacy & Security' "$HERE/packaging/SHARE-README.txt" \
     && grep -q 'Open Anyway' "$HERE/packaging/SHARE-README.txt"; then
    ok "unsigned first launch has an explicit Privacy & Security handoff"
  else
    no "unsigned first-launch instructions or shortcut are incomplete"
  fi

  if python3 - "$HERE/setup.py" <<'PY' >/dev/null 2>&1
import importlib.util, pathlib, sys, tempfile, zipfile
source = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("wb_setup_support", source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
with tempfile.TemporaryDirectory() as directory:
    root = pathlib.Path(directory)
    store = module.StateStore(root / "state")
    def seed(data):
        data["last_verification"] = {
            "summary": {"passed": 1, "failed": 1, "skipped": 0},
            "checks": [{
                "id": "TEST",
                "status": "fail",
                "message": "user@example.com +15551234567 sk-secretsecretsecret",
            }],
        }
        data["action_runs"]["run_install"] = {
            "status": "complete",
            "exit_code": 0,
            "started_at": "then",
            "finished_at": "now",
            "output_tail": "RAW-SECRET-MUST-NOT-SHIP",
        }
    store.update(seed)
    summary = module.support_summary(store)
    assert "install.reconcile" in summary["setup"]["completed_step_ids"]
    bundle, _ = module.create_support_bundle(store)
    assert bundle.stat().st_mode & 0o777 == 0o600
    with zipfile.ZipFile(bundle) as archive:
        assert set(archive.namelist()) == {"README.txt", "diagnostics.json"}
        content = b"\n".join(archive.read(name) for name in archive.namelist()).decode()
    assert "user@example.com" not in content
    assert "+15551234567" not in content
    assert "sk-secretsecretsecret" not in content
    assert "RAW-SECRET-MUST-NOT-SHIP" not in content
    assert ".sop-vars values" in content
PY
  then
    ok "support bundle is private, minimal, and redacts common credentials and contact values"
  else
    no "support bundle privacy contract failed"
  fi

  if python3 - "$HERE/setup.py" <<'PY' >/dev/null 2>&1
import importlib.util, pathlib, sys, tempfile, time
source = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("wb_setup_deactivate", source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
with tempfile.TemporaryDirectory() as directory:
    root = pathlib.Path(directory)
    home = root / "home"
    launch_agents = home / "Library" / "LaunchAgents"
    agent = home / "Applications" / "Wideband Agent.app"
    launch_agents.mkdir(parents=True)
    agent.mkdir(parents=True)
    (home / ".sop-vars").write_text('export ORG="acme"\n', encoding="utf-8")
    for job in ("cost-watch", "healthcheck", "tmux-boot", "imessage-watch", "imessage-route", "imessage-keep", "imessage-outbox",
                "fleetdeck-portal", "fleetdeck-chat", "fleetdeck-adopt", "fleetdeck-skin"):
        (launch_agents / f"com.acme.{job}.plist").write_text(job, encoding="utf-8")
    (launch_agents / "ai.wideband.first-project.plist").write_text("first project", encoding="utf-8")
    fleetdeck = home / "srv" / "fleetdeck"
    fleetdeck.mkdir(parents=True)
    (fleetdeck / "config.json").write_text('{"label_prefix":"com.acme"}', encoding="utf-8")
    workspace = home / "wideband" / "head"
    workspace.mkdir(parents=True)
    (workspace / "CLIENT.txt").write_text("preserve", encoding="utf-8")
    unrelated = launch_agents / "com.other.healthcheck.plist"
    unrelated.write_text("keep", encoding="utf-8")
    unrelated_imessage = launch_agents / "com.other.imessage-watch.plist"
    unrelated_imessage.write_text("keep", encoding="utf-8")
    store = module.StateStore(root / "state")
    store.update(lambda data: (
        data["completed"].update({"prove.messaging": {"at": "test", "source": "human"}}),
        data["action_runs"].update({
            "run_first_goal_apply": {"status": "complete"},
            "run_phone_install": {"status": "complete"},
        }),
    ))
    result = module.deactivate_wideband(store, home=home, run_launchctl=False)
    assert result["deactivated"] and result["moved_count"] == 13
    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert unrelated_imessage.read_text(encoding="utf-8") == "keep"
    assert (workspace / "CLIENT.txt").read_text(encoding="utf-8") == "preserve"
    assert not agent.exists()
    recovery = pathlib.Path(result["recovery_path"])
    assert (recovery / "receipt.json").stat().st_mode & 0o777 == 0o600
    assert (store.directory / "deactivated").stat().st_mode & 0o777 == 0o600
    assert len(list((recovery / "LaunchAgents").glob("com.acme.*.plist"))) == 11
    assert (recovery / "LaunchAgents" / "ai.wideband.first-project.plist").is_file()
    assert store.read()["lifecycle"]["deactivated_at"]
    assert "prove.messaging" not in store.read()["completed"]
    assert "run_first_goal_apply" not in store.read()["action_runs"]
    assert "run_phone_install" not in store.read()["action_runs"]
    runner = module.JobRunner(store)
    runner.COMMANDS = {"run_imessage_install": ["/usr/bin/true"], "run_verify_imessage": ["/usr/bin/true"]}
    job = runner.start("run_imessage_install")
    for _ in range(100):
        if (
            runner.get(job["id"])["status"] == "complete"
            and not (store.directory / "deactivated").exists()
            and store.read()["lifecycle"]["deactivated_at"] is None
        ):
            break
        time.sleep(0.05)
    assert runner.get(job["id"])["status"] == "complete"
    assert not (store.directory / "deactivated").exists()
    assert store.read()["lifecycle"]["deactivated_at"] is None
PY
  then
    ok "deactivation is confirmed, scoped to Wideband objects, and recoverable"
  else
    no "recoverable deactivation contract failed"
  fi

  if grep -q 'DEACTIVATED=.*deactivated' "$HERE/packaging/app-launcher" \
     && grep -q '! -f "$DEACTIVATED"' "$HERE/packaging/app-launcher" \
     && grep -q 'directory / "deactivated"' "$HERE/setup.py"; then
    ok "reopening setup preserves an explicit deactivation until Repair succeeds"
  else
    no "packaged launcher can silently undo deactivation"
  fi

  profile_tmp="$(mktemp)"
  if python3 "$HERE/packaging/render-profile.py" \
       "$HERE/packaging/client-profile.example.json" "$profile_tmp" >/dev/null 2>&1 \
     && grep -q '^export CLIENT_NAME=' "$profile_tmp" \
     && grep -q '^export WORK_REPO=' "$profile_tmp"; then
    ok "personalized client profile validates and renders"
  else
    no "personalized client profile renderer failed"
  fi
  rm -f "$profile_tmp"

  if python3 "$HERE/tests/phone-link-test.py" >/dev/null 2>&1; then
    ok "Fleetdeck phone link requires exact Serve routing and live HTTPS health"
  else
    no "Fleetdeck phone link can expose an unverified route"
  fi

  if python3 "$HERE/tests/setup-handoff-test.py" >/dev/null 2>&1; then
    ok "setup texts require proven phone handoff and queue once through guarded outbox"
  else
    no "setup texts can bypass owner proof or repeat from an unsafe route"
  fi

  if python3 "$HERE/tests/provider-choice-test.py" >/dev/null 2>&1; then
    ok "provider choice is explicit, persisted, and gated before text activation"
  else
    no "provider choice can silently activate an unverified text runtime"
  fi

  if python3 "$HERE/tests/bind-handoff-test.py" >/dev/null 2>&1; then
    ok "iMessage bind uses the app's privacy identity and requires exact private success output"
  else
    no "iMessage bind can mistake open's status for the app's result"
  fi

  tmp="$(mktemp)"
  bash "$HERE/verify.sh" --quick --json > "$tmp" 2>/dev/null || true
  if python3 - "$tmp" <<'PY' >/dev/null 2>&1
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
assert data["schema_version"] == 1
assert {"passed", "failed", "skipped"} <= data["summary"].keys()
assert data["checks"] and all({"id", "status", "message"} <= item.keys() for item in data["checks"])
PY
  then
    ok "verify.sh --json satisfies the installer contract"
  else
    no "verify.sh --json did not return the installer contract"
  fi
  rm -f "$tmp"
fi

# ── 10. syntax ───────────────────────────────────────────────────────────────
head_ "10 · syntax"
for s in bootstrap.sh install.sh verify.sh selftest.sh doctor.sh setup.sh \
         packaging/app-launcher packaging/build-app.sh packaging/run-setup.command \
         lib/bootstrap-homebrew.sh \
         skills/agent-session-memory/scripts/selfcheck.sh; do
  [ -f "$HERE/$s" ] || { no "$s missing"; continue; }
  bash -n "$HERE/$s" 2>/dev/null && ok "$s parses" || no "$s has a syntax error"
done
if command -v python3 >/dev/null 2>&1; then
  python3 -c 'import sys; compile(open(sys.argv[1], encoding="utf-8").read(), sys.argv[1], "exec")' "$HERE/setup.py" \
    && ok "setup.py parses" || no "setup.py has a syntax error"
  python3 -c 'import sys; compile(open(sys.argv[1], encoding="utf-8").read(), sys.argv[1], "exec")' "$HERE/bin/tm-memory" \
    && ok "tm-memory parses" || no "tm-memory has a syntax error"
fi
if command -v node >/dev/null 2>&1; then
  node --check "$HERE/installer/app.js" >/dev/null 2>&1 \
    && ok "installer/app.js parses" || no "installer/app.js has a syntax error"
  node --check "$HERE/tests/browser-e2e.mjs" >/dev/null 2>&1 \
    && ok "browser E2E runner parses" || no "browser E2E runner has a syntax error"
fi
for p in "$HERE"/loops/*; do
  [ -f "$p" ] || continue
  head -1 "$p" | grep -q python || continue
  b="$(basename "$p")"
  if command -v python3 >/dev/null 2>&1; then
    python3 -c "import ast,sys; ast.parse(open(sys.argv[1]).read())" "$p" 2>/dev/null \
      && ok "$b parses" || no "$b has a syntax error"
  fi
done
if command -v shellcheck >/dev/null 2>&1; then
  for s in bootstrap.sh install.sh verify.sh selftest.sh doctor.sh setup.sh; do
    shellcheck -S error "$HERE/$s" >/dev/null 2>&1 \
      && ok "shellcheck $s (errors)" \
      || no "shellcheck found errors in $s"
  done
fi

# ── 11. the session-memory skill ─────────────────────────────────────────────
# A skill is chosen from its name and description before anything else is read,
# and a reference nothing links to is a file that never loads. Both fail
# silently at the moment they matter, so they are asserted here.
head_ "11 · agent-session-memory skill"
SK="$HERE/skills/agent-session-memory"
if [ ! -f "$SK/SKILL.md" ]; then
  no "skills/agent-session-memory/SKILL.md missing"
else
  if head -1 "$SK/SKILL.md" | grep -q '^---$' \
     && grep -q '^name: agent-session-memory$' "$SK/SKILL.md" \
     && grep -q '^description: .\{40,\}' "$SK/SKILL.md"; then
    ok "SKILL.md carries the frontmatter a skill is selected by"
  else
    no "SKILL.md is missing name or a usable description"
  fi
  unlinked=0
  for r in "$SK"/references/*.md; do
    [ -f "$r" ] || continue
    grep -q "references/$(basename "$r")" "$SK/SKILL.md" \
      || { no "references/$(basename "$r") is linked from nothing — it will never load"; unlinked=1; }
  done
  [ "$unlinked" = 0 ] && ok "every reference is reachable from SKILL.md"
fi
[ -x "$HERE/bin/tm-memory" ] \
  && ok "tm-memory is executable" || no "bin/tm-memory is not executable"
[ -x "$SK/scripts/selfcheck.sh" ] \
  && ok "the recovery selfcheck is executable" || no "selfcheck.sh is not executable"
grep -q 'tm-memory' "$HERE/install.sh" \
  && ok "install.sh places tm-memory" || no "install.sh never installs tm-memory"
grep -q 'place_skill "$HERE/skills/agent-session-memory"' "$HERE/install.sh" \
  && ok "install.sh installs the skill for the agents" || no "the skill is never installed"
grep -q 'tm-memory' "$HERE/loops/tmux-boot" \
  && ok "tmux-boot primes session identity at login" || no "tmux-boot never primes identity"
if grep -q 'send-keys' "$HERE/loops/tmux-boot"; then
  no "tmux-boot types into panes — login is unattended; it must not"
else
  ok "tmux-boot types into no pane"
fi

printf '\n\033[1m%s\033[0m\n' "─────────────────────────────────────────"
printf '  %d passed · %d failed\n\n' "$PASS" "$FAIL"
exit "$FAIL"
