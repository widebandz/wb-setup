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
# TOOL BUDGET: macOS built-ins only until Homebrew lands. Packaged client mode
# may use /usr/bin/osascript for the owner-phone prompt, and the health guard uses
# built-in identity, filesystem, and xcode-select probes. A bare macOS has no
# usable Git or Python — /usr/bin/git and /usr/bin/python3 can be stubs that pop
# the Command Line Tools dialog and block. That is why the repo arrives as a
# tarball rather than a clone. selftest.sh asserts that no package-managed tool
# crosses this boundary, because it is the constraint most likely to regress.
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
SETUP_STATE="$HOME/.wideband/setup"
BREW_LOG="/tmp/wb-bootstrap-brew.log"
BREW_PID=""
SUDO_KEEPALIVE=""
BREW_BLOCK_REASON=""
BREW_USABLE=0
BREW_INSTALLER=""
DIAGNOSE_HOMEBREW=0
CLT_WAIT_SECONDS="${WB_CLT_WAIT_SECONDS:-3600}"
CLT_POLL_SECONDS="${WB_CLT_POLL_SECONDS:-5}"
HERE=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]:-/nonexistent}" ]; then
  HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
fi

DO_CLAUDE=1; DO_BREW=1; DO_FETCH=1; DO_UI=1; ASSUME_YES=0; CLIENT_MODE=0

for arg in "$@"; do
  case "$arg" in
    --no-claude) DO_CLAUDE=0 ;;
    --no-brew)   DO_BREW=0 ;;
    --no-fetch)  DO_FETCH=0 ;;
    --no-ui)     DO_UI=0 ;;
    --client)    CLIENT_MODE=1; export WB_SETUP_CLIENT_MODE=1 ;;
    --diagnose-homebrew) DIAGNOSE_HOMEBREW=1; DO_CLAUDE=0; DO_BREW=0; DO_FETCH=0; DO_UI=0 ;;
    --yes|-y)    ASSUME_YES=1 ;;
    --org=*)     export ORG="${arg#*=}" ;;
    --brand=*)   export BRAND="${arg#*=}" ;;
    --mark=*)    export MARK="${arg#*=}" ;;
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

case "$CLT_WAIT_SECONDS:$CLT_POLL_SECONDS" in
  *[!0-9:]*|:*|*:) echo "  ! invalid developer-tools wait configuration" >&2; exit 2 ;;
esac
if [ "$CLT_POLL_SECONDS" -lt 1 ]; then
  echo "  ! developer-tools polling interval must be at least one second" >&2
  exit 2
fi

say()  { printf '%s\n' "$*"; }
step() { printf '\n\033[1m%s\033[0m\n' "$*"; }
bootstrap_status() {
  mkdir -p "$SETUP_STATE" 2>/dev/null || return
  ( umask 077; printf '%s\n' "$1" > "$SETUP_STATE/bootstrap-status" ) 2>/dev/null || true
}

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
if [ "$CLIENT_MODE" = "1" ] && [ "$OSMAJ" -lt 14 ]; then
  bootstrap_status unsupported_macos
  say "  ✗ The client iMessage path needs macOS 14 or newer."
  say "    Update macOS, then reopen Wideband Setup."
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

if [ "$DIAGNOSE_HOMEBREW" = 1 ]; then
  if [ -z "$HERE" ] || [ ! -f "$HERE/lib/bootstrap-homebrew.sh" ]; then
    say "  ✗ --diagnose-homebrew must be run from the downloaded wb-setup repository."
    exit 1
  fi
  # shellcheck source=lib/bootstrap-homebrew.sh
  . "$HERE/lib/bootstrap-homebrew.sh"
  wb_hb_identity_probe
  wb_hb_clt_probe
  wb_hb_prefix_probe /opt/homebrew
  wb_hb_print_report
  if wb_hb_repair_available; then
    echo
    wb_hb_print_repair
  fi
  exit 0
fi

say "  ✓ arm64 · macOS $(sw_vers -productVersion) · $(id -un)"
bootstrap_status starting

