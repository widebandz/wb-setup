#!/bin/bash
# bootstrap.sh — bare M-chip Mac → a live agent, in the shortest path there is.
#
#   curl -fsSL https://raw.githubusercontent.com/widebandz/wb-setup/main/bootstrap.sh | bash
#
# The ordering here is the entire point, and it is not the order the SOP reads
# in. Three resources are in play and they do not contend:
#
#   MACHINE   downloads. Slow, but unattended once started.
#   HUMAN     sign-ins, 2FA, permission dialogs. The scarce one.
#   AGENT     Claude Code. Does the bulk — but only once it is authed.
#
# So: start the agent's installer FIRST (it has zero dependencies and takes
# seconds), throw Homebrew into the background, and hand the human a queue of
# work to do while the download runs. The common mistake is installing Homebrew
# first and waiting on it — Claude Code is not behind it and never was.
#
# TOOL BUDGET: bash, curl, tar, sed, awk, grep. Nothing else, until Homebrew
# lands. A bare macOS has no git and no python3 — /usr/bin/git and
# /usr/bin/python3 are stubs that pop the Command Line Tools dialog and block.
# That is why the repo arrives as a tarball rather than a clone. verify.sh
# asserts this budget, because it is the constraint most likely to regress.
#
# bash 3.2 compatible on purpose: that is what /bin/bash on macOS is, and this
# script runs before a newer one exists.
#
# Idempotent. Safe to re-run.
set -uo pipefail

REPO="widebandz/wb-setup"
TARBALL="https://github.com/$REPO/archive/refs/heads/main.tar.gz"
ROOT="${WB_SETUP_ROOT:-$HOME/srv/wb-setup}"
VARS="$HOME/.sop-vars"
BREW_LOG="/tmp/wb-bootstrap-brew.log"
BREW_PID=""

DO_CLAUDE=1; DO_BREW=1; DO_FETCH=1; ASSUME_YES=0

for arg in "$@"; do
  case "$arg" in
    --no-claude) DO_CLAUDE=0 ;;
    --no-brew)   DO_BREW=0 ;;
    --no-fetch)  DO_FETCH=0 ;;
    --yes|-y)    ASSUME_YES=1 ;;
    --org=*)     export ORG="${arg#*=}" ;;
    --brand=*)   export BRAND="${arg#*=}" ;;
    --gh-user=*) export GH_USER="${arg#*=}" ;;
    --email=*)   export GIT_EMAIL="${arg#*=}" ;;
    --phone=*)   export OPERATOR_PHONE="${arg#*=}" ;;
    --repo=*)    export WORK_REPO="${arg#*=}" ;;
    --pack=*)    export GRAPH_PACK="${arg#*=}" ;;
    --help|-h)
      grep '^#' "$0" | sed 's/^# \{0,1\}//' | sed -n '1,32p'
      exit 0 ;;
    *) echo "  ! unknown flag: $arg (--help for usage)" >&2 ;;
  esac
done

say()  { printf '%s\n' "$*"; }
step() { printf '\n\033[1m%s\033[0m\n' "$*"; }

echo "▩ wb-setup bootstrap — $ROOT"
echo

# ── preflight ────────────────────────────────────────────────────────────────
# Refuse loudly and early. Every check below has produced a confusing
# mid-install failure at least once when it was left implicit.

if [ "$(id -u)" = "0" ]; then
  say "  ✗ REFUSING: running as root."
  say "    Homebrew refuses root, and every file this places would end up owned"
  say "    by root in a home directory the operator cannot write. Re-run as you."
  exit 1
fi

ARCH="$(uname -m)"
if [ "$ARCH" != "arm64" ]; then
  say "  ✗ REFUSING: this machine is $ARCH, not arm64."
  say "    This build targets Apple silicon. On Intel the Homebrew prefix is"
  say "    /usr/local, not /opt/homebrew, and every hardcoded path below is"
  say "    wrong in a way that fails late instead of here."
  exit 1
fi

