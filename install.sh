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

RUN_VERIFY=1
for arg in "$@"; do
  case "$arg" in
    --no-verify) RUN_VERIFY=0 ;;
    --help|-h)
      echo "usage: bash install.sh [--no-verify]"
      exit 0 ;;
    *)
      echo "unknown option: $arg" >&2
      exit 2 ;;
  esac
done

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
chmod 600 "$VARS" 2>/dev/null || { echo "  ✗ cannot make $VARS private"; exit 1; }
# shellcheck disable=SC1090
. "$VARS"

for v in ORG BRAND MARK GH_USER GIT_EMAIL OPERATOR_PHONE WORK_REPO GRAPH_PACK; do
  eval "val=\${$v:-}"
  [ -z "$val" ] && continue
  printf '%s' "$val" | grep -q '[[:cntrl:]]' \
    && { echo "  ✗ REFUSING: $v contains a control character in $VARS"; exit 1; }
done
for v in ORG BRAND GH_USER OPERATOR_PHONE; do
  eval "val=\${$v:-}"
  [ -n "$val" ] || { echo "  ✗ REFUSING: $v is empty in $VARS"; exit 1; }
done
printf '%s' "$ORG" | grep -Eq '^[a-z][a-z0-9-]{0,30}$' \
  || { echo "  ✗ REFUSING: ORG must be a lowercase slug in $VARS"; exit 1; }
printf '%s' "$OPERATOR_PHONE" | grep -Eq '^\+[1-9][0-9]{7,14}$' \
  || { echo "  ✗ REFUSING: OPERATOR_PHONE must be E.164 in $VARS"; exit 1; }

miss=0
for b in jq tmux git; do
  command -v "$b" >/dev/null 2>&1 || { echo "  ✗ missing: $b   (brew install $b)"; miss=1; }
done
[ "$miss" = 0 ] || { echo; echo "install the missing tools, then re-run."; exit 1; }

PREFIX="com.$ORG"
PY="$(command -v python3 || echo /usr/bin/python3)"
AGENT_EXECUTABLE="$HOME/Applications/Wideband Agent.app/Contents/MacOS/Wideband Agent"
MARK="${MARK:-◈}"
# Where the work repo lives — the root the `website` session opens in.
APP_DIR="${APP_DIR:-$HOME/app}"
printf '%s' "$APP_DIR" | grep -q '[[:cntrl:]]' \
  && { echo "  ✗ REFUSING: APP_DIR contains a control character"; exit 1; }

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

