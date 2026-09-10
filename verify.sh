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
#
# A verifier that reports all green on a machine with known gaps is broken. If
# this prints nothing but ✓ on a fresh build, distrust it before trusting it.
set -uo pipefail

QUICK=0
[ "${1:-}" = "--quick" ] && QUICK=1

VARS="$HOME/.sop-vars"
PASS=0; FAIL=0; SKIP=0

ok()   { printf '  ✓ %s\n' "$*"; PASS=$((PASS+1)); }
# no() takes a stable check ID first, then the message. The ID is the lookup
# key into TROUBLESHOOTING.md — an agent reading this output gets a section to
# open rather than a sentence to pattern-match. selftest.sh asserts every ID
# here has a section there, and that every section maps back to a live check,
# so the guide cannot drift out of sync without failing the suite.
no()   { printf '  ✗ [%s] %s\n' "$1" "${*:2}"; FAIL=$((FAIL+1)); }
skip() { printf '  ~ %s\n' "$*"; SKIP=$((SKIP+1)); }
head_() { printf '\n\033[1m%s\033[0m\n' "$*"; }

if [ -f "$VARS" ]; then
  # shellcheck disable=SC1090
  . "$VARS"
fi
ORG="${ORG:-}"; GH_USER="${GH_USER:-}"

echo "▩ wb-setup verify — $(hostname -s) · $(date '+%Y-%m-%d %H:%M')"

# ── phase 0 · permissions ────────────────────────────────────────────────────
head_ "phase 0 · permissions"

if sqlite3 "$HOME/Library/Messages/chat.db" "select count(*) from message;" >/dev/null 2>&1; then
  ok "Full Disk Access — chat.db is readable"
else
  no P0-FDA "Full Disk Access — cannot read ~/Library/Messages/chat.db (message scanning will return nothing)"
fi

# `systemsetup -getremotelogin` needs admin and errors out unprivileged, so it
# can never pass here. Enabling Remote Login is exactly `launchctl enable
# system/com.openssh.sshd`, and the disabled-list is readable without
# privileges. Checking for a listener on :22 does NOT work: sshd is socket-
# activated and the socket belongs to root, so lsof shows an ordinary user
# nothing even when it is on.
if launchctl print-disabled system 2>/dev/null | grep -q '"com.openssh.sshd" => enabled'; then
  ok "Remote Login is on"
elif launchctl print-disabled system 2>/dev/null | grep -q '"com.openssh.sshd" => disabled'; then
  no P0-SSH "Remote Login is off — Settings → General → Sharing → Remote Login"
else
  skip "Remote Login state unreadable"
fi

if pmset -g 2>/dev/null | awk '/^ *sleep/{print $2}' | grep -q '^0$'; then
  ok "system sleep disabled — scheduled loops will not miss their window"
else
  no P0-SLEEP "system sleeps — 'sudo pmset -a sleep 0' or overnight loops are unreliable"
fi

# ── phase 3 · core CLIs ──────────────────────────────────────────────────────
head_ "phase 3 · core CLIs"
for b in brew node npm git gh jq tmux python3 sqlite3; do
  if command -v "$b" >/dev/null 2>&1; then ok "$b"; else no P3-CLI "$b missing"; fi
done

if command -v gh >/dev/null 2>&1; then
  who="$(gh api user -q .login 2>/dev/null)"
  if [ -z "$who" ]; then
    no P3-GHAUTH "gh is not authenticated (gh auth login)"
  elif [ -n "$GH_USER" ] && [ "$who" != "$GH_USER" ]; then
    no P3-GHUSER "gh is authenticated as '$who' but \$GH_USER is '$GH_USER' — this blocks deploys"
  else
    ok "gh authenticated as $who"
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
elif [ "$QUICK" = "1" ]; then
  skip "tailnet checks (--quick)"
else
  ok "tailscale CLI at $TSBIN"
  if "$TSBIN" serve status 2>/dev/null | grep -q 'ts\.net'; then
    ok "surfaces served over tailnet HTTPS"
  else
    no P4-TSSERVE "no tailscale serve mappings — phone surfaces will be unreachable"
  fi
fi

# ── phase 5 · the Claude layer ───────────────────────────────────────────────
head_ "phase 5 · claude layer"

if command -v claude >/dev/null 2>&1 || [ -x "$HOME/.local/bin/claude" ]; then
  ok "claude installed ($(claude --version 2>/dev/null | head -1))"
else
  no P5-CLAUDE "claude not on PATH — check ~/.local/bin in .zshrc"
fi

