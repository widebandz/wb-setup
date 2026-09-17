#!/bin/bash
# verify.sh — what is actually true on this machine, phase by phase.
#
# Assertions, not executions and not eyeballs. Every check below either passes
# or names the exact thing that is wrong; "the installer exited 0" is not
# evidence that a loop is delivering or that a grant was given.
#
# Exit code is the number of failures, so this composes into a gate.
#
#   bash verify.sh            everything
#   bash verify.sh --quick    skip the network-bound checks (MCP, tailnet)
#   bash verify.sh --json     the same assertions as structured installer data
#
# A verifier that reports all green on a machine with known gaps is broken. If
# this prints nothing but ✓ on a fresh build, distrust it before trusting it.
set -uo pipefail

QUICK=0; JSON=0
for arg in "$@"; do
  case "$arg" in
    --quick) QUICK=1 ;;
    --json)  JSON=1 ;;
    --help|-h)
      echo "usage: bash verify.sh [--quick] [--json]"
      exit 0 ;;
    *)
      echo "unknown option: $arg" >&2
      exit 2 ;;
  esac
done

VARS="$HOME/.sop-vars"
PASS=0; FAIL=0; SKIP=0
RESULTS=""
[ "$JSON" = "1" ] && RESULTS="$(mktemp -t wb-verify.XXXXXX)"
cleanup() { [ -n "$RESULTS" ] && rm -f "$RESULTS"; }
trap cleanup EXIT INT TERM

record() {
  [ "$JSON" = "1" ] || return 0
  # Messages are fixed single-line strings. Tabs are excluded so the temporary
  # record remains parseable without jq (which is itself one of the checks).
  printf '%s\t%s\t%s\n' "$1" "$2" "$(printf '%s' "$3" | tr '\t' ' ')" >> "$RESULTS"
}
ok()   {
  id="$1"; shift
  [ "$JSON" = "0" ] && printf '  ✓ %s\n' "$*"
  record pass "$id" "$*"
  PASS=$((PASS+1))
}
# no() takes a stable check ID first, then the message. The ID is the lookup
# key into TROUBLESHOOTING.md — an agent reading this output gets a section to
# open rather than a sentence to pattern-match. selftest.sh asserts every ID
# here has a section there, and that every section maps back to a live check,
# so the guide cannot drift out of sync without failing the suite.
no()   {
  id="$1"; shift
  [ "$JSON" = "0" ] && printf '  ✗ [%s] %s\n' "$id" "$*"
  record fail "$id" "$*"
  FAIL=$((FAIL+1))
}
skip() {
  id="$1"; shift
  [ "$JSON" = "0" ] && printf '  ~ %s\n' "$*"
  record skip "$id" "$*"
  SKIP=$((SKIP+1))
}
head_() { [ "$JSON" = "0" ] && printf '\n\033[1m%s\033[0m\n' "$*"; }

