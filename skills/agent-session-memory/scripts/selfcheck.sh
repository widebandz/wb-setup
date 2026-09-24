#!/bin/bash
# selfcheck.sh — prove the recovery path before it is pointed at a real fleet.
#
# Everything here runs against an ISOLATED tmux server (`tmux -L <socket>`) and
# a temporary memory directory. It never lists, reads, writes, or kills a
# session on the default server, so it is safe to run on the live machine.
#
# Exit code is the number of failures.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TM_MEMORY_BIN="${TM_MEMORY_BIN:-$(command -v tm-memory || echo "$HERE/../../../bin/tm-memory")}"
[ -x "$TM_MEMORY_BIN" ] || { echo "selfcheck: no tm-memory at $TM_MEMORY_BIN" >&2; exit 1; }
command -v tmux >/dev/null 2>&1 || { echo "selfcheck: tmux is required" >&2; exit 1; }

PASS=0; FAIL=0
ok() { printf '  ✓ %s\n' "$*"; PASS=$((PASS+1)); }
no() { printf '  ✗ %s\n' "$*"; FAIL=$((FAIL+1)); }
head_() { printf '\n\033[1m%s\033[0m\n' "$*"; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/wb-memory-selfcheck.XXXXXX")" || exit 1
SOCKET="wbmem-selfcheck-$$"

cleanup() {
  tmux -L "$SOCKET" kill-server >/dev/null 2>&1
  [ -n "${WORK:-}" ] && [ -d "$WORK" ] && rm -rf "$WORK"
}
trap cleanup EXIT

export TM_MEMORY_DIR="$WORK/memory"
export TM_ROUTING="$WORK/routing.json"
export TM_SESSIONS_CONF="$WORK/sessions.conf"
export TM_TMUX_SOCKET="$SOCKET"
export TM_MEMORY_LAUNCHERS="fakeagent"
export PATH="$WORK/bin:$PATH"

mkdir -p "$WORK/bin" "$TM_MEMORY_DIR/identity" "$TM_MEMORY_DIR/state"

# A stand-in agent. A real binary, not a shell script: tmux reports the
# interpreter for a script, so a script would never look like an agent pane.
# `cat` sits on stdin and echoes it, which also proves what was injected.
cp /bin/cat "$WORK/bin/fakeagent"

cat > "$TM_ROUTING" <<'JSON'
{
  "sessions": { "probe": "the disposable probe session", "ghost": "described but not running" },
  "exclude": [],
  "agent_pane_commands": ["fakeagent"],
  "shell_pane_commands": ["zsh", "bash", "sh", "fish"]
}
JSON

printf 'probe = %s\n' "$WORK" > "$TM_SESSIONS_CONF"

tm() { "$TM_MEMORY_BIN" "$@"; }

has() { # has HAYSTACK NEEDLE — no pipe, so no SIGPIPE race under pipefail
  case "$1" in *"$2"*) return 0 ;; *) return 1 ;; esac
}

pane() { tmux -L "$SOCKET" capture-pane -p -t "$1"; }

card() { # card NAME BOOTSTRAP [extra frontmatter lines...]
  local name="$1" boot="$2"; shift 2
  {
    echo "---"
    echo "session: $name"
    echo "role: assigned"
    echo "concern: disposable probe session for the recovery selfcheck"
    echo "root: $WORK"
    echo "bootstrap: $boot"
    for extra in "$@"; do echo "$extra"; done
    echo "updated: $(date +%Y-%m-%d)"
    echo "---"
    echo
    echo "## Responsibilities"
    echo
    echo "- prove the recovery path"
    echo
    echo "## Not this session"
    echo
    echo "- anything on the real fleet"
  } > "$TM_MEMORY_DIR/identity/$name.md"
}

unassigned_card() { # unassigned_card NAME
  {
    echo "---"
    echo "session: $1"
    echo "role: unassigned"
    echo "root: $WORK"
    echo "bootstrap: fakeagent"
    echo "updated: $(date +%Y-%m-%d)"
    echo "---"
    echo
    echo "## Responsibilities"
    echo
    echo "- UNVERIFIED — no role assigned."
    echo
    echo "## Not this session"
    echo
    echo "- UNVERIFIED — no exclusions recorded."
  } > "$TM_MEMORY_DIR/identity/$1.md"
}