# ── 1. the agent, first ──────────────────────────────────────────────────────
# Zero dependencies: no Node, no Homebrew, no Command Line Tools. Seconds.
# This is the step that is conventionally put last and belongs first.

step "1/6  Claude Code"
bootstrap_status installing_agent
if [ "$DO_CLAUDE" = "0" ]; then
  say "  ~ skipped (--no-claude)"
elif command -v claude >/dev/null 2>&1 || [ -x "$HOME/.local/bin/claude" ]; then
  say "  = already installed"
else
  if { curl -fsSL https://claude.ai/install.sh 2>/tmp/wb-claude-install.log \
       || { say "  ! could not reach claude.ai — the network may be blocking it"; false; }; } \
       | bash >>/tmp/wb-claude-install.log 2>&1; then
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

# ── 2. the repo ──────────────────────────────────────────────────────────────
# Tarball, not clone: git does not exist yet. Fetch this small payload before
# Homebrew so its versioned, testable health guard can diagnose partial prefixes
# left behind by OS upgrades. The delay is seconds; the long downloads still
# run in the background while the human works.

step "2/6  wb-setup"
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

if [ ! -f "$ROOT/lib/bootstrap-homebrew.sh" ]; then
  say "  ✗ Homebrew health guard is missing from $ROOT."
  say "    Refusing to inspect or repair /opt/homebrew without it."
  exit 1
fi
# shellcheck source=lib/bootstrap-homebrew.sh
. "$ROOT/lib/bootstrap-homebrew.sh"

explain_developer_tools_selection() {
  bootstrap_status needs_developer_tools_selection
  say "  ! Apple Command Line Tools exist but are not selected after the OS upgrade."
  say "    Wideband will not change the system developer directory with sudo."
  say "    The intended user must personally review and run:"
  say ""
  say "      sudo /usr/bin/xcode-select --switch /Library/Developer/CommandLineTools"
  say ""
  say "    Then reopen Wideband Setup."
}

explain_developer_tools_update() {
  bootstrap_status needs_developer_tools_update
  say "  ! Developer-tool files exist, but their Git cannot run after the OS upgrade."
  say "    Wideband will not delete or replace Apple's tools automatically."
  say "    Open System Settings → General → Software Update and install the"
  say "    available Command Line Tools update, then reopen Wideband Setup."
}

ensure_developer_tools() {
  local waited=0 next_notice=60
  wb_hb_clt_probe
  [ "$WB_HB_CLT_READY" = 1 ] && return 0

  if [ "$WB_HB_CLT_STATE" = "installed_not_selected" ]; then
    explain_developer_tools_selection
    return 1
  fi

  if [ "$WB_HB_CLT_STATE" = "incompatible" ]; then
    explain_developer_tools_update
    return 1
  fi

  bootstrap_status needs_developer_tools
  say "  Apple Command Line Tools are missing. This is not the full Xcode app."
  say "  macOS will open its installer; select Install and accept Apple's terms."
  say "  The request message alone does not mean the download has started."
  /usr/bin/xcode-select --install >>"$BREW_LOG" 2>&1 || true
  say "  … waiting for Apple Command Line Tools; Wideband checks automatically."
  while [ "$waited" -lt "$CLT_WAIT_SECONDS" ]; do
    /bin/sleep "$CLT_POLL_SECONDS"
    waited=$((waited + CLT_POLL_SECONDS))
    wb_hb_clt_probe
    if [ "$WB_HB_CLT_READY" = 1 ]; then
      say "  ✓ Apple Command Line Tools and developer Git are ready"
      return 0
    fi
    if [ "$WB_HB_CLT_STATE" = "installed_not_selected" ]; then
      explain_developer_tools_selection
      return 1
    fi
    if [ "$WB_HB_CLT_STATE" = "incompatible" ]; then
      explain_developer_tools_update
      return 1
    fi
    if [ "$waited" -ge "$next_notice" ]; then
      say "  … still waiting for the Apple installer (${waited}s); do not close Terminal"
      next_notice=$((next_notice + 60))
    fi
  done
  say "  ! Apple Command Line Tools did not become ready before the wait expired."
  say "    Reopen Wideband Setup after the Apple installation finishes."
  return 1
}