json_string() {
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

if [ -f "$VARS" ]; then
  # shellcheck disable=SC1090
  . "$VARS"
fi
ORG="${ORG:-}"; GH_USER="${GH_USER:-}"

[ "$JSON" = "0" ] && echo "▩ wb-setup verify — $(hostname -s) · $(date '+%Y-%m-%d %H:%M')"

# ── phase 0 · permissions ────────────────────────────────────────────────────
head_ "phase 0 · permissions"

AGENT_APP="$HOME/Applications/Wideband Agent.app"
AGENT="$AGENT_APP/Contents/MacOS/Wideband Agent"
AGENT_STATUS="$HOME/.wideband/setup/agent-status.json"
AGENT_READY=0
if [ -x "$AGENT" ]; then
  AGENT_NONCE="$(date '+%Y%m%d%H%M%S')-$$-$RANDOM"
  /usr/bin/open -n "$AGENT_APP" --args report "$AGENT_NONCE" >/dev/null 2>&1 || true
  AGENT_WAIT=0
  while [ "$AGENT_WAIT" -lt 50 ]; do
    if [ -f "$AGENT_STATUS" ] \
       && [ "$(/usr/bin/plutil -extract nonce raw -o - "$AGENT_STATUS" 2>/dev/null)" = "$AGENT_NONCE" ]; then
      AGENT_READY=1
      break
    fi
    AGENT_WAIT=$((AGENT_WAIT + 1))
    sleep 0.1
  done
fi

agent_granted() {
  [ "$AGENT_READY" = "1" ] \
    && [ "$(/usr/bin/plutil -extract "$1" raw -o - "$AGENT_STATUS" 2>/dev/null)" = "true" ]
}

if [ "$AGENT_READY" = "1" ]; then
  if agent_granted full_disk_access; then
    ok P0-FDA "Wideband Agent has Full Disk Access"
  else
    no P0-FDA "Wideband Agent does not have Full Disk Access"
  fi
  if agent_granted accessibility; then
    ok P0-AX "Wideband Agent has Accessibility access"
  else
    no P0-AX "Wideband Agent does not have Accessibility access"
  fi
  if agent_granted screen_capture; then
    ok P0-SCREEN "Wideband Agent has Screen Recording access"
  else
    no P0-SCREEN "Wideband Agent does not have Screen Recording access"
  fi
  if agent_granted automation_messages; then
    ok P0-AUTOMATION "Wideband Agent may automate Messages"
  else
    no P0-AUTOMATION "Wideband Agent may not automate Messages"
  fi
else
  no P0-FDA "Wideband Agent did not produce a fresh permission report"
  no P0-AX "Wideband Agent did not produce a fresh Accessibility report"
  no P0-SCREEN "Wideband Agent did not produce a fresh Screen Recording report"
  no P0-AUTOMATION "Wideband Agent did not produce a fresh Messages Automation report"
fi

# `systemsetup -getremotelogin` needs admin and errors out unprivileged, so it
# can never pass here. Enabling Remote Login is exactly `launchctl enable
# system/com.openssh.sshd`, and the disabled-list is readable without
# privileges. Checking for a listener on :22 does NOT work: sshd is socket-
# activated and the socket belongs to root, so lsof shows an ordinary user
# nothing even when it is on.
if launchctl print-disabled system 2>/dev/null | grep -q '"com.openssh.sshd" => enabled'; then
  ok P0-SSH "Remote Login is on"
elif launchctl print-disabled system 2>/dev/null | grep -q '"com.openssh.sshd" => disabled'; then
  no P0-SSH "Remote Login is off — Settings → General → Sharing → Remote Login"
else
  skip P0-SSH "Remote Login state unreadable"
fi

if launchctl print-disabled system 2>/dev/null | grep -q '"com.apple.screensharing" => enabled'; then
  ok P0-SCREENSHARING "Apple Screen Sharing is on"
elif launchctl print-disabled system 2>/dev/null | grep -q '"com.apple.screensharing" => disabled'; then
  no P0-SCREENSHARING "Apple Screen Sharing is off — Settings → General → Sharing"
else
  skip P0-SCREENSHARING "Apple Screen Sharing state unreadable"
fi

if pmset -g 2>/dev/null | awk '/^ *sleep/{print $2}' | grep -q '^0$'; then
  ok P0-SLEEP "system sleep disabled — scheduled loops will not miss their window"
else
  no P0-SLEEP "system sleeps — 'sudo pmset -a sleep 0' or overnight loops are unreliable"
fi

# ── phase 3 · core CLIs ──────────────────────────────────────────────────────
head_ "phase 3 · core CLIs"
for b in brew node npm git gh jq tmux python3 sqlite3; do
  if command -v "$b" >/dev/null 2>&1; then ok P3-CLI "$b"; else no P3-CLI "$b missing"; fi
done

if command -v gh >/dev/null 2>&1; then
  who="$(gh api user -q .login 2>/dev/null)"
  if [ -z "$who" ]; then
    no P3-GHAUTH "gh is not authenticated (gh auth login)"
  elif [ -n "$GH_USER" ] && [ "$who" != "$GH_USER" ]; then
    ok P3-GHAUTH "gh authenticated as $who"
    no P3-GHUSER "gh is authenticated as '$who' but \$GH_USER is '$GH_USER' — this blocks deploys"
  else
    ok P3-GHAUTH "gh authenticated as $who"
    ok P3-GHUSER "gh identity matches $who"
  fi
fi

# ── phase 4 · tailnet ────────────────────────────────────────────────────────
head_ "phase 4 · tailscale"
TSBIN=""
command -v tailscale >/dev/null 2>&1 && TSBIN="$(command -v tailscale)"
[ -z "$TSBIN" ] && [ -x /Applications/Tailscale.app/Contents/MacOS/Tailscale ] \
  && TSBIN=/Applications/Tailscale.app/Contents/MacOS/Tailscale

if [ -z "$TSBIN" ]; then
  no P4-TSCLI "no tailscale CLI — install the standalone app, not the App Store build"
else
  ok P4-TSCLI "tailscale CLI at $TSBIN"
  if [ "$QUICK" = "1" ]; then
    skip P4-TSSERVE "tailnet checks (--quick)"
  else
    if "$TSBIN" serve status 2>/dev/null | grep -q 'ts\.net'; then
      ok P4-TSSERVE "surfaces served over tailnet HTTPS"
    else
      no P4-TSSERVE "no tailscale serve mappings — phone surfaces will be unreachable"
    fi
  fi
fi

# ── phase 5 · the Claude layer ───────────────────────────────────────────────
head_ "phase 5 · claude layer"

if command -v claude >/dev/null 2>&1 || [ -x "$HOME/.local/bin/claude" ]; then
  ok P5-CLAUDE "claude installed ($(claude --version 2>/dev/null | head -1))"
else
  no P5-CLAUDE "claude not on PATH — check ~/.local/bin in .zshrc"
fi

SL="$HOME/.claude/statusline-command.sh"
# Readable, not executable. settings.json invokes this as `bash <path>`, which
# does not need the +x bit — requiring it fails a setup that works fine.
if [ -r "$SL" ]; then
  ok P5-SL "status line script present"
  # The two documented ways this file breaks. Both are silent at install time
  # and only show up as a blank or literal-escape status line in a session.
  if grep -q "\$'" "$SL"; then
    ok P5-SLCOLOR "status line colors use \$'...' (real ESC bytes)"
  else
    no P5-SLCOLOR "status line colors are not \$'...' — they will print literally"
  fi
  command -v jq >/dev/null 2>&1 \
    && ok P5-SLJQ "jq present — status line can parse its input" \
    || no P5-SLJQ "jq missing — status line will render blank"
else
  no P5-SL "$SL missing"
fi

if [ -f "$HOME/.claude/settings.json" ]; then
  if command -v jq >/dev/null 2>&1; then
    if jq -e '.statusLine.command' "$HOME/.claude/settings.json" >/dev/null 2>&1; then
      ok P5-SETTINGS "settings.json wires the status line"
    else
      no P5-SETTINGS "settings.json has no statusLine block"
    fi
  else
    skip P5-SETTINGS "settings.json present (no jq to inspect it)"
  fi
else
  no P5-SETTINGS "~/.claude/settings.json missing"
fi

# The MD surface, and the 200-line cap. The cap is the point: a file past it
# stops being read, which makes it worse than absent because it reads as covered.
head_ "phase 5 · MD surface (cap: 200 lines)"
for f in "$HOME/.claude/CLAUDE.md" "$HOME/.claude/USER.md"; do
  if [ ! -f "$f" ]; then
    no P5-MD "$(basename "$f") missing — $f"
  else
    n="$(wc -l < "$f" | tr -d ' ')"
    ok P5-MD "$(basename "$f") present"
    if [ "$n" -le 200 ]; then ok P5-MDCAP "$(basename "$f") — $n lines"
    else no P5-MDCAP "$(basename "$f") — $n lines, over the 200 cap"; fi
  fi
done

if [ "$QUICK" = "0" ] && command -v claude >/dev/null 2>&1; then
  n="$(claude mcp list 2>/dev/null | grep -c 'Connected')"
  if [ "${n:-0}" -ge 1 ]; then ok P5-MCP "$n MCP servers connected"
  else no P5-MCP "no MCP servers connected"; fi
else
  skip P5-MCP "MCP server check"
fi

# ── phase 7 · tmux ───────────────────────────────────────────────────────────
head_ "phase 7 · tmux"
[ -f "$HOME/.config/tmux/tmux.conf" ] && ok P7-CONF "tmux.conf placed" || no P7-CONF "~/.config/tmux/tmux.conf missing"
[ -d "$HOME/.config/tmux/plugins/tpm" ] && ok P7-TPM "tpm installed" || no P7-TPM "tpm missing — plugins will not load"
for c in tm tm-standard; do
  [ -x "$HOME/bin/$c" ] && ok P7-TM "$c installed" || no P7-TM "~/bin/$c missing — three tmux keybindings depend on it"
done

SESSIONS="$HOME/.config/tmux-command-center/config/sessions.conf"
if [ ! -f "$SESSIONS" ]; then
  no P7-STD "no session standard at $SESSIONS"
else
  ok P7-STD "session standard present"
fi
if [ -f "$SESSIONS" ] && command -v tmux >/dev/null 2>&1; then
  # Check the standard is actually STANDING, not merely written down. A config
  # listing five sessions and a server running none is the failure this catches.
  live="$(tmux ls -F '#{session_name}' 2>/dev/null)"
  missing=""
  while IFS= read -r line; do
    line="${line%%#*}"
    case "$line" in *=*) ;; *) continue ;; esac
    nm="$(printf '%s' "${line%%=*}" | tr -d '[:space:]')"
    [ -z "$nm" ] && continue
    printf '%s\n' "$live" | grep -qx "$nm" || missing="$missing $nm"
  done < "$SESSIONS"
  if [ -z "$missing" ]; then
    ok P7-SESS "every standard session is running ($(printf '%s' "$live" | grep -c .) live)"
  else
    no P7-SESS "standard sessions not running:$missing  → tm-standard apply"
  fi
