#!/bin/bash
# doctor.sh — everything about this machine's state, in one pasteable block.
#
#   bash doctor.sh              the full dump
#   bash doctor.sh > /tmp/d.txt then paste it to the agent, or to whoever is helping
#
# verify.sh answers "is it right?" with a pass/fail per check. This answers
# "what IS it?" with no judgement at all, because the failures that are hard to
# diagnose are the ones where every individual check passes and the combination
# is still wrong.
#
# DIAGNOSES, NEVER FIXES. Nothing here installs, loads, copies or writes outside
# /tmp. Detection and remediation stay separate on purpose: a diagnostic that
# repairs as it goes destroys the evidence of what was broken, and you learn
# nothing about why it happened again next month. selftest.sh asserts this
# property statically.
#
# Two things it reports that a naive check gets wrong:
#
#   RESOLVED REAL PATHS, not `command -v`. macOS attributes TCC grants to a
#   binary's resolved real path, so a symlinked or wrapper-shadowed tool holds
#   a grant the thing you are actually running does not have. The real path is
#   the diagnostic.
#
#   LAST EXIT CODES from launchctl, not just "is it loaded". A loaded job with
#   a non-zero last exit is a broken loop that looks installed, which is the
#   single most common silent failure in this build.
set -uo pipefail

VARS="$HOME/.sop-vars"
if [ -f "$VARS" ]; then
  # shellcheck disable=SC1090
  . "$VARS"
fi
ORG="${ORG:-}"; GH_USER="${GH_USER:-}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

sec() { printf '\n\033[1m── %s %s\033[0m\n' "$1" "$(printf '%.0s─' $(seq 1 $((60 - ${#1}))))"; }
kv()  { printf '  %-22s %s\n' "$1" "$2"; }