prepare_brew_log() {
  local log_uid=""
  if [ -L "$BREW_LOG" ] || { [ -e "$BREW_LOG" ] && [ ! -f "$BREW_LOG" ]; }; then
    say "  ✗ refusing unsafe Homebrew log target: $BREW_LOG"
    return 1
  fi
  if [ -e "$BREW_LOG" ]; then
    log_uid="$(/usr/bin/stat -f '%u' "$BREW_LOG" 2>/dev/null)"
    if [ "$log_uid" != "$WB_HB_UID" ]; then
      say "  ✗ refusing Homebrew log owned by another user: $BREW_LOG"
      return 1
    fi
  fi
  ( umask 077; : > "$BREW_LOG" ) || return 1
  /bin/chmod 600 "$BREW_LOG" 2>/dev/null || return 1
}

# ── 3. Homebrew + Command Line Tools ────────────────────────────────────────
# A binary at /opt/homebrew/bin/brew is not enough. Major macOS upgrades can
# leave the prefix in place while removing/deselecting CLT or changing the
# ownership context. Inspect identity, prefix and Git separately before brew.

step "3/6  Homebrew + Command Line Tools (background)"
wb_hb_identity_probe
wb_hb_clt_probe
wb_hb_prefix_probe /opt/homebrew
wb_hb_print_report

if [ "$DO_BREW" = "0" ]; then
  say "  ~ skipped (--no-brew)"
elif [ "$WB_HB_IDENTITY_SAFE" != 1 ]; then
  BREW_BLOCK_REASON="identity"
  bootstrap_status needs_attention
  say "  ✗ cannot prove the intended install user owns HOME; refusing Homebrew changes"
  DO_BREW=0
else
  PREFIX_REPAIR_REQUIRED=0
  case "$WB_HB_PREFIX_STATE" in
    absent|healthy) ;;
    wrong_owner|not_writable)
      if wb_hb_repair_available; then
        PREFIX_REPAIR_REQUIRED=1
      else
        BREW_BLOCK_REASON="unsafe_prefix"
        bootstrap_status needs_homebrew_ownership
        say "  ✗ /opt/homebrew is not healthy, but the intended repair user is not proven."
        say "    No chown command will be suggested. An operator must review the report above."
        DO_BREW=0
      fi
      ;;
    *)
      BREW_BLOCK_REASON="unsafe_prefix"
      bootstrap_status needs_homebrew_ownership
      say "  ✗ refusing an unrecognized or redirected /opt/homebrew target ($WB_HB_PREFIX_STATE)"
      DO_BREW=0
      ;;
  esac

  if [ "$DO_BREW" = 1 ] && ! prepare_brew_log; then
    BREW_BLOCK_REASON="unsafe_log"
    bootstrap_status needs_attention
    DO_BREW=0
  fi

  if [ "$DO_BREW" = 1 ] && ! ensure_developer_tools; then
    if [ "$WB_HB_CLT_STATE" = "installed_not_selected" ]; then
      BREW_BLOCK_REASON="developer_tools_selection"
    elif [ "$WB_HB_CLT_STATE" = "incompatible" ]; then
      BREW_BLOCK_REASON="developer_tools_update"
    else
      BREW_BLOCK_REASON="developer_tools"
    fi
    DO_BREW=0
  fi

  if [ "$DO_BREW" = 1 ] && [ "$PREFIX_REPAIR_REQUIRED" = 1 ]; then
    BREW_BLOCK_REASON="ownership"
    bootstrap_status needs_homebrew_ownership
    say "  ✗ Homebrew belongs to another ownership context or is not writable."
    wb_hb_print_repair
    DO_BREW=0
  fi
fi

if [ "$DO_BREW" = 1 ] && [ -x /opt/homebrew/bin/brew ]; then
  BREW_USABLE=1
  say "  = existing Homebrew passed identity, prefix, and developer-Git checks"
