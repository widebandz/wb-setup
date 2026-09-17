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
#
# Exit code is the number of failures.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PASS=0; FAIL=0

ok() { printf '  ✓ %s\n' "$*"; PASS=$((PASS+1)); }
no() { printf '  ✗ %s\n' "$*"; FAIL=$((FAIL+1)); }
head_() { printf '\n\033[1m%s\033[0m\n' "$*"; }

echo "▩ wb-setup selftest — $HERE"

# ── 1. bare-Mac tool budget ──────────────────────────────────────────────────
# Everything before the Homebrew step may use only: bash curl tar sed awk grep
# plus shell builtins. A bare macOS has no git and no python3 — those paths are
# CLT stubs that pop a dialog and block.
#
# Strings and comments are stripped first, and only COMMAND POSITION counts:
# `--no-brew` as a flag name and `command -v brew` as a guard are both fine,
# and a naive token grep flags them, which trains people to ignore this check.
head_ "1 · bare-Mac tool budget"
FORBIDDEN='git|python3|python|jq|node|npm|brew|gh|tmux|sqlite3|launchctl|tailscale|code'
hits="$(
  awk '/^# ── 2\. Homebrew/{exit} {print}' "$HERE/bootstrap.sh" \
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

found="$(grep -rIlniE 'brainwave|tailacfa70|zayed' "$HERE" \
          --exclude-dir=.git --exclude='selftest.sh' 2>/dev/null)"
[ -z "$found" ] && ok "no operator hostnames or names" \
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
assert all(step.get("type") in {"automatic", "guided", "interview", "verification"} for step in steps)
clients = [step for step in steps if step.get("actor") == "client"]
assert clients
assert all(step.get("client_phase") in {"now", "handoff", "later"} for step in clients)
assert all(step.get("client_guide", {}).get("intro") for step in clients)
assert all(step.get("client_guide", {}).get("instructions") for step in clients)
assert all(isinstance(step.get("client_priority", 1000), int) for step in clients)
frontloaded = sorted(enumerate(clients), key=lambda pair: (pair[1].get("client_priority", 1000), pair[0]))
assert [step["id"] for _, step in frontloaded[:6]] == [
    "connect.screen-sharing",
    "connect.full-disk-access",
    "connect.accessibility",
    "connect.screen-recording",
    "connect.automation-dialog",
    "connect.remote-login",
]
PY
  then
    ok "manifest parses and every client step has popup guidance"
  else
    no "manifest schema, IDs, or client-guide contract is invalid"
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
        state = json.load(urllib.request.urlopen(urllib.request.Request(base + "/api/state", headers=headers), timeout=1))
        assert state["connection"] == {
            "host": "127.0.0.1",
            "port": server.server_address[1],
            "release": module.MANIFEST["release"],
            "build_id": "test-build",
            "started_at": app.started_at,
        }
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
    ok "authenticated loopback API reports its real release, build, port, and shutdown state"
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
    run_doctor run_install run_selftest run_verify_full run_verify_quick | tr ' ' '\n' | sort -u)"
  unknown_actions="$(comm -23 <(printf '%s\n' "$manifest_actions") <(printf '%s\n' "$allowed_actions"))"
  [ -z "$unknown_actions" ] \
    && ok "every manifest action is allowlisted" \
    || { no "manifest references actions the runner does not allow:"; printf '      %s\n' $unknown_actions; }

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
     && grep -q 'function renderReadiness' "$HERE/installer/app.js" \
     && grep -q 'function runSupportJob' "$HERE/installer/app.js"; then
    ok "client UI exposes resume state, readiness, repair, and support tools"
  else
    no "client readiness or recovery UI is incomplete"
  fi

  if grep -q 'id="connection-alert"' "$HERE/installer/index.html" \
     && grep -q 'id="status-dialog"' "$HERE/installer/index.html" \
     && grep -q 'Machine verified' "$HERE/installer/index.html" \
     && grep -q 'function evidenceLabel' "$HERE/installer/app.js" \
     && grep -q 'function pollState' "$HERE/installer/app.js" \
     && grep -q 'needs_admin_password' "$HERE/installer/app.js" \
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
     && grep -q 'WidebandSetupLauncher.swift' "$HERE/packaging/build-app.sh" \
     && grep -q 'RESOURCES/app-launcher' "$HERE/packaging/build-app.sh" \
     && grep -q 'wb-setup-engine' "$HERE/packaging/build-app.sh" \
     && ! grep -q 'codesign --force --options runtime --sign -.*wb-setup-engine' "$HERE/packaging/build-app.sh" \
     && grep -q 'engine unexpectedly enables hardened runtime library validation' "$HERE/packaging/build-app.sh" \
     && grep -q 'launch_terminal' "$HERE/packaging/app-launcher" \
     && grep -q 'WB_SETUP_ROOT' "$HERE/packaging/run-setup.command"; then
    if command -v xcrun >/dev/null 2>&1; then
      xcrun swiftc -parse-as-library -typecheck -target arm64-apple-macos13.0 \
        -framework AppKit "$HERE/packaging/WidebandSetupLauncher.swift" >/dev/null 2>&1 \
        && ok "Wideband Setup native launcher compiles" \
        || no "Wideband Setup native launcher does not compile"
    else
      ok "Wideband Setup native launcher and bare-Mac engine are packaged (compile deferred)"
    fi
  else
    no "Wideband Setup launcher or bare-Mac engine packaging is incomplete"
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
    for job in ("cost-watch", "healthcheck", "tmux-boot"):
        (launch_agents / f"com.acme.{job}.plist").write_text(job, encoding="utf-8")
    unrelated = launch_agents / "com.other.healthcheck.plist"
    unrelated.write_text("keep", encoding="utf-8")
    store = module.StateStore(root / "state")
    result = module.deactivate_wideband(store, home=home, run_launchctl=False)
    assert result["deactivated"] and result["moved_count"] == 4
    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert not agent.exists()
    recovery = pathlib.Path(result["recovery_path"])
    assert (recovery / "receipt.json").stat().st_mode & 0o777 == 0o600
    assert (store.directory / "deactivated").stat().st_mode & 0o777 == 0o600
    assert len(list((recovery / "LaunchAgents").glob("com.acme.*.plist"))) == 3
    assert store.read()["lifecycle"]["deactivated_at"]
    runner = module.JobRunner(store)
    runner.COMMANDS = {"run_install": ["/usr/bin/true"]}
    job = runner.start("run_install")
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
         packaging/app-launcher packaging/build-app.sh packaging/run-setup.command; do
  [ -f "$HERE/$s" ] || { no "$s missing"; continue; }
  bash -n "$HERE/$s" 2>/dev/null && ok "$s parses" || no "$s has a syntax error"
done
if command -v python3 >/dev/null 2>&1; then
  python3 -c 'import sys; compile(open(sys.argv[1], encoding="utf-8").read(), sys.argv[1], "exec")' "$HERE/setup.py" \
    && ok "setup.py parses" || no "setup.py has a syntax error"
fi
if command -v node >/dev/null 2>&1; then
  node --check "$HERE/installer/app.js" >/dev/null 2>&1 \
    && ok "installer/app.js parses" || no "installer/app.js has a syntax error"
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

printf '\n\033[1m%s\033[0m\n' "─────────────────────────────────────────"
printf '  %d passed · %d failed\n\n' "$PASS" "$FAIL"
exit "$FAIL"