echo "▩ agent-session-memory selfcheck"
echo "  tm-memory $TM_MEMORY_BIN"
echo "  socket    $SOCKET (isolated server)"
echo "  workdir   $WORK"

# ── isolated server ──────────────────────────────────────────────────────────
head_ "0 · isolation"
tmux -L "$SOCKET" -f /dev/null new-session -d -s probe /bin/sh >/dev/null 2>&1
if tmux -L "$SOCKET" has-session -t =probe 2>/dev/null; then
  ok "disposable 'probe' session created on the isolated server"
else
  no "could not create the isolated probe session"; echo; exit "$((FAIL))"
fi
sleep 0.5
probe_cmd="$(tmux -L "$SOCKET" list-panes -s -t =probe -F '#{pane_current_command}' | head -1)"
case "$probe_cmd" in
  sh|bash|zsh|fish) ok "probe pane is a bare shell ($probe_cmd)" ;;
  *) no "probe pane is '$probe_cmd', not a shell — the refusal tests would not mean anything" ;;
esac

# ── schema, aliases, roots, secrets ──────────────────────────────────────────
head_ "1 · card validation"
card probe fakeagent
out="$(tm check 2>&1)"; rc=$?
[ "$rc" -eq 0 ] && ok "a well-formed card passes check" \
                || { no "valid card rejected:"; printf '%s\n' "$out" | sed 's/^/      /'; }

card dup fakeagent "aliases:" "  - shared"
card dup2 fakeagent "aliases:" "  - shared"
out="$(tm check 2>&1)"
has "$out" "also claimed by" \
  && ok "duplicate alias across two cards is an error" \
  || no "duplicate alias was not detected"
rm -f "$TM_MEMORY_DIR/identity/dup.md" "$TM_MEMORY_DIR/identity/dup2.md"

card shadow fakeagent "aliases:" "  - probe"
has "$(tm check 2>&1)" "canonical name" \
  && ok "an alias that shadows another session's name is an error" \
  || no "alias/name collision was not detected"
rm -f "$TM_MEMORY_DIR/identity/shadow.md"

sed "s|^root: .*|root: $WORK/does-not-exist|" "$TM_MEMORY_DIR/identity/probe.md" \
  > "$TM_MEMORY_DIR/identity/missingroot.md"
sed -i '' 's/^session: probe/session: missingroot/' "$TM_MEMORY_DIR/identity/missingroot.md" 2>/dev/null \
  || sed -i 's/^session: probe/session: missingroot/' "$TM_MEMORY_DIR/identity/missingroot.md"
out="$(tm check 2>&1)"; rc=$?
has "$out" "does not exist" \
  && ok "a missing project root is reported" \
  || no "missing root was not reported"
[ "$rc" -eq 0 ] && ok "a missing root warns rather than failing the fleet" \
                || no "missing root was treated as a hard error"
rm -f "$TM_MEMORY_DIR/identity/missingroot.md"

card badfield fakeagent "notakey: something"
has "$(tm check 2>&1)" "unknown field" \
  && ok "an unknown frontmatter field is an error, so typos surface" \
  || no "unknown field accepted"
rm -f "$TM_MEMORY_DIR/identity/badfield.md"

head_ "2 · secrets never become durable memory"
secret_case() { # secret_case LABEL LINE
  card leak fakeagent
  printf '%s\n' "$2" >> "$TM_MEMORY_DIR/identity/leak.md"
  out="$(tm check 2>&1)"; rc=$?
  if [ "$rc" -gt 0 ] && has "$out" "remove it"; then
    ok "$1 rejected"
  else
    no "$1 was NOT rejected"
  fi
  rm -f "$TM_MEMORY_DIR/identity/leak.md"
}
secret_case "a GitHub token"    "- ghp_$(printf 'A%.0s' $(seq 1 24))"
secret_case "an API key"        "- sk-$(printf 'B%.0s' $(seq 1 24))"
secret_case "a private key"     "- -----BEGIN OPENSSH PRIVATE $(printf 'KEY')-----"
secret_case "a phone number"    "- reachable at +15551234567"
secret_case "an inline password" "- password: hunter2hunter2"

