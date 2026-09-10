#!/bin/bash
# install.sh — reconcile this machine with this repo.
#
# Runs AFTER bootstrap.sh: Homebrew exists, jq exists, Claude Code is authed.
# Everything here either needs one of those or needs to merge into a file the
# operator may already own.
#
# The repo is the source of truth. Rendered artifacts are COPIES, not symlinks:
# macOS attributes TCC grants to a binary's resolved real path, and symlinking a
# launchd job's program into a different real path invites the exact failure
# where a grant silently stops applying. `verify.sh` reports drift instead,
# which is the cheap half of that trade.
#
# Idempotent. Safe to re-run. Does not touch tmux sessions.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VARS="$HOME/.sop-vars"
LA="$HOME/Library/LaunchAgents"
UID_N="$(id -u)"

echo "▩ wb-setup — installing from $HERE"
echo

# ── preflight ────────────────────────────────────────────────────────────────
if [ ! -f "$VARS" ]; then
  echo "  ✗ REFUSING: no $VARS."
  echo "    Identity has to exist before anything is rendered from it. Run"
  echo "    bootstrap.sh first, or copy vars.example to $VARS and edit it."
  exit 1
fi
# shellcheck disable=SC1090
. "$VARS"

for v in ORG BRAND GH_USER OPERATOR_PHONE; do
  eval "val=\${$v:-}"
  [ -n "$val" ] || { echo "  ✗ REFUSING: $v is empty in $VARS"; exit 1; }
done

miss=0
for b in jq tmux git; do
  command -v "$b" >/dev/null 2>&1 || { echo "  ✗ missing: $b   (brew install $b)"; miss=1; }
done
[ "$miss" = 0 ] || { echo; echo "install the missing tools, then re-run."; exit 1; }

PREFIX="com.$ORG"
PY="$(command -v python3 || echo /usr/bin/python3)"
MARK="${MARK:-◈}"
# Where the work repo lives — the root the `website` session opens in.
APP_DIR="${APP_DIR:-$HOME/app}"

echo "  prefix     $PREFIX"
echo "  brand      $BRAND"
echo "  python3    $PY"
echo

mkdir -p "$LA" "$HOME/.claude" "$HOME/.config/tmux"

# place SRC DEST [mode] — copy only on difference, so a re-run is quiet.
place() {
  local src="$1" dest="$2" mode="${3:-644}"
  [ -f "$src" ] || { echo "  ~ missing in repo: $src"; return; }
  mkdir -p "$(dirname "$dest")"
  if cmp -s "$src" "$dest"; then echo "  = $dest"; return; fi
  cp "$src" "$dest" && chmod "$mode" "$dest" && echo "  + $dest"
}

# render TMPL DEST [mode] — substitute, then place only on difference.
render() {
  local tmpl="$1" dest="$2" mode="${3:-644}" tmp
  [ -f "$tmpl" ] || { echo "  ~ missing in repo: $tmpl"; return; }
  tmp="$(mktemp)"
  sed -e "s|__ROOT__|$HERE|g" \
      -e "s|__HOME__|$HOME|g" \
      -e "s|__PREFIX__|$PREFIX|g" \
      -e "s|__PYTHON__|$PY|g" \
      -e "s|__ORG__|$ORG|g" \
      -e "s|__BRAND__|$BRAND|g" \
      -e "s|__MARK__|$MARK|g" \
      -e "s|__APP_DIR__|$APP_DIR|g" \
      "$tmpl" > "$tmp"
  mkdir -p "$(dirname "$dest")"
  if cmp -s "$tmp" "$dest"; then echo "  = $dest"
  else cp "$tmp" "$dest" && chmod "$mode" "$dest" && echo "  + $dest"; fi
  rm -f "$tmp"
}