elif [ "$DO_BREW" = 1 ]; then
  # Homebrew needs sudo. A detached job has no terminal, so it cannot prompt
  # for the password — prime the credential in the foreground, then keep it
  # warm while the official installer runs detached.
  bootstrap_status needs_admin_password
  say "  macOS will ask for your password once — Homebrew needs it."
  if sudo -v; then
    bootstrap_status installing_tools
    ( while true; do sudo -n true 2>/dev/null; sleep 50; kill -0 "$$" 2>/dev/null || exit; done ) &
    SUDO_KEEPALIVE=$!
  else
    bootstrap_status needs_attention
    BREW_BLOCK_REASON="sudo"
    say "  ! no sudo — Homebrew cannot install. Everything else still runs."
    DO_BREW=0
  fi

  if [ "$DO_BREW" = "1" ]; then
    # Download to a FILE first. Piped straight into bash, a 404 or a blocked
    # network yields an empty string, `bash -c ""` exits 0, and the run reports
    # a successful install of nothing.
    BREW_INSTALLER="$(/usr/bin/mktemp "$SETUP_STATE/homebrew-install.XXXXXX")" || BREW_INSTALLER=""
    if [ -n "$BREW_INSTALLER" ] \
       && /bin/chmod 600 "$BREW_INSTALLER" \
       && curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh \
         -o "$BREW_INSTALLER" 2>>"$BREW_LOG"; then
      ( NONINTERACTIVE=1 /bin/bash "$BREW_INSTALLER" >>"$BREW_LOG" 2>&1 ) &
      BREW_PID=$!
      say "  → started (pid $BREW_PID), logging to $BREW_LOG"
      say "    This is the download to work around, not wait on."
    else
      BREW_BLOCK_REASON="network"
      say "  ! could not download the Homebrew installer — the network is blocking it"
      say "    Try a phone hotspot. See TROUBLESHOOTING.md."
    fi
  fi
fi

# ── 4. identity ──────────────────────────────────────────────────────────────
# One substitution table. Everything downstream reads from it, which is the
# property that makes the next machine come out the same as this one.

step "4/6  identity → $VARS"
bootstrap_status collecting_identity

# Piped as `curl … | bash`, stdin IS the script — a bare `read` would eat the
# rest of it and the run would end mid-file. Always read the human from the
# terminal directly.
TTY_OK=0
if [ -r /dev/tty ] && { : < /dev/tty; } 2>/dev/null; then TTY_OK=1; fi

VALIDATION_ERROR=""
valid_value() {  # valid_value VAR VALUE
  local var="$1" value="$2" n
  VALIDATION_ERROR=""
  case "$var" in
    CLIENT_NAME)
      n="${#value}"
      [ "$n" -ge 1 ] && [ "$n" -le 120 ] \
        && ! printf '%s' "$value" | grep -q '[[:cntrl:]]' \
        || VALIDATION_ERROR="your name on one line (120 characters or fewer)" ;;
    ORG)
      printf '%s' "$value" | grep -Eq '^[a-z][a-z0-9-]{0,30}$' \
        || VALIDATION_ERROR="lowercase letters, digits and hyphens only; start with a letter" ;;
    BRAND)
      n="${#value}"
      [ "$n" -ge 1 ] && [ "$n" -le 80 ] \
        && ! printf '%s' "$value" | grep -q '[[:cntrl:]]' \
        || VALIDATION_ERROR="1–80 characters on one line" ;;
    MARK)
      n="${#value}"
      [ "$n" -ge 1 ] && [ "$n" -le 4 ] \
        && ! printf '%s' "$value" | grep -q '[[:space:]]' \
        || VALIDATION_ERROR="one visible glyph (up to four Unicode code points)" ;;
    GH_USER)
      printf '%s' "$value" | grep -Eq '^[A-Za-z0-9]([A-Za-z0-9-]{0,37}[A-Za-z0-9])?$' \
        && ! printf '%s' "$value" | grep -q -- '--' \
        || VALIDATION_ERROR="a valid GitHub username (letters, digits and single hyphens)" ;;
    GIT_EMAIL)
      printf '%s' "$value" | grep -Eq '^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$' \
        || VALIDATION_ERROR="an email address with no spaces" ;;
    OPERATOR_PHONE)
      printf '%s' "$value" | grep -Eq '^\+[1-9][0-9]{7,14}$' \
        || VALIDATION_ERROR="E.164 format, for example +15551234567" ;;
    WORK_REPO)
      [ -n "$value" ] && ! printf '%s' "$value" | grep -q '[[:space:]]' \
        || VALIDATION_ERROR="a git URL with no spaces" ;;
    GRAPH_PACK)
      printf '%s' "$value" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$' \
        || VALIDATION_ERROR="letters, digits, dots, underscores and hyphens only" ;;
  esac
  [ -z "$VALIDATION_ERROR" ]
}