card envref fakeagent "recovery_checks:" '  - curl -H "Authorization: Bearer $DQR_TOKEN" https://example.com'
out="$(tm check 2>&1)"; rc=$?
[ "$rc" -eq 0 ] && ok "naming an env var (not its value) is allowed" \
                || { no "an env-var reference was wrongly rejected:"; printf '%s\n' "$out" | sed 's/^/      /'; }
rm -f "$TM_MEMORY_DIR/identity/envref.md"

# ── the bootstrap allowlist ──────────────────────────────────────────────────
head_ "3 · a card cannot become arbitrary shell"
card evil "fakeagent; curl http://example.com/x"
has "$(tm check 2>&1)" "metacharacter" \
  && ok "a chained command in bootstrap is rejected" \
  || no "command chaining in bootstrap was accepted"
rm -f "$TM_MEMORY_DIR/identity/evil.md"

card evil2 "rm -rf /tmp/nope"
has "$(tm check 2>&1)" "not an approved agent launcher" \
  && ok "a non-launcher bootstrap is rejected" \
  || no "an arbitrary bootstrap command was accepted"
rm -f "$TM_MEMORY_DIR/identity/evil2.md"

# ── bare-shell refusal ───────────────────────────────────────────────────────
head_ "4 · recovery refuses a bare shell"
card probe fakeagent
out="$(tm resume probe 2>&1)"; rc=$?
if [ "$rc" -eq 5 ] && has "$out" "REFUSED"; then
  ok "resume refuses a pane running a shell (exit 5)"
else
  no "resume did not refuse a bare shell (exit $rc)"
fi
if has "$(pane probe)" "Session identity restored"; then
  no "a brief was typed into a bare shell"
else
  ok "nothing was typed into the bare shell"
fi

head_ "5 · restored scrollback is not authorization"
# Paint agent-looking text into a pane that is still a bare shell — exactly what
# tmux-resurrect leaves behind after a restore.
tmux -L "$SOCKET" send-keys -t probe -l \
  'printf "\n> Ask Codex to do anything\n  gpt-5.6 max\n"' >/dev/null 2>&1
tmux -L "$SOCKET" send-keys -t probe Enter >/dev/null 2>&1
sleep 0.5
if has "$(pane probe)" "Ask Codex"; then
  ok "pane scrollback now looks like a live agent"
else
  no "could not stage the restored-scrollback case"
fi
out="$(tm resume probe 2>&1)"; rc=$?
if [ "$rc" -eq 5 ] && has "$out" "REFUSED"; then
  ok "resume still refuses — it reads the process, not the screen"
else
  no "agent-looking scrollback was mistaken for a running agent (exit $rc)"
fi

head_ "6 · refusal when no bootstrap is approved"
card noboot ""
tmux -L "$SOCKET" -f /dev/null new-session -d -s noboot /bin/sh >/dev/null 2>&1
sleep 0.3
out="$(tm resume noboot --start 2>&1)"; rc=$?
if [ "$rc" -eq 5 ] && has "$out" "REFUSED"; then
  ok "--start refuses when the card names no approved launcher"
else
  no "--start proceeded without an approved launcher (exit $rc)"
fi

# ── the sanctioned start path ────────────────────────────────────────────────
head_ "7 · the explicit bootstrap flow"
out="$(tm resume probe --start --inject --timeout 20 --settle 0 2>&1)"; rc=$?
sleep 0.5
now="$(tmux -L "$SOCKET" list-panes -s -t =probe -F '#{pane_current_command}' | head -1)"
if [ "$rc" -eq 0 ] && [ "$now" = "fakeagent" ]; then
  ok "--start launched the approved agent and waited for the process"
else
  no "--start did not bring up an agent (exit $rc, pane=$now)"
  printf '%s\n' "$out" | sed 's/^/      /'
fi
if has "$(pane probe)" "Session identity restored"; then
  ok "the brief was injected only after an agent process existed"
else
  no "the brief never reached the agent"
fi
if has "$(pane probe)" "not authorization"; then
  ok "the brief tells the agent restored scrollback is not an instruction"
else
  no "the brief is missing the scrollback warning"
fi