# ── the Claude layer ─────────────────────────────────────────────────────────
echo "claude layer"
place  "$HERE/dotfiles/statusline-command.sh" "$HOME/.claude/statusline-command.sh" 755
place  "$HERE/SOP.md"                          "$HOME/.claude/SOP.md"
render "$HERE/templates/global-claude.md.tmpl" "$HOME/.claude/CLAUDE.md"

# settings.json belongs to the operator — it carries their MCP servers,
# permissions and plugin choices. Merge our two keys in rather than replacing
# the file, which is why this step waits for jq instead of running in bootstrap.
SETTINGS="$HOME/.claude/settings.json"
if [ ! -f "$SETTINGS" ]; then
  render "$HERE/templates/settings.json.tmpl" "$SETTINGS"
else
  tmp="$(mktemp)"
  if jq --arg cmd "bash $HOME/.claude/statusline-command.sh" '
        .statusLine = {type: "command", command: $cmd}
        | .enabledPlugins = ((.enabledPlugins // {}) + {
            "frontend-design@claude-plugins-official": true,
            "supabase@claude-plugins-official": true,
            "vercel@claude-plugins-official": true,
            "claude-code-setup@claude-plugins-official": true
          })' "$SETTINGS" > "$tmp" 2>/dev/null; then
    if cmp -s "$tmp" "$SETTINGS"; then echo "  = $SETTINGS"
    else cp "$tmp" "$SETTINGS" && echo "  + $SETTINGS (merged)"; fi
  else
    echo "  ! $SETTINGS is not valid JSON — left untouched"
  fi
  rm -f "$tmp"
fi

# ── tmux ─────────────────────────────────────────────────────────────────────
echo
echo "tmux"
render "$HERE/templates/tmux.conf.tmpl" "$HOME/.config/tmux/tmux.conf"

# The command-center CLI. Copied to ~/bin rather than symlinked into the brew
# prefix: a symlink there is clobberable by brew, and the SOP's copies-not-
# symlinks rule exists because TCC grants follow a binary's resolved real path.
mkdir -p "$HOME/bin"
place "$HERE/bin/tm"          "$HOME/bin/tm"          755
place "$HERE/bin/tm-standard" "$HOME/bin/tm-standard" 755
place "$HERE/dotfiles/shell.zsh" "$HOME/.config/wb-setup/shell.zsh"
if ! grep -qs 'wb-setup/shell.zsh' "$HOME/.zshrc" 2>/dev/null; then
  printf '\n# added by wb-setup\n[ -f ~/.config/wb-setup/shell.zsh ] && source ~/.config/wb-setup/shell.zsh\n' >> "$HOME/.zshrc"
  echo "  + shell.zsh sourced from ~/.zshrc"
fi
if ! grep -qs 'HOME/bin' "$HOME/.zshrc" 2>/dev/null; then
  printf '\n# added by wb-setup — operator commands\nexport PATH="$HOME/bin:$PATH"\n' >> "$HOME/.zshrc"
  echo "  + ~/bin on PATH (~/.zshrc)"
fi

# The session standard. Seeded once, then it belongs to the operator — the same
# rule config.json gets. `tm-standard save` is how it changes after that, and
# re-running install.sh must not undo a curated set.
SESSIONS="$HOME/.config/tmux-command-center/config/sessions.conf"
if [ -f "$SESSIONS" ]; then
  echo "  = $SESSIONS (operator's — left alone)"
else
  render "$HERE/templates/sessions.conf.tmpl" "$SESSIONS"
fi

TPM="$HOME/.config/tmux/plugins/tpm"
if [ -d "$TPM/.git" ]; then
  echo "  = $TPM"
else
  if git clone -q --depth 1 https://github.com/tmux-plugins/tpm "$TPM" 2>/dev/null; then
    echo "  + $TPM"
    echo "    press prefix + I inside tmux once to fetch the plugin set"
  else
    echo "  ! could not clone tpm — plugins will not load"
  fi
fi