# Resolved real path — what TCC actually sees.
realpath_of() {
  local p="$1" t
  [ -n "$p" ] || { echo "-"; return; }
  t="$p"
  while [ -L "$t" ]; do t="$(readlink "$t")"; case "$t" in /*) ;; *) t="$(dirname "$p")/$t" ;; esac; done
  echo "$t"
}

echo "▩ wb-setup doctor — $(hostname -s) · $(date '+%Y-%m-%d %H:%M:%S %Z')"

# ── machine ──────────────────────────────────────────────────────────────────
sec "machine"
kv "macOS"      "$(sw_vers -productVersion 2>/dev/null) ($(sw_vers -buildVersion 2>/dev/null))"
kv "arch"       "$(uname -m)"
kv "user"       "$(id -un) (uid $(id -u))"
kv "admin"      "$(id -Gn 2>/dev/null | tr ' ' '\n' | grep -qx admin && echo yes || echo 'NO — most of the build needs it')"
kv "uptime"     "$(uptime | sed 's/^ *//')"
kv "disk free"  "$(df -h / 2>/dev/null | awk 'NR==2{print $4" of "$2" ("$5" used)"}')"
kv "sleep"      "$(pmset -g 2>/dev/null | awk '/^ *sleep/{print $2}' | head -1)"

# ── identity ─────────────────────────────────────────────────────────────────
sec "identity"
if [ -f "$VARS" ]; then
  kv "~/.sop-vars" "present"
  for v in ORG BRAND MARK GH_USER GIT_EMAIL WORK_REPO GRAPH_PACK; do
    eval "val=\${$v:-}"
    # OPERATOR_PHONE deliberately omitted — this output gets pasted around.
    kv "  $v" "${val:-(unset)}"
  done
  eval "ph=\${OPERATOR_PHONE:-}"
  kv "  OPERATOR_PHONE" "$([ -n "$ph" ] && echo 'set (redacted)' || echo '(unset)')"
else
  kv "~/.sop-vars" "MISSING — nothing downstream can render"
fi
kv "git user.name"  "$(git config --global user.name 2>/dev/null || echo -)"
kv "git user.email" "$(git config --global user.email 2>/dev/null || echo -)"
if command -v gh >/dev/null 2>&1; then
  who="$(gh api user -q .login 2>/dev/null)"
  if [ -z "$who" ]; then kv "gh auth" "NOT AUTHENTICATED"
  elif [ -n "$GH_USER" ] && [ "$who" != "$GH_USER" ]; then
    kv "gh auth" "$who  ← MISMATCH, \$GH_USER is $GH_USER"
  else kv "gh auth" "$who"; fi
else
  kv "gh auth" "gh not installed"
fi

# ── tools, by resolved real path ─────────────────────────────────────────────
sec "tools (resolved real path)"
for b in brew node npm git gh jq tmux python3 sqlite3 claude ttyd ffmpeg tm tm-standard; do
  w="$(command -v "$b" 2>/dev/null || true)"
  if [ -z "$w" ]; then
    printf '  %-14s %s\n' "$b" "MISSING"
  else
    r="$(realpath_of "$w")"
    if [ "$r" != "$w" ]; then printf '  %-14s %s  →  %s\n' "$b" "$w" "$r"
    else printf '  %-14s %s\n' "$b" "$w"; fi
  fi
done
TSBIN="/Applications/Tailscale.app/Contents/MacOS/Tailscale"
[ -x "$TSBIN" ] && printf '  %-14s %s\n' "tailscale.app" "$TSBIN" \
                || printf '  %-14s %s\n' "tailscale.app" "NOT INSTALLED (App Store build ships no CLI)"

# ── permissions ──────────────────────────────────────────────────────────────
sec "permissions (TCC)"
if sqlite3 "$HOME/Library/Messages/chat.db" "select count(*) from message;" >/dev/null 2>&1; then
  kv "Full Disk Access" "granted (chat.db readable)"
else
  kv "Full Disk Access" "NOT granted to this terminal — or it was granted after this process started"
fi
if osascript -e 'tell application "System Events" to get name' >/dev/null 2>&1; then
  kv "Automation" "granted (System Events answered)"
else
  kv "Automation" "NOT granted — the agent cannot drive Messages"
fi
if launchctl print-disabled system 2>/dev/null | grep -q '"com.openssh.sshd" => enabled'; then
  kv "Remote Login" "on"
elif launchctl print-disabled system 2>/dev/null | grep -q '"com.openssh.sshd" => disabled'; then
  kv "Remote Login" "OFF"
else
  kv "Remote Login" "unreadable"
fi

# ── launchd ──────────────────────────────────────────────────────────────────
sec "launchd${ORG:+ (com.$ORG.*)}"
if [ -z "$ORG" ]; then
  echo "  no \$ORG in ~/.sop-vars — cannot identify this machine's agents"
else
  found="$(launchctl list 2>/dev/null | grep "com\.$ORG\." || true)"
  if [ -z "$found" ]; then
    echo "  none loaded"
  else
    printf '  %-8s %-6s %s\n' "PID" "EXIT" "LABEL"
    printf '%s\n' "$found" | awk '{printf "  %-8s %-6s %s%s\n",$1,$2,$3,($2!=0?"   ← FAILING":"")}'
  fi
  echo
  for f in "$HOME/Library/LaunchAgents/com.$ORG."*.plist; do
    [ -e "$f" ] || { echo "  (no plists installed)"; break; }
    printf '  plist  %s\n' "$(basename "$f")"
  done
fi

# ── loop logs ────────────────────────────────────────────────────────────────
sec "loop logs (last 3 lines each)"
shown=0
for f in /tmp/com."$ORG".*.log "$HOME/.config/tmux/health.log"; do
  [ -f "$f" ] || continue
  shown=1
  printf '  %s\n' "$f"
  tail -n 3 "$f" 2>/dev/null | sed 's/^/      /'
done
[ "$shown" = 0 ] && echo "  no loop logs yet — nothing has fired"

# ── network ──────────────────────────────────────────────────────────────────
sec "tailnet"
if [ -x "$TSBIN" ]; then
  # `status --json` is pretty-printed, so the key/value separator is `": "` and
  # not `":"`. A pattern without the space silently matches nothing and prints
  # an empty field, which reads as "Tailscale is down" when it is fine.
  tsjson="$("$TSBIN" status --json 2>/dev/null)"
  kv "backend" "$(printf '%s' "$tsjson" | sed -n 's/.*"BackendState": *"\([^"]*\)".*/\1/p' | head -1)"
  kv "self"    "$(printf '%s' "$tsjson" | sed -n 's/.*"DNSName": *"\([^"]*\)".*/\1/p' | head -1 | sed 's/\.$//')"
  echo
  "$TSBIN" serve status 2>/dev/null | sed 's/^/  /' || echo "  (serve status unavailable)"
else
  echo "  no Tailscale CLI"
fi

# ── tmux ─────────────────────────────────────────────────────────────────────
sec "tmux"
if command -v tmux >/dev/null 2>&1 && tmux has-session 2>/dev/null; then
  kv "live sessions" "$(tmux ls 2>/dev/null | wc -l | tr -d ' ')"
  tmux ls 2>/dev/null | sed 's/^/      /'
else
  kv "server" "DOWN — no sessions"
fi
STD="$HOME/.config/tmux-command-center/config/sessions.conf"
echo
if [ -f "$STD" ]; then
  kv "standard" "$STD"
  if [ -x "$HOME/bin/tm-standard" ]; then
    "$HOME/bin/tm-standard" 2>/dev/null | sed 's/^/      /' | head -14
  fi
else
  kv "standard" "MISSING"
fi

# ── drift: installed vs repo ─────────────────────────────────────────────────
sec "drift (installed vs $HERE)"
drift_check() {  # drift_check REPO_FILE INSTALLED_FILE
  local a="$1" b="$2"
  if [ ! -f "$b" ]; then printf '  %-46s %s\n' "$(basename "$b")" "NOT INSTALLED"; return; fi
  if [ ! -f "$a" ]; then printf '  %-46s %s\n' "$(basename "$b")" "no repo copy"; return; fi
  if cmp -s "$a" "$b"; then printf '  %-46s %s\n' "$(basename "$b")" "= matches repo"
  else printf '  %-46s %s\n' "$(basename "$b")" "DIFFERS from repo"; fi
}
# Only files copied verbatim. Rendered templates always differ from their
# source by design, so comparing those would report permanent false drift.
drift_check "$HERE/dotfiles/statusline-command.sh" "$HOME/.claude/statusline-command.sh"
drift_check "$HERE/dotfiles/shell.zsh"             "$HOME/.config/wb-setup/shell.zsh"
drift_check "$HERE/SOP.md"                          "$HOME/.claude/SOP.md"
drift_check "$HERE/bin/tm"                          "$HOME/bin/tm"
drift_check "$HERE/bin/tm-standard"                 "$HOME/bin/tm-standard"

# ── the verdict ──────────────────────────────────────────────────────────────
sec "verify.sh"
if [ -f "$HERE/verify.sh" ]; then
  bash "$HERE/verify.sh" --quick 2>&1 | grep -E '✗|passed|failed' | sed 's/^/  /'
  echo
  echo "  Each [ID] above has a section in TROUBLESHOOTING.md."
else
  echo "  verify.sh not found next to doctor.sh"
fi

echo