head_ "8 · restore is idempotent"
before="$(tmux -L "$SOCKET" list-panes -s -t =probe -F '#{pane_pid}' | head -1)"
out="$(tm resume probe --start 2>&1)"; rc=$?
after="$(tmux -L "$SOCKET" list-panes -s -t =probe -F '#{pane_pid}' | head -1)"
if [ "$rc" -eq 0 ] && has "$out" "already running"; then
  ok "a second --start starts nothing"
else
  no "a second --start was not a no-op (exit $rc)"
fi
if [ -n "$before" ] && [ "$before" = "$after" ]; then
  ok "no second agent process was created (pane pid $before unchanged)"
else
  no "pane process changed or could not be read (before='$before' after='$after')"
fi
count="$(pane probe > "$WORK/pane.txt"; grep -c "Session identity restored" "$WORK/pane.txt")"
[ "$count" -le 2 ] && ok "resume without --inject did not re-send the brief (seen $count)" \
                   || no "the brief was re-injected on a plain resume (seen $count)"

head_ "9 · a missing session is reported, not created"
out="$(tm resume ghostcard 2>&1)"; rc=$?
[ "$rc" -eq 2 ] && ok "an unknown session name is refused" \
                || no "an unknown session name returned $rc"
card offline fakeagent
out="$(tm resume offline 2>&1)"; rc=$?
if [ "$rc" -eq 4 ] && has "$out" "not running"; then
  ok "a card with no live session prints the bootstrap, creates nothing"
else
  no "an offline session was not handled (exit $rc)"
fi
tmux -L "$SOCKET" has-session -t =offline 2>/dev/null \
  && no "resume created a session it should not have" \
  || ok "no session was created as a side effect"

head_ "9b · assigned and unassigned are different contracts"
unassigned_card drifter
out="$(tm check 2>&1)"; rc=$?
if [ "$rc" -eq 0 ]; then
  ok "an unassigned card may be sparse and carry UNVERIFIED"
else
  no "a sparse unassigned card was rejected:"; printf '%s\n' "$out" | sed 's/^/      /'
fi

sed -i '' 's/^role: unassigned/role: assigned/' "$TM_MEMORY_DIR/identity/drifter.md" 2>/dev/null \
  || sed -i 's/^role: unassigned/role: assigned/' "$TM_MEMORY_DIR/identity/drifter.md"
out="$(tm check 2>&1)"; rc=$?
if [ "$rc" -gt 0 ] && has "$out" "no concern is recorded"; then
  ok "promoting to assigned without a concern is refused"
else
  no "an assigned card with no concern was accepted (exit $rc)"
fi
has "$out" "UNVERIFIED" \
  && ok "an assigned card still carrying UNVERIFIED is refused" \
  || no "UNVERIFIED survived promotion to assigned"
rm -f "$TM_MEMORY_DIR/identity/drifter.md"

card badrole fakeagent
sed -i '' 's/^role: assigned/role: sortof/' "$TM_MEMORY_DIR/identity/badrole.md" 2>/dev/null \
  || sed -i 's/^role: assigned/role: sortof/' "$TM_MEMORY_DIR/identity/badrole.md"
has "$(tm check 2>&1)" "not one of" \
  && ok "an unknown role value is refused" \
  || no "an arbitrary role value was accepted"
rm -f "$TM_MEMORY_DIR/identity/badrole.md"

head_ "9c · an unassigned session recovers as a fresh start"
unassigned_card probe
brief="$(tm brief probe 2>&1)"
has "$brief" "has no assigned role" \
  && ok "the brief tells an unassigned agent it has no role" \
  || no "the unassigned brief does not say the role is unassigned"
has "$brief" "do not infer a mission" \
  && ok "it forbids inferring a mission from scrollback, directory or name" \
  || no "the unassigned brief is missing the do-not-infer rule"
if has "$brief" "Session identity restored"; then
  no "the unassigned brief reuses the assigned wording"
else
  ok "it does not claim an identity was restored"
fi
card probe fakeagent
has "$(tm brief probe 2>&1)" "Session identity restored" \
  && ok "an assigned session still gets the identity brief" \
  || no "the assigned brief regressed"