# ── loops ────────────────────────────────────────────────────────────────────
echo
echo "loops"
for src in "$HERE"/loops/*; do
  [ -f "$src" ] || continue
  chmod +x "$src"
  base="$(basename "$src")"
  tmpl="$HERE/templates/launchagents/$base.plist.tmpl"
  [ -f "$tmpl" ] || { echo "  ~ $base has no plist template — not scheduled"; continue; }
  render "$tmpl" "$LA/$PREFIX.$base.plist"
done

echo
echo "loading agents…"
for src in "$HERE"/loops/*; do
  [ -f "$src" ] || continue
  base="$(basename "$src")"
  l="$PREFIX.$base"
  [ -f "$LA/$l.plist" ] || continue
  if launchctl print "gui/$UID_N/$l" >/dev/null 2>&1; then
    launchctl bootout "gui/$UID_N/$l" 2>/dev/null
    # bootout is ASYNCHRONOUS. Bootstrapping before the old job has finished
    # tearing down fails, and there is nothing loaded to kickstart as a
    # fallback. Wait for it to actually be gone.
    for _ in $(seq 20); do
      launchctl print "gui/$UID_N/$l" >/dev/null 2>&1 || break
      sleep 0.3
    done
  fi
  if err="$(launchctl bootstrap "gui/$UID_N" "$LA/$l.plist" 2>&1)"; then
    echo "  ✓ $l"
  else
    echo "  ! $l FAILED to load: ${err:-unknown}"
  fi
done

# ── fleetdeck ────────────────────────────────────────────────────────────────
# Every value it needs is already in ~/.sop-vars, so there is nothing here for
# a human to decide. `machine` is deliberately left EMPTY — fleetdeck resolves
# it from Tailscale at boot, and pinning it is how a board works on the machine
# that built it and nowhere else.
echo
echo "fleetdeck"
FD="$HOME/srv/fleetdeck"
if [ "${NO_FLEETDECK:-0}" = "1" ]; then
  echo "  ~ skipped (NO_FLEETDECK=1)"
else
  if [ -d "$FD/.git" ]; then
    echo "  = $FD"
  elif git clone -q https://github.com/widebandz/fleetdeck.git "$FD" 2>/dev/null; then
    echo "  + $FD"
  else
    echo "  ! could not clone fleetdeck — skipping"
  fi

  if [ -d "$FD" ]; then
    # Seed once, then it belongs to the operator — the same rule sessions.conf
    # and ~/.sop-vars get. Re-running must not flatten a curated board.
    if [ -f "$FD/config.json" ]; then
      echo "  = config.json (operator's — left alone)"
    elif [ -f "$FD/config.example.json" ]; then
      if jq --arg b "$BRAND" --arg p "$PREFIX" \
            '.brand=$b | .label_prefix=$p | .machine=""' \
            "$FD/config.example.json" > "$FD/config.json" 2>/dev/null; then
        echo "  + config.json (brand=$BRAND · prefix=$PREFIX · machine=auto)"
      else
        echo "  ! could not write config.json"
      fi
    fi

    # fleetdeck's installer ends with `exec fleetdeck doctor`, so its exit code
    # reports surface health rather than install success. Judge the object.
    ( cd "$FD" && ./install.sh ) >/tmp/wb-fleetdeck-install.log 2>&1 || true
    if [ -x "$HOME/bin/fleetdeck" ]; then
      echo "  ✓ fleetdeck installed — fleetdeck url"
    else
      echo "  ! fleetdeck did not install — see /tmp/wb-fleetdeck-install.log"
    fi
  fi
fi

echo
echo "──────────────────────────────────────────────────────────"
echo "  OPEN A NEW TERMINAL WINDOW before using tm, fleetdeck or"
echo "  claude. This one was started before they were on PATH, so"
echo "  it will say 'command not found' for tools that are"
echo "  installed and working."
echo "──────────────────────────────────────────────────────────"
echo
exec bash "$HERE/verify.sh"