fi

# ── phase 8 · loops ──────────────────────────────────────────────────────────
head_ "phase 8 · loops"
if [ -z "$ORG" ]; then
  skip P8-LOAD "no \$ORG set — cannot identify this machine's LaunchAgents"
else
  loaded="$(launchctl list 2>/dev/null | grep -c "com\.$ORG\.")"
  if [ "${loaded:-0}" -eq 0 ]; then
    no P8-LOAD "no com.$ORG.* agents loaded"
  else
    ok P8-LOAD "$loaded com.$ORG.* agents loaded"
    # A loaded job with a non-zero last exit is a broken loop that looks
    # installed. This is the check the whole phase exists for.
    bad="$(launchctl list 2>/dev/null | grep "com\.$ORG\." | awk '$2 != 0 {print $3}')"
    if [ -n "$bad" ]; then
      for l in $bad; do no P8-EXIT "$l is loaded but last exited non-zero"; done
    else
      ok P8-EXIT "every loaded agent last exited clean"
    fi
  fi
fi

# ── PATH ─────────────────────────────────────────────────────────────────────
# A binary on disk that the shell cannot find reports "command not found",
# which reads as "it did not install". Twice on the first live build we chased
# an install that had already succeeded. The distinction is cheap to make and
# nothing was making it.
head_ "PATH"
path_miss=""
for pair in "claude:$HOME/.local/bin/claude" "fleetdeck:$HOME/bin/fleetdeck" \
            "tm:$HOME/bin/tm" "brew:/opt/homebrew/bin/brew"; do
  n="${pair%%:*}"; f="${pair#*:}"
  [ -x "$f" ] || continue
  command -v "$n" >/dev/null 2>&1 || path_miss="$path_miss $n"