SL="$HOME/.claude/statusline-command.sh"
# Readable, not executable. settings.json invokes this as `bash <path>`, which
# does not need the +x bit — requiring it fails a setup that works fine.
if [ -r "$SL" ]; then
  ok "status line script present"
  # The two documented ways this file breaks. Both are silent at install time
  # and only show up as a blank or literal-escape status line in a session.
  if grep -q "\$'" "$SL"; then
    ok "status line colors use \$'...' (real ESC bytes)"
  else
    no P5-SLCOLOR "status line colors are not \$'...' — they will print literally"
  fi
  command -v jq >/dev/null 2>&1 \
    && ok "jq present — status line can parse its input" \
    || no P5-SLJQ "jq missing — status line will render blank"
else
  no P5-SL "$SL missing"
fi

if [ -f "$HOME/.claude/settings.json" ]; then
  if command -v jq >/dev/null 2>&1; then
    if jq -e '.statusLine.command' "$HOME/.claude/settings.json" >/dev/null 2>&1; then
      ok "settings.json wires the status line"
    else
      no P5-SETTINGS "settings.json has no statusLine block"
    fi
  else
    skip "settings.json present (no jq to inspect it)"
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
    if [ "$n" -le 200 ]; then ok "$(basename "$f") — $n lines"
    else no P5-MDCAP "$(basename "$f") — $n lines, over the 200 cap"; fi
  fi
done

if [ "$QUICK" = "0" ] && command -v claude >/dev/null 2>&1; then
  n="$(claude mcp list 2>/dev/null | grep -c 'Connected')"
  if [ "${n:-0}" -ge 1 ]; then ok "$n MCP servers connected"
  else no P5-MCP "no MCP servers connected"; fi
else
  skip "MCP server check"
fi

# ── phase 7 · tmux ───────────────────────────────────────────────────────────
head_ "phase 7 · tmux"
[ -f "$HOME/.config/tmux/tmux.conf" ] && ok "tmux.conf placed" || no P7-CONF "~/.config/tmux/tmux.conf missing"
[ -d "$HOME/.config/tmux/plugins/tpm" ] && ok "tpm installed" || no P7-TPM "tpm missing — plugins will not load"
for c in tm tm-standard; do
  [ -x "$HOME/bin/$c" ] && ok "$c installed" || no P7-TM "~/bin/$c missing — three tmux keybindings depend on it"
done

SESSIONS="$HOME/.config/tmux-command-center/config/sessions.conf"
if [ ! -f "$SESSIONS" ]; then
  no P7-STD "no session standard at $SESSIONS"
elif command -v tmux >/dev/null 2>&1; then
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
    ok "every standard session is running ($(printf '%s' "$live" | grep -c .) live)"
  else
    no P7-SESS "standard sessions not running:$missing  → tm-standard apply"
  fi
fi

# ── phase 8 · loops ──────────────────────────────────────────────────────────
head_ "phase 8 · loops"
if [ -z "$ORG" ]; then
  skip "no \$ORG set — cannot identify this machine's LaunchAgents"
else
  loaded="$(launchctl list 2>/dev/null | grep -c "com\.$ORG\.")"
  if [ "${loaded:-0}" -eq 0 ]; then
    no P8-LOAD "no com.$ORG.* agents loaded"
  else
    ok "$loaded com.$ORG.* agents loaded"
    # A loaded job with a non-zero last exit is a broken loop that looks
    # installed. This is the check the whole phase exists for.
    bad="$(launchctl list 2>/dev/null | grep "com\.$ORG\." | awk '$2 != 0 {print $3}')"
    if [ -n "$bad" ]; then
      for l in $bad; do no P8-EXIT "$l is loaded but last exited non-zero"; done
    else
      ok "every loaded agent last exited clean"
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
  ok "every installed tool is reachable on PATH"
else
  no SHELL-PATH "installed but NOT on this shell's PATH:$path_miss — open a new terminal window"
fi

# ── phase 9 · fleetdeck ──────────────────────────────────────────────────────
head_ "phase 9 · fleetdeck"
if [ ! -x "$HOME/bin/fleetdeck" ]; then
  no P9-FLEET "fleetdeck not installed — the board and the tmux chat are unavailable"
else
  ok "fleetdeck installed"
  if [ -f "$HOME/srv/fleetdeck/config.json" ] && command -v jq >/dev/null 2>&1; then
    m="$(jq -r '.machine // ""' "$HOME/srv/fleetdeck/config.json" 2>/dev/null)"
    [ -z "$m" ] && ok "config.json leaves machine empty (resolves from Tailscale)" \
                || no P9-PINNED "config.json pins machine='$m' — the board will break on the next machine"
  fi
fi

# ── summary ──────────────────────────────────────────────────────────────────
printf '\n\033[1m%s\033[0m\n' "─────────────────────────────────────────"
printf '  %d passed · %d failed · %d skipped\n\n' "$PASS" "$FAIL" "$SKIP"
[ "$FAIL" -eq 0 ] && echo "  build is complete." || echo "  $FAIL check(s) failed — work them in phase order."
echo
exit "$FAIL"