native_ask() {  # native_ask VAR "plain-language prompt" "default"
  local var="$1" prompt="$2" def="$3" answer
  while true; do
    answer="$(/usr/bin/osascript - "$prompt" "$def" <<'APPLESCRIPT'
on run argv
  set response to display dialog (item 1 of argv) default answer (item 2 of argv) with title "Wideband Setup" buttons {"Cancel", "Continue"} default button "Continue" cancel button "Cancel"
  return text returned of response
end run
APPLESCRIPT
    )" || { say "  Setup was cancelled. Reopen Wideband Setup when you are ready."; exit 1; }
    if valid_value "$var" "$answer"; then
      export "$var=$answer"
      return
    fi
    /usr/bin/osascript - "$VALIDATION_ERROR" <<'APPLESCRIPT' >/dev/null 2>&1 || true
on run argv
  display alert "Check that answer" message (item 1 of argv) as warning
end run
APPLESCRIPT
  done
}

collect_client_identity() {
  # The first client milestone is a working text exchange. GitHub, a work
  # repository, commit identity, and an organization graph can be chosen after
  # that proof; invented values here would masquerade as real client answers.
  ORG="${ORG:-wideband}"; BRAND="${BRAND:-Wideband}"; MARK="${MARK:-◈}"
  GH_USER="${GH_USER:-}"; GIT_EMAIL="${GIT_EMAIL:-}"
  WORK_REPO="${WORK_REPO:-}"; GRAPH_PACK="${GRAPH_PACK:-wideband}"
  export ORG BRAND MARK GH_USER GIT_EMAIL WORK_REPO GRAPH_PACK
  if ! valid_value OPERATOR_PHONE "${OPERATOR_PHONE:-}"; then
    native_ask OPERATOR_PHONE "What is your personal phone number? Include country code (for example +15551234567). Your separate agent Apple Account will text this number." ""
  fi
  say "  + owner phone saved; optional developer identity deferred"
}

ask() {  # ask VAR "prompt" "default"
  local var="$1" prompt="$2" def="$3" cur ans
  eval "cur=\${$var:-}"
  if [ -n "$cur" ]; then
    if valid_value "$var" "$cur"; then say "  = $var=$cur"; return; fi
    say "  ! $var is invalid: $VALIDATION_ERROR"
    if [ "$ASSUME_YES" = "1" ] || [ "$TTY_OK" = "0" ]; then
      say "    Fix the value and re-run bootstrap."
      exit 1
    fi
  fi
  if [ "$ASSUME_YES" = "1" ] || [ "$TTY_OK" = "0" ]; then
    export "$var=$def"
    say "  + $var=$def (default)"
    return
  fi
  while true; do
    printf '    %s [%s]: ' "$prompt" "$def" > /dev/tty
    read -r ans < /dev/tty
    [ -z "$ans" ] && ans="$def"
    if valid_value "$var" "$ans"; then
      export "$var=$ans"
      return
    fi
    printf '      Invalid: %s. Try again.\n' "$VALIDATION_ERROR" > /dev/tty
  done
}