# place_skill SRC_DIR DEST_DIR — copy a skill folder file by file. Not a
# directory sync: the operator's other skills, and anything they added inside
# this one, are never removed by a re-run.
place_skill() {
  local src="$1" dest="$2" f rel
  [ -d "$src" ] || { echo "  ~ missing in repo: $src"; return; }
  while IFS= read -r f; do
    rel="${f#"$src"/}"
    case "$rel" in
      *.sh|*/scripts/*) place "$f" "$dest/$rel" 755 ;;
      *)                place "$f" "$dest/$rel" 644 ;;
    esac
  done < <(find "$src" -type f ! -name '.DS_Store' | sort)
}

# render TMPL DEST [mode] — substitute, then place only on difference.
sed_replacement() {
  # Values are data, not sed programs. Escape the replacement metacharacters
  # so names such as "Smith & Co" render byte-for-byte rather than expanding
  # `&` back to the template token.
  printf '%s' "$1" | sed 's/[\\&|]/\\&/g'
}

render() {
  local tmpl="$1" dest="$2" mode="${3:-644}" tmp
  local root_e home_e prefix_e python_e agent_e org_e brand_e mark_e app_e
  [ -f "$tmpl" ] || { echo "  ~ missing in repo: $tmpl"; return; }
  tmp="$(mktemp)"
  root_e="$(sed_replacement "$HERE")"; home_e="$(sed_replacement "$HOME")"
  prefix_e="$(sed_replacement "$PREFIX")"; python_e="$(sed_replacement "$PY")"
  agent_e="$(sed_replacement "$AGENT_EXECUTABLE")"
  org_e="$(sed_replacement "$ORG")"; brand_e="$(sed_replacement "$BRAND")"
  mark_e="$(sed_replacement "$MARK")"; app_e="$(sed_replacement "$APP_DIR")"
  sed -e "s|__ROOT__|$root_e|g" \
      -e "s|__HOME__|$home_e|g" \
      -e "s|__PREFIX__|$prefix_e|g" \
      -e "s|__PYTHON__|$python_e|g" \
      -e "s|__AGENT_EXECUTABLE__|$agent_e|g" \
      -e "s|__ORG__|$org_e|g" \
      -e "s|__BRAND__|$brand_e|g" \
      -e "s|__MARK__|$mark_e|g" \
      -e "s|__APP_DIR__|$app_e|g" \
      "$tmpl" > "$tmp"
  mkdir -p "$(dirname "$dest")"
  if cmp -s "$tmp" "$dest"; then echo "  = $dest"
  else cp "$tmp" "$dest" && chmod "$mode" "$dest" && echo "  + $dest"; fi
  rm -f "$tmp"
}

# The packaged installer places this app before install.sh runs. Keep the
# original curl/bootstrap path working too: by this point Homebrew has supplied
# Command Line Tools, so a missing helper can be built locally without fetching
# or trusting another binary.
ensure_wideband_agent() {
  [ -x "$AGENT_EXECUTABLE" ] && return 0

  local build_root agent_app contents iconset source_png backup
  command -v xcrun >/dev/null 2>&1 \
    && xcrun --find swiftc >/dev/null 2>&1 \
    || { echo "  ✗ Wideband Agent needs Apple Command Line Tools"; return 1; }

  mkdir -p "$HOME/.wideband/setup" "$HOME/Applications" || return 1
  build_root="$(mktemp -d "$HOME/.wideband/setup/agent-build.XXXXXX")" || return 1
  agent_app="$build_root/Wideband Agent.app"
  contents="$agent_app/Contents"
  iconset="$build_root/AppIcon.iconset"
  source_png="$build_root/AppIcon-1024.png"
  mkdir -p "$contents/MacOS" "$contents/Resources" "$iconset" || return 1
  /usr/bin/ditto "$HERE/agent/Info.plist" "$contents/Info.plist" || return 1

  if [ -s "$HERE/installer/wideband-mark.png" ]; then
    /usr/bin/sips -z 1024 1024 "$HERE/installer/wideband-mark.png" --out "$source_png" >/dev/null || return 1
    /usr/bin/sips -z 16 16 "$source_png" --out "$iconset/icon_16x16.png" >/dev/null || return 1
    /usr/bin/sips -z 32 32 "$source_png" --out "$iconset/icon_16x16@2x.png" >/dev/null || return 1
    /usr/bin/sips -z 32 32 "$source_png" --out "$iconset/icon_32x32.png" >/dev/null || return 1
    /usr/bin/sips -z 64 64 "$source_png" --out "$iconset/icon_32x32@2x.png" >/dev/null || return 1
    /usr/bin/sips -z 128 128 "$source_png" --out "$iconset/icon_128x128.png" >/dev/null || return 1
    /usr/bin/sips -z 256 256 "$source_png" --out "$iconset/icon_128x128@2x.png" >/dev/null || return 1
    /usr/bin/sips -z 256 256 "$source_png" --out "$iconset/icon_256x256.png" >/dev/null || return 1
    /usr/bin/sips -z 512 512 "$source_png" --out "$iconset/icon_256x256@2x.png" >/dev/null || return 1
    /usr/bin/sips -z 512 512 "$source_png" --out "$iconset/icon_512x512.png" >/dev/null || return 1
    /usr/bin/sips -z 1024 1024 "$source_png" --out "$iconset/icon_512x512@2x.png" >/dev/null || return 1
    /usr/bin/iconutil -c icns "$iconset" -o "$contents/Resources/AppIcon.icns" || return 1
  fi

  xcrun swiftc -parse-as-library -target arm64-apple-macos13.0 \
    -framework AppKit -framework ApplicationServices -framework Carbon -framework CoreGraphics \
    "$HERE/agent/WidebandAgent.swift" -o "$contents/MacOS/Wideband Agent" || return 1
  /bin/chmod 755 "$contents/MacOS/Wideband Agent" || return 1
  /usr/bin/codesign --force --options runtime --entitlements "$HERE/agent/entitlements.plist" \
    --sign - "$agent_app" >/dev/null || return 1

  if [ -e "$HOME/Applications/Wideband Agent.app" ]; then
    backup="$HOME/.wideband/setup/package-backups/$(date '+%Y%m%d-%H%M%S')-$$/Wideband Agent.app"
    mkdir -p "$(dirname "$backup")" || return 1
    /bin/mv "$HOME/Applications/Wideband Agent.app" "$backup" || return 1
  fi
  /bin/mv "$agent_app" "$HOME/Applications/Wideband Agent.app" || return 1
  /bin/rm -rf "$build_root"
  echo "  + $HOME/Applications/Wideband Agent.app (built locally)"
}

ensure_wideband_agent || {
  echo "  ✗ could not install the branded Wideband background helper"
  exit 1
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
place "$HERE/bin/tm-memory"   "$HOME/bin/tm-memory"   755
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

# ── agent skills ─────────────────────────────────────────────────────────────
# Product code, so it updates on every run — unlike sessions.conf and the
# identity cards themselves, which belong to the operator. The cards live in
# ~/.config/agent-session-memory and are never seeded, backed up, or read here.
echo
echo "agent skills"
place_skill "$HERE/skills/agent-session-memory" "$HOME/.claude/skills/agent-session-memory"
if [ -d "$HOME/.codex" ]; then
  place_skill "$HERE/skills/agent-session-memory" "$HOME/.codex/skills/agent-session-memory"
else
  echo "  ~ no ~/.codex — Codex copy skipped; re-run install.sh after installing Codex"
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
if [ "$RUN_VERIFY" = "0" ]; then
  echo "  reconciliation finished; verification is owned by the guided installer"
  exit 0
fi
exec bash "$HERE/verify.sh"