OSMAJ="$(sw_vers -productVersion 2>/dev/null | awk -F. '{print $1}')"
if [ -z "$OSMAJ" ] || [ "$OSMAJ" -lt 13 ] 2>/dev/null; then
  say "  ✗ REFUSING: macOS $(sw_vers -productVersion 2>/dev/null || echo '?') is below the 13.0 minimum."
  exit 1
fi

case "$ROOT" in
  "$HOME/Documents"/*|"$HOME/Desktop"/*|"$HOME/Downloads"/*)
    say "  ✗ REFUSING: $ROOT is inside a TCC-protected folder."
    say "    launchd cannot read Documents/Desktop/Downloads without a Full Disk"
    say "    Access grant, and the jobs fail in a way that looks like a bug in"
    say "    this tool. Set WB_SETUP_ROOT elsewhere and re-run."
    exit 1 ;;
esac

for t in curl tar sed awk grep; do
  command -v "$t" >/dev/null 2>&1 || { say "  ✗ REFUSING: no $t on PATH."; exit 1; }
done

say "  ✓ arm64 · macOS $(sw_vers -productVersion) · $(id -un)"

# ── 1. the agent, first ──────────────────────────────────────────────────────
# Zero dependencies: no Node, no Homebrew, no Command Line Tools. Seconds.
# This is the step that is conventionally put last and belongs first.

step "1/6  Claude Code"
if [ "$DO_CLAUDE" = "0" ]; then
  say "  ~ skipped (--no-claude)"
elif command -v claude >/dev/null 2>&1 || [ -x "$HOME/.local/bin/claude" ]; then
  say "  = already installed"
else
  if curl -fsSL https://claude.ai/install.sh | bash >/tmp/wb-claude-install.log 2>&1; then
    say "  + ~/.local/bin/claude"
  else
    say "  ! install failed — see /tmp/wb-claude-install.log"
    say "    Everything below still runs; authenticate later with: claude"
  fi
fi

# `command not found: claude` is the single most reported failure, and it is
# always this. Fix it in the file, not just this shell.
if ! grep -qs '\.local/bin' "$HOME/.zshrc" 2>/dev/null; then
  printf '\n# added by wb-setup bootstrap — Claude Code installs here\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$HOME/.zshrc"
  say "  + ~/.local/bin on PATH (~/.zshrc)"
else
  say "  = ~/.local/bin already on PATH"
fi
export PATH="$HOME/.local/bin:$PATH"

# ── 2. Homebrew, in the background ───────────────────────────────────────────
# The long pole, and nothing below waits on it. It pulls the Command Line Tools
# (a large download) on a bare machine, which is most of the wall clock for the
# whole build.

step "2/6  Homebrew + Command Line Tools (background)"
if [ "$DO_BREW" = "0" ]; then
  say "  ~ skipped (--no-brew)"
elif command -v brew >/dev/null 2>&1 || [ -x /opt/homebrew/bin/brew ]; then
  say "  = already installed"
else
  : > "$BREW_LOG"
  # NONINTERACTIVE keeps the installer from waiting on a RETURN nobody is
  # watching — this runs detached and its stdin is not a terminal.
  ( NONINTERACTIVE=1 /bin/bash -c \
      "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" \
      >>"$BREW_LOG" 2>&1 ) &
  BREW_PID=$!
  say "  → started (pid $BREW_PID), logging to $BREW_LOG"
  say "    This is the download to work around, not wait on."
fi

# ── 3. the repo ──────────────────────────────────────────────────────────────
# Tarball, not clone: git does not exist yet. See the tool budget above.

step "3/6  wb-setup"
HERE=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]:-/nonexistent}" ]; then
  HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
fi

if [ -n "$HERE" ] && [ -f "$HERE/Brewfile" ]; then
  ROOT="$HERE"
  say "  = running from the repo at $ROOT"
elif [ "$DO_FETCH" = "0" ]; then
  say "  ~ skipped (--no-fetch)"
else
  mkdir -p "$ROOT"
  if curl -fsSL "$TARBALL" | tar xz -C "$ROOT" --strip-components=1 2>/dev/null; then
    say "  + fetched $REPO → $ROOT"
  else
    say "  ✗ could not fetch $TARBALL"
    say "    The repo is public; this is a network failure or a renamed branch."
    exit 1
  fi
fi

# ── 4. identity ──────────────────────────────────────────────────────────────
# One substitution table. Everything downstream reads from it, which is the
# property that makes the next machine come out the same as this one.

step "4/6  identity → $VARS"

# Piped as `curl … | bash`, stdin IS the script — a bare `read` would eat the
# rest of it and the run would end mid-file. Always read the human from the
# terminal directly.
TTY_OK=0
[ -r /dev/tty ] && TTY_OK=1

ask() {  # ask VAR "prompt" "default"
  local var="$1" prompt="$2" def="$3" cur ans
  eval "cur=\${$var:-}"
  if [ -n "$cur" ]; then say "  = $var=$cur"; return; fi
  if [ "$ASSUME_YES" = "1" ] || [ "$TTY_OK" = "0" ]; then
    eval "export $var=\"\$def\""
    say "  + $var=$def (default)"
    return
  fi
  printf '    %s [%s]: ' "$prompt" "$def" > /dev/tty
  read -r ans < /dev/tty
  [ -z "$ans" ] && ans="$def"
  eval "export $var=\"\$ans\""
}

if [ -f "$VARS" ]; then
  # Never overwrite a curated identity file. Same rule fleetdeck applies to
  # config.json: seed once, then it belongs to the operator.
  # shellcheck disable=SC1090
  . "$VARS"
  say "  = $VARS exists — leaving it alone"
else
  ask ORG            "org slug (names LaunchAgents com.<org>.*)" "acme"
  ask BRAND          "board name"                                "fleetdeck"
  ask MARK           "tmux status mark (one cell)"               "◈"
  ask GH_USER        "GitHub username (the ONLY one on this Mac)" "$ORG"
  ask GIT_EMAIL      "git commit email"                          "ops@$ORG.com"
  ask OPERATOR_PHONE "phone for briefs (E.164)"                  "+15551234567"
  ask WORK_REPO      "work repo (git URL)"                       "git@github.com:$GH_USER/app.git"
  ask GRAPH_PACK     "knowledge-graph pack name"                 "$ORG"

  cat > "$VARS" <<EOF
# Written by wb-setup bootstrap. Edit freely, then re-run install.sh.
# MACHINE and TAILNET are deliberately absent — resolved from Tailscale at
# runtime. Pinning them is how a build stops being portable.
export ORG="$ORG"
export BRAND="$BRAND"
export MARK="$MARK"
export GH_USER="$GH_USER"
export GIT_EMAIL="$GIT_EMAIL"
export OPERATOR_PHONE="$OPERATOR_PHONE"
export WORK_REPO="$WORK_REPO"
export GRAPH_PACK="$GRAPH_PACK"
EOF
  say "  + $VARS"
fi

if ! grep -qs 'sop-vars' "$HOME/.zshrc" 2>/dev/null; then
  printf '\n# added by wb-setup bootstrap\n[ -f ~/.sop-vars ] && source ~/.sop-vars\n' >> "$HOME/.zshrc"
  say "  + sourced from ~/.zshrc"
fi

# ── 5. the artifacts that need no Homebrew ───────────────────────────────────
# Placed now so the agent's first session already has a status line and a
# runbook. The status line stays blank until jq arrives with Homebrew; that is
# expected and verify.sh reports it rather than hiding it.

step "5/6  agent context"
place() {  # place SRC DEST [mode]
  local src="$1" dest="$2" mode="${3:-644}"
  [ -f "$src" ] || { say "  ~ missing in repo: $src"; return; }
  mkdir -p "$(dirname "$dest")"
  if cmp -s "$src" "$dest"; then say "  = $dest"; return; fi
  cp "$src" "$dest" && chmod "$mode" "$dest" && say "  + $dest"
}

place "$ROOT/dotfiles/statusline-command.sh" "$HOME/.claude/statusline-command.sh" 755
place "$ROOT/SOP.md"                          "$HOME/.claude/SOP.md"

# settings.json holds the operator's own plugins, permissions and MCP config.
# Merging into an existing one needs jq, which does not exist yet — so seed it
# only when absent and leave the merge to install.sh, which runs after brew.
if [ -f "$HOME/.claude/settings.json" ]; then
  say "  ~ ~/.claude/settings.json exists — install.sh will merge the statusLine"
elif [ -f "$ROOT/templates/settings.json.tmpl" ]; then
  mkdir -p "$HOME/.claude"
  sed "s|__HOME__|$HOME|g" "$ROOT/templates/settings.json.tmpl" > "$HOME/.claude/settings.json"
  say "  + ~/.claude/settings.json"
fi

if [ -f "$HOME/.claude/CLAUDE.md" ]; then
  say "  = ~/.claude/CLAUDE.md"
elif [ -f "$ROOT/templates/global-claude.md.tmpl" ]; then
  sed -e "s|__ORG__|${ORG:-acme}|g" -e "s|__ROOT__|$ROOT|g" \
      "$ROOT/templates/global-claude.md.tmpl" > "$HOME/.claude/CLAUDE.md"
  say "  + ~/.claude/CLAUDE.md"
fi

# ── 6. the human queue ───────────────────────────────────────────────────────
# The reason this script exists. Downloads are running; the person reading this
# should not be watching them.

step "6/6  do these now, while the download runs"
cat <<'QUEUE'

  These need a human and no network from this machine. Working them now is
  free; working them after the download is pure added wall clock.

  PERMISSIONS  — System Settings. Every one is a dialog, and a missed grant
                 fails silently several phases later.
    1. General → Sharing → Remote Login                          ON
    2. Privacy & Security → Full Disk Access                     Terminal, VS Code
    3. Privacy & Security → Accessibility                        Terminal
    4. Privacy & Security → Screen Recording                     Terminal, VS Code
    5. General → Login Items & Extensions → allow background items
    6. Messages.app → Settings → sign in to iMessage

  ACCOUNTS     — email FIRST; everything else verifies through it.
    7. Apple ID / iCloud            8. email — send yourself one, confirm
    9. GitHub (as $GH_USER only)   10. Anthropic (Pro/Max, or API key)
   11. Tailscale                   12. Vercel · Supabase

  THEN, the moment Claude Code is installed:
       claude          → browser login → the agent is live

QUEUE

# ── wait on Homebrew ─────────────────────────────────────────────────────────
if [ -n "$BREW_PID" ]; then
  say "  … waiting on Homebrew (pid $BREW_PID). tail -f $BREW_LOG to watch."
  wait "$BREW_PID"; brew_rc=$?
  if [ "$brew_rc" = "0" ]; then say "  ✓ Homebrew installed"
  else say "  ! Homebrew exited $brew_rc — see $BREW_LOG"; fi
fi

BREW_BIN=""
[ -x /opt/homebrew/bin/brew ] && BREW_BIN=/opt/homebrew/bin/brew
if [ -n "$BREW_BIN" ]; then
  eval "$("$BREW_BIN" shellenv)"
  if ! grep -qs 'brew shellenv' "$HOME/.zprofile" 2>/dev/null; then
    printf '\neval "$(/opt/homebrew/bin/brew shellenv)"\n' >> "$HOME/.zprofile"
    say "  + brew shellenv → ~/.zprofile"
  fi
  if [ "$DO_BREW" = "1" ] && [ -f "$ROOT/Brewfile" ]; then
    say "  … brew bundle"
    if brew bundle --file="$ROOT/Brewfile" >>"$BREW_LOG" 2>&1; then
      say "  ✓ core CLIs installed"
    else
      say "  ! brew bundle had failures — see $BREW_LOG"
    fi
  fi
fi

# ── handoff ──────────────────────────────────────────────────────────────────
cat <<EOF

▩ bootstrap done.

  Next, in this order:

    claude
        authenticate in the browser — the agent is live from here

    bash $ROOT/verify.sh
        what is actually true on this machine, phase by phase

    bash $ROOT/install.sh
        phase 5 (claude layer), 7 (tmux), 8 (loops) — once brew and auth are in
        phases 6, 9 and 10 are still hands-on; the SOP has them

  The agent's runbook is ~/.claude/SOP.md. Point it there:

    "Read ~/.claude/SOP.md and run verify.sh. Work the phases that fail,
     in order, stopping at anything that needs me."

EOF