shell_quote() {
  # Single-quote arbitrary one-line text for a file that will be sourced by
  # bash/zsh. This prevents a brand name or URL from becoming shell syntax.
  printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"
}

if [ -f "$VARS" ]; then
  # Never overwrite a curated identity file. Same rule fleetdeck applies to
  # config.json: seed once, then it belongs to the operator.
  chmod 600 "$VARS" 2>/dev/null || { say "  ✗ cannot make $VARS private"; exit 1; }
  # shellcheck disable=SC1090
  . "$VARS"
  say "  = $VARS exists — leaving it alone"
else
  if [ "$CLIENT_MODE" = "1" ] && [ -x /usr/bin/osascript ]; then
    say "  → opening the Wideband identity guide"
    collect_client_identity
  else
    ask ORG            "org slug (names LaunchAgents com.<org>.*)" "acme"
    ask BRAND          "board name"                                "fleetdeck"
    ask MARK           "tmux status mark (one cell)"               "◈"
    ask GH_USER        "GitHub username (the ONLY one on this Mac)" "$ORG"
    ask GIT_EMAIL      "git commit email"                          "ops@$ORG.com"
    ask OPERATOR_PHONE "phone for briefs (E.164)"                  "+15551234567"
    ask WORK_REPO      "work repo (git URL)"                       "git@github.com:$GH_USER/app.git"
    ask GRAPH_PACK     "knowledge-graph pack name"                 "$ORG"
  fi

  if ! ( umask 077
    {
      printf '%s\n' '# Written by wb-setup bootstrap. Edit freely, then re-run install.sh.'
      printf '%s\n' '# MACHINE and TAILNET are deliberately absent — resolved from Tailscale at'
      printf '%s\n' '# runtime. Pinning them is how a build stops being portable.'
      if [ -n "${CLIENT_NAME:-}" ]; then
        printf 'export CLIENT_NAME=%s\n' "$(shell_quote "$CLIENT_NAME")"
      fi
      for name in ORG BRAND MARK GH_USER GIT_EMAIL OPERATOR_PHONE WORK_REPO GRAPH_PACK; do
        eval "value=\${$name}"
        printf 'export %s=%s\n' "$name" "$(shell_quote "$value")"
      done
    } > "$VARS"
  ); then
    say "  ✗ could not write $VARS"
    exit 1
  fi
  say "  + $VARS"
fi
for name in ORG BRAND MARK GH_USER GIT_EMAIL OPERATOR_PHONE WORK_REPO GRAPH_PACK; do
  eval "value=\${$name:-}"
  if [ "$CLIENT_MODE" = "1" ] && [ -z "$value" ]; then
    case "$name" in GH_USER|GIT_EMAIL|WORK_REPO) continue ;; esac
  fi
  if ! valid_value "$name" "$value"; then
    say "  ✗ REFUSING: $name in $VARS is invalid: $VALIDATION_ERROR"
    say "    Edit the file, then re-run bootstrap."
    exit 1
  fi
done
if [ -n "${CLIENT_NAME:-}" ] && ! valid_value CLIENT_NAME "$CLIENT_NAME"; then
  say "  ✗ REFUSING: CLIENT_NAME in $VARS is invalid: $VALIDATION_ERROR"
  exit 1
fi
chmod 600 "$VARS" 2>/dev/null || say "  ! could not make $VARS private"

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

if [ "$CLIENT_MODE" = "1" ]; then
  bootstrap_status installing_tools
  step "6/6  guided setup is next"
  cat <<'QUEUE'

  Leave this Terminal window open behind the browser. Wideband Setup is already
  showing live machine progress and guides every account and macOS permission
  one step at a time while the remaining tools install.

  Passwords and two-factor codes stay between you and each provider. Wideband
  Setup never asks you to paste them into the installer.