# ── migration ────────────────────────────────────────────────────────────────
head_ "10 · adopt never overwrites"
tmux -L "$SOCKET" -f /dev/null new-session -d -s fresh /bin/sh >/dev/null 2>&1
sleep 0.3
tm adopt >/dev/null 2>&1
[ -f "$TM_MEMORY_DIR/identity/fresh.md" ] \
  && ok "adopt drafted a card for an uncovered live session" \
  || no "adopt did not draft the uncovered session"
grep -q "UNVERIFIED" "$TM_MEMORY_DIR/identity/fresh.md" 2>/dev/null \
  && ok "the draft marks what it could not verify" \
  || no "the draft invented content instead of marking it UNVERIFIED"
grep -q "^role: unassigned$" "$TM_MEMORY_DIR/identity/fresh.md" 2>/dev/null \
  && ok "adopt drafts an unassigned role — it never decides one" \
  || no "adopt assigned a role it had no evidence for"
sum_before="$(shasum "$TM_MEMORY_DIR/identity/probe.md" | awk '{print $1}')"
out="$(tm adopt 2>&1)"
sum_after="$(shasum "$TM_MEMORY_DIR/identity/probe.md" | awk '{print $1}')"
[ "$sum_before" = "$sum_after" ] && ok "a second adopt left the curated card byte-identical" \
                                 || no "adopt overwrote an existing card"
has "$out" "card exists" \
  && ok "adopt says what it skipped and why" \
  || no "adopt did not report skipped sessions"

head_ "11 · drift is visible"
out="$(tm doctor 2>&1)"
has "$out" "ghost" \
  && ok "a routing entry with no live session shows as drift" \
  || no "routing drift was not reported"
rm -f "$TM_MEMORY_DIR/identity/fresh.md"
has "$(tm doctor 2>&1)" "no identity card" \
  && ok "a live session with no card shows as uncovered" \
  || no "an uncovered live session was not reported"
has "$(tm doctor 2>&1)" "not in the standard" \
  && ok "a live session missing from sessions.conf shows as drift" \
  || no "sessions.conf drift was not reported"
unassigned_card probe
has "$(tm doctor 2>&1)" "no assigned role" \
  && ok "unassigned live sessions are listed for promotion" \
  || no "the unassigned section is missing from doctor"
card probe fakeagent

head_ "12 · backup and rollback"
tm backup --quiet
orig="$(grep '^concern:' "$TM_MEMORY_DIR/identity/probe.md")"
sed -i '' 's/^concern: .*/concern: wrecked/' "$TM_MEMORY_DIR/identity/probe.md" 2>/dev/null \
  || sed -i 's/^concern: .*/concern: wrecked/' "$TM_MEMORY_DIR/identity/probe.md"
tm rollback >/dev/null 2>&1
if [ "$(grep '^concern:' "$TM_MEMORY_DIR/identity/probe.md")" = "$orig" ]; then
  ok "rollback restored the previous card"
else
  no "rollback did not restore the card"
fi
[ "$(find "$TM_MEMORY_DIR/backups" -maxdepth 1 -mindepth 1 -type d | wc -l | tr -d ' ')" -ge 2 ] \
  && ok "rollback saved the pre-rollback state as its own backup" \
  || no "rollback discarded the state it replaced"

head_ "13 · private by default"
tmux -L "$SOCKET" -f /dev/null new-session -d -s modecheck /bin/sh >/dev/null 2>&1
sleep 0.3
tm adopt --session modecheck >/dev/null 2>&1
authored="$TM_MEMORY_DIR/identity/modecheck.md"
if [ -f "$authored" ]; then
  mode="$(stat -f '%Lp' "$authored" 2>/dev/null || stat -c '%a' "$authored")"
  [ "$mode" = "600" ] && ok "cards tm-memory writes are mode 0600" \
                      || no "card mode is $mode, not 600"
else
  no "adopt --session did not write a card to stat"
fi
dmode="$(stat -f '%Lp' "$TM_MEMORY_DIR" 2>/dev/null || stat -c '%a' "$TM_MEMORY_DIR")"
[ "$dmode" = "700" ] && ok "the memory directory is mode 0700" \
                     || no "memory directory mode is $dmode, not 700"

printf '\n\033[1m%s\033[0m\n' "─────────────────────────────────────────"
printf '  %d passed · %d failed\n\n' "$PASS" "$FAIL"
exit "$FAIL"