done
if [ -z "$path_miss" ]; then
  ok SHELL-PATH "every installed tool is reachable on PATH"
else
  no SHELL-PATH "installed but NOT on this shell's PATH:$path_miss — open a new terminal window"
fi

# ── phase 9 · fleetdeck ──────────────────────────────────────────────────────
head_ "phase 9 · fleetdeck"
if [ ! -x "$HOME/bin/fleetdeck" ]; then
  no P9-FLEET "fleetdeck not installed — the board and the tmux chat are unavailable"
else
  ok P9-FLEET "fleetdeck installed"
  if [ -f "$HOME/srv/fleetdeck/config.json" ] && command -v jq >/dev/null 2>&1; then
    m="$(jq -r '.machine // ""' "$HOME/srv/fleetdeck/config.json" 2>/dev/null)"
    [ -z "$m" ] && ok P9-PINNED "config.json leaves machine empty (resolves from Tailscale)" \
                || no P9-PINNED "config.json pins machine='$m' — the board will break on the next machine"
  fi
fi

# ── summary ──────────────────────────────────────────────────────────────────
if [ "$JSON" = "1" ]; then
  printf '{"schema_version":1,"machine":"%s","generated_at":"%s","quick":%s,"summary":{"passed":%d,"failed":%d,"skipped":%d},"checks":[' \
    "$(json_string "$(hostname -s)")" "$(date '+%Y-%m-%dT%H:%M:%S%z')" \
    "$([ "$QUICK" = "1" ] && printf true || printf false)" "$PASS" "$FAIL" "$SKIP"
  first=1
  while IFS="$(printf '\t')" read -r status id message; do
    [ "$first" = "1" ] || printf ','
    first=0
    printf '{"id":"%s","status":"%s","message":"%s"}' \
      "$(json_string "$id")" "$(json_string "$status")" "$(json_string "$message")"
  done < "$RESULTS"
  printf ']}\n'
else
  printf '\n\033[1m%s\033[0m\n' "─────────────────────────────────────────"
  printf '  %d passed · %d failed · %d skipped\n\n' "$PASS" "$FAIL" "$SKIP"
  [ "$FAIL" -eq 0 ] && echo "  build is complete." || echo "  $FAIL check(s) failed — work them in phase order."
  echo
fi
exit "$FAIL"