QUEUE
else
  step "6/6  do these now, while the download runs"
  cat <<'QUEUE'

  These need a human and no network from this machine. Working them now is
  free; working them after the download is pure added wall clock.

	  PERMISSIONS  — System Settings. Every one is a dialog, and a missed grant
	                 fails silently several phases later.
	    1. General → Sharing → Remote Login                          ON
	    2. General → Sharing → Screen Sharing                        intended admin only
	    3. Privacy & Security → Full Disk Access                     Terminal (direct bootstrap)
	    4. Privacy & Security → Accessibility                        Terminal (direct bootstrap)
	    5. Privacy & Security → Screen Recording                     Terminal (direct bootstrap)
	    6. General → Login Items & Extensions → allow background items
	    7. Messages.app → Settings → sign in with the separate agent Apple Account

  ACCOUNTS     — email FIRST; everything else verifies through it.
	    8. Agent Apple Account         9. email — send yourself one, confirm
	   10. GitHub (as $GH_USER only)   11. Anthropic (Pro/Max, or API key)
	   12. Tailscale                   13. Vercel · Supabase

  THEN, the moment Claude Code is installed:
       claude          → browser login → the agent is live

QUEUE
fi

# ── wait on Homebrew ─────────────────────────────────────────────────────────
if [ -n "$BREW_PID" ]; then
  bootstrap_status installing_tools
  say "  … waiting on Homebrew (pid $BREW_PID). tail -f $BREW_LOG to watch."
  wait "$BREW_PID"; brew_rc=$?
  # Check the BINARY, not the exit code. An installer can exit 0 having done
  # nothing, which is exactly how a machine reached the end of this script with
  # "✓ Homebrew installed" on screen and no brew on disk.
  if [ -x /opt/homebrew/bin/brew ]; then
    wb_hb_prefix_probe /opt/homebrew
    if [ "$WB_HB_PREFIX_STATE" = "healthy" ]; then
      BREW_USABLE=1
      say "  ✓ Homebrew installed and passed the prefix health check"
    else
      BREW_BLOCK_REASON="homebrew_install"
      say "  ! Homebrew appeared but failed its prefix health check ($WB_HB_PREFIX_STATE)"
    fi
  else
    BREW_BLOCK_REASON="homebrew_install"
    say "  ! Homebrew did NOT install (installer exited $brew_rc) — see $BREW_LOG"
    say "    Run it in the foreground so it can prompt for your password:"
    say "    /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
  fi
fi
[ -n "$BREW_INSTALLER" ] && /bin/rm -f "$BREW_INSTALLER"
[ -n "${SUDO_KEEPALIVE:-}" ] && kill "$SUDO_KEEPALIVE" 2>/dev/null

BREW_BIN=""
[ "$BREW_USABLE" = 1 ] && [ -x /opt/homebrew/bin/brew ] && BREW_BIN=/opt/homebrew/bin/brew
if [ -n "$BREW_BIN" ]; then
  eval "$("$BREW_BIN" shellenv)"
  if ! grep -qs 'brew shellenv' "$HOME/.zprofile" 2>/dev/null; then
    printf '\neval "$(/opt/homebrew/bin/brew shellenv)"\n' >> "$HOME/.zprofile"
    say "  + brew shellenv → ~/.zprofile"
  fi
  BREWFILE="$ROOT/Brewfile"
  [ "$CLIENT_MODE" = "1" ] && BREWFILE="$ROOT/Brewfile.quick"
  if [ "$DO_BREW" = "1" ] && [ -f "$BREWFILE" ]; then
    say "  … brew bundle ($(basename "$BREWFILE"))"
    if brew bundle --file="$BREWFILE" >>"$BREW_LOG" 2>&1; then
      say "  ✓ core CLIs installed"
    else
      BREW_BLOCK_REASON="brew_bundle"
      say "  ! brew bundle had failures — see $BREW_LOG"
    fi
  fi
fi

# ── Claude Code, second attempt ──────────────────────────────────────────────
# Step 1 runs before Homebrew exists, by design — the native installer has no
# dependencies and the whole ordering rests on that. But on a filtered network
# (corporate, school, or filtered DNS) claude.ai can be blocked while the
# Homebrew CDN is not, and step 1 then fails with a 404 that looks like a bad
# URL. Observed on a real client machine, 2026-09-10.
#
# By this point Homebrew exists, so there is a second route. Same tool.
if ! command -v claude >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/claude" ]; then
  if [ -n "$BREW_BIN" ]; then
    step "Claude Code — retry via Homebrew"
    say "  the direct installer did not succeed; trying the cask"
    if brew install --cask claude-code >>"$BREW_LOG" 2>&1; then
      say "  ✓ installed via Homebrew"
      say "    Open a NEW terminal window before running claude."
    else
      say "  ! that failed too — see $BREW_LOG"
      say "    Try a phone hotspot, then: brew install --cask claude-code"
    fi
  else
    step "Claude Code — not installed"
    say "  No healthy Homebrew to fall back to. After resolving the preflight, either of:"
    say "    curl -fsSL https://claude.ai/install.sh | bash"
    say "    brew install --cask claude-code"
  fi
fi

# ── handoff ──────────────────────────────────────────────────────────────────
if [ "$BREW_BLOCK_REASON" = "ownership" ] \
  || [ "$BREW_BLOCK_REASON" = "unsafe_prefix" ]; then
  bootstrap_status needs_homebrew_ownership
elif [ "$BREW_BLOCK_REASON" = "developer_tools" ]; then
  bootstrap_status needs_developer_tools
elif [ "$BREW_BLOCK_REASON" = "developer_tools_selection" ]; then
  bootstrap_status needs_developer_tools_selection
elif [ "$BREW_BLOCK_REASON" = "developer_tools_update" ]; then
  bootstrap_status needs_developer_tools_update
elif [ -n "$BREW_BLOCK_REASON" ]; then
  bootstrap_status needs_attention
elif [ "$CLIENT_MODE" = "1" ] \
   && [ -f "$VARS" ] \
   && [ -x /opt/homebrew/bin/brew ] \
   && [ -x /opt/homebrew/bin/python3 ] \
   && [ -x /opt/homebrew/bin/tmux ] \
   && [ -x /opt/homebrew/bin/imsg ]; then
  bootstrap_status ready
elif [ "$CLIENT_MODE" != "1" ] \
   && [ -f "$VARS" ] \
   && [ -x /opt/homebrew/bin/git ] \
   && [ -x /opt/homebrew/bin/jq ] \
   && [ -x /opt/homebrew/bin/tmux ]; then
  bootstrap_status ready
else
  bootstrap_status needs_attention
fi

cat <<EOF

▩ bootstrap done.

  Next, in this order:

    bash $ROOT/setup.sh
        opens the guided installer, resumes after a restart, and keeps the
        human steps, machine checks, interview, and build record together

  Prefer the guided installer for a client build. The underlying commands
  remain available for diagnosis and unattended reconciliation:

    claude                       authenticate the agent in the browser
    bash $ROOT/verify.sh         human-readable machine assertions
    bash $ROOT/install.sh        reconcile the deterministic artifacts

  The agent's runbook is ~/.claude/SOP.md. Point it there:

    "Read ~/.claude/SOP.md and run verify.sh. Work the phases that fail,
     in order, stopping at anything that needs me."

EOF

# The guided installer is the normal handoff, not an optional demo. Keep an
# explicit --no-ui path for unattended runs and for operators who only want the
# underlying scripts. For a standalone bootstrap, `exec` leaves one foreground
# process in this Terminal; closing it stops the local server. The native app
# already owns the guide, so its handoff must not open Safari.
if [ "$DO_UI" = "1" ] && [ -t 1 ]; then
  if command -v python3 >/dev/null 2>&1 || [ -x /opt/homebrew/bin/python3 ]; then
    step "Opening Wideband Setup"
    if [ "${WB_SETUP_EMBEDDED:-0}" = 1 ]; then
      exec bash "$ROOT/setup.sh" --no-open
    fi
    exec bash "$ROOT/setup.sh"
  else
    say "  ! guided installer not opened — Python did not arrive with the Brewfile"
    say "    After fixing Homebrew, run: bash $ROOT/setup.sh"
  fi
fi
