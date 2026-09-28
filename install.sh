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
IMESSAGE_ONLY=0
PHONE_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --no-verify) RUN_VERIFY=0 ;;
    --imessage-only) IMESSAGE_ONLY=1 ;;
    --phone-only) PHONE_ONLY=1 ;;
    --help|-h)
      echo "usage: bash install.sh [--no-verify] [--imessage-only|--phone-only]"
      exit 0 ;;
    *)
      echo "unknown option: $arg" >&2
      exit 2 ;;
  esac
done
[ "$IMESSAGE_ONLY" = "1" ] && [ "$PHONE_ONLY" = "1" ] \
  && { echo "choose one scoped install mode" >&2; exit 2; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Customer phone mode installs a reviewed, managed Fleetdeck bundle. An
# existing checkout has its own source and configuration; leave it untouched
# before changing permissions, installing tools, or minting an access token.
if [ "$PHONE_ONLY" = "1" ] && { [ -e "$HOME/srv/fleetdeck/.git" ] \
                              || [ -L "$HOME/srv/fleetdeck/.git" ]; }; then
  echo "  ✗ existing Fleetdeck checkout at $HOME/srv/fleetdeck; preserved"
  echo "    The managed customer phone stack needs an isolated bundled source."
  exit 1
fi
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
required_vars="ORG BRAND GH_USER OPERATOR_PHONE"
[ "$IMESSAGE_ONLY" = "1" ] && required_vars="ORG OPERATOR_PHONE"
[ "$PHONE_ONLY" = "1" ] && required_vars="ORG BRAND"
for v in $required_vars; do
  eval "val=\${$v:-}"
  [ -n "$val" ] || { echo "  ✗ REFUSING: $v is empty in $VARS"; exit 1; }
done
printf '%s' "$ORG" | grep -Eq '^[a-z][a-z0-9-]{0,30}$' \
  || { echo "  ✗ REFUSING: ORG must be a lowercase slug in $VARS"; exit 1; }
if [ "$PHONE_ONLY" != "1" ] || [ -n "${OPERATOR_PHONE:-}" ]; then
  printf '%s' "${OPERATOR_PHONE:-}" | grep -Eq '^\+[1-9][0-9]{7,14}$' \
    || { echo "  ✗ REFUSING: OPERATOR_PHONE must be E.164 in $VARS"; exit 1; }
fi

miss=0
required_bins="jq tmux git"
[ "$IMESSAGE_ONLY" = "1" ] && required_bins="python3 tmux"
[ "$PHONE_ONLY" = "1" ] && required_bins="python3 tmux"
for b in $required_bins; do
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

install_imessage_runtime() {
  # LaunchAgents/ is loaded at GUI login, even without an explicit bootstrap.
  # Keep unbound templates in the private runtime directory until the named
  # setup action has created an exact owner chat binding.
  echo
  echo "iMessage head runtime"
  place "$HERE/imessage/runtime.py" "$HOME/bin/wb-imessage" 755
  local stage="$HOME/.wideband/imessage/launchagents"
  local disabled="$HOME/.wideband/imessage/disabled-launchagents"
  local cfg="$HOME/.wideband/imessage/config.json" job l err reason="" failures=0 backup="" snapshot="" disabled_jobs=""
  mkdir -p "$stage" "$disabled" || return 1
  chmod 700 "$HOME/.wideband/imessage" "$stage" "$disabled" || return 1
  for job in watch route keep outbox; do
    l="$PREFIX.imessage-$job"
    render "$HERE/imessage/plists/$job.plist.tmpl" "$stage/$l.plist"
    [ -s "$stage/$l.plist" ] || { echo "  ✗ could not stage $l"; return 1; }
  done

  if [ "${NO_IMESSAGE:-0}" = "1" ]; then
    reason="runtime activation disabled (NO_IMESSAGE=1)"
  elif [ ! -x "$HOME/bin/wb-imessage" ] || ! command -v imsg >/dev/null 2>&1; then
    reason="imsg unavailable; install steipete/tap/imsg before binding"
  elif [ "$(sw_vers -productVersion | cut -d. -f1)" -lt 14 ]; then
    reason="iMessage runtime requires macOS 14 or newer"
  elif [ ! -f "$cfg" ] \
       || ! "$PY" - "$cfg" <<'PY' >/dev/null 2>&1
import json, sys
try:
    value = json.load(open(sys.argv[1], encoding="utf-8"))
    b = value["binding"]
    assert value["schema_version"] == 1
    assert isinstance(b["chat_id"], int) and b["chat_id"] > 0
    assert all(isinstance(b[key], str) and b[key] for key in ("chat_guid", "account_login"))
except (OSError, ValueError, KeyError, TypeError, AssertionError):
    sys.exit(1)
PY
  then
    reason="waiting for separate Apple Account and exact owner chat binding"
  fi
  if [ -z "$reason" ]; then
    # A structurally valid saved binding is not enough. Confirm the pinned
    # owner-only chat still matches Messages using the same FDA principal as
    # the jobs before placing any plist in the login-loaded directory.
    snapshot="$("$AGENT_EXECUTABLE" run-background-task "$PY" "$HOME/bin/wb-imessage" check 2>/dev/null || true)"
    if ! printf '%s' "$snapshot" | "$PY" -c '
import json, sys
try:
    value = json.load(sys.stdin)
    assert value.get("target_verified") is True
except (ValueError, AssertionError):
    sys.exit(1)
' >/dev/null 2>&1; then
      reason="saved binding does not match the live owner chat under Wideband Agent"
    fi
  fi

  if [ -n "$reason" ]; then
    echo "  ~ $reason; LaunchAgents remain inactive"
    # A prior release placed these plists in the live directory before binding.
    # Remove only this organization's four labels so a reboot cannot start them.
    for job in keep route watch outbox; do
      l="$PREFIX.imessage-$job"
      if [ -e "$LA/$l.plist" ] || [ -L "$LA/$l.plist" ]; then
        if [ -z "$backup" ]; then
          backup="$disabled/$(date '+%Y%m%d-%H%M%S')-$$"
          mkdir -p "$backup" || return 1
        fi
        if mv "$LA/$l.plist" "$backup/$l.plist"; then
          echo "  - $l.plist (moved out of LaunchAgents)"
        else
          echo "  ! could not move $l.plist out of LaunchAgents"
          failures=1
        fi
      fi
      if launchctl print "gui/$UID_N/$l" >/dev/null 2>&1; then
        launchctl bootout "gui/$UID_N/$l" 2>/dev/null || true
        for _ in $(seq 20); do
          launchctl print "gui/$UID_N/$l" >/dev/null 2>&1 || break
          sleep 0.3
        done
        if launchctl print "gui/$UID_N/$l" >/dev/null 2>&1; then
          echo "  ! $l remains loaded; inspect it before continuing"
          failures=1
        fi
      fi
    done
    return "$failures"
  fi

  mkdir -p "$HOME/.wideband/imessage/logs" || return 1
  chmod 700 "$HOME/.wideband/imessage/logs" || return 1
  # A previous stop can leave launchd's persistent disabled bit set even when
  # no job is loaded. In that state bootstrap fails until the exact label is
  # enabled again. Clear it only after the owner chat has been verified.
  disabled_jobs="$(launchctl print-disabled "gui/$UID_N" 2>/dev/null || true)"
  for job in keep route watch outbox; do
      l="$PREFIX.imessage-$job"
      if [ -L "$LA/$l.plist" ] || { [ -e "$LA/$l.plist" ] && [ ! -f "$LA/$l.plist" ]; }; then
        echo "  ! refusing unexpected LaunchAgent path: $LA/$l.plist"
        failures=1
        continue
      fi
      place "$stage/$l.plist" "$LA/$l.plist" || { failures=1; continue; }
      if launchctl print "gui/$UID_N/$l" >/dev/null 2>&1; then
        launchctl bootout "gui/$UID_N/$l" 2>/dev/null || true
        for _ in $(seq 20); do
          launchctl print "gui/$UID_N/$l" >/dev/null 2>&1 || break
          sleep 0.3
        done
        if launchctl print "gui/$UID_N/$l" >/dev/null 2>&1; then
          echo "  ! $l could not be stopped for reload"
          failures=1
          continue
        fi
      fi
      if grep -Fq "\"$l\" => disabled" <<< "$disabled_jobs"; then
        if ! err="$(launchctl enable "gui/$UID_N/$l" 2>&1)"; then
          echo "  ! $l could not be re-enabled: ${err:-unknown}"
          failures=1
          continue
        fi
      fi
      if err="$(launchctl bootstrap "gui/$UID_N" "$LA/$l.plist" 2>&1)"; then
        echo "  ✓ $l"
      else
        echo "  ! $l FAILED to load: ${err:-unknown}"
        failures=1
      fi
  done
  return "$failures"
}

install_phone_portal() {
  # This step follows the first successful text. Reconcile the real Fleetdeck
  # board first, then its VM-local terminal map, graph and guarded tmux chat.
  local fd="$HOME/srv/fleetdeck" state="$HOME/.wideband/setup/state.json"
  local bundle="$HERE/vendor/fleetdeck" stage="" portal_port prefix base portal_values
  local upgrade_result="" upgrade_backup="" portal_upgraded=0
  local portal_pid_before="" portal_pid_after=""
  # Bash functions see their caller's locals. Every failure after a managed
  # source upgrade comes through here so the old portal and manifest return.
  phone_portal_fail() {
    local reason="$1" label="${prefix:-$PREFIX}.fleetdeck-portal"
    echo "  ✗ $reason"
    if [ "$portal_upgraded" = "1" ]; then
      if [ -n "$upgrade_backup" ] \
         && "$PY" "$HERE/packaging/bundle-fleetdeck.py" restore \
              "$bundle" "$fd" "$upgrade_backup" >/dev/null; then
        echo "  - previous Fleetdeck portal source restored; client data preserved"
        if launchctl print "gui/$UID_N/$label" >/dev/null 2>&1; then
          launchctl kickstart -k "gui/$UID_N/$label" >/dev/null 2>&1 \
            || echo "  ! previous portal could not restart; inspect its LaunchAgent"
        elif [ -f "$LA/$label.plist" ] && [ ! -L "$LA/$label.plist" ]; then
          launchctl bootstrap "gui/$UID_N" "$LA/$label.plist" >/dev/null 2>&1 \
            || echo "  ! previous portal could not reload; inspect its LaunchAgent"
        fi
      else
        echo "  ! portal source rollback needs review; previous backup was kept"
      fi
    fi
    return 1
  }
  echo
  echo "Fleetdeck phone portal"
  mkdir -p "$HOME/.wideband/setup"
  chmod 700 "$HOME/.wideband/setup"
  umask 077
  if ! "$PY" - "$state" <<'PY' >/dev/null 2>&1
import json, os, stat, sys
try:
    fd = os.open(sys.argv[1], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, encoding="utf-8") as f:
        info = os.fstat(f.fileno())
        assert stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
        assert not info.st_mode & 0o077 and info.st_size <= 64 * 1024
        meta = json.load(f)["metadata"]
        assert all(isinstance(meta.get(k), str) and meta[k] for k in ("os_name", "agent_name", "first_goal"))
except (OSError, ValueError, KeyError, TypeError, AssertionError):
    sys.exit(1)
PY
  then
    echo "  ✗ finish OS name, agent name and first goal before installing the phone portal"
    return 1
  fi
  if ! "$PY" "$HERE/packaging/phone-access-token.py" "$HOME"; then
    echo "  ✗ private phone access could not be prepared"
    return 1
  fi
  if [ ! -d "$bundle" ] || [ -L "$bundle" ] \
     || ! "$PY" "$HERE/packaging/bundle-fleetdeck.py" verify "$bundle" \
     || [ ! -d "$HERE/vendor/glitch-cat-pilot-bundle" ] \
     || ! "$PY" "$HERE/packaging/glitch-cat-pilot.py" verify \
            "$HERE/vendor/glitch-cat-pilot-bundle"; then
    echo "  ✗ the reviewed real Fleetdeck and Knowledge Graph bundles are required"
    return 1
  fi
  if ! command -v brew >/dev/null 2>&1 \
     || ! brew bundle --file="$HERE/Brewfile.phone" \
          >"$HOME/.wideband/setup/phone-tools-install.log" 2>&1; then
    echo "  ✗ phone workspace tools could not install; see phone-tools-install.log"
    return 1
  fi

  if [ -L "$fd" ]; then
    echo "  ✗ $fd is a symlink; left untouched"
    return 1
  elif [ -f "$fd/.wideband-fleetdeck-bundle.json" ]; then
    if ! "$PY" "$HERE/packaging/bundle-fleetdeck.py" verify-managed "$fd"; then
      echo "  ✗ existing bundled Fleetdeck source was edited or damaged; left untouched"
      return 1
    fi
    if [ -e "$bundle" ] || [ -L "$bundle" ]; then
      if ! upgrade_result="$("$PY" "$HERE/packaging/bundle-fleetdeck.py" upgrade "$bundle" "$fd")"; then
        echo "  ✗ packaged Fleetdeck source cannot safely upgrade; client data left untouched"
        return 1
      fi
      if [ "${upgrade_result%%$'\n'*}" = "upgraded" ] \
         && [ "$upgrade_result" != "${upgrade_result#*$'\n'}" ]; then
        upgrade_backup="${upgrade_result#*$'\n'}"
        portal_upgraded=1
        echo "  + generated Fleetdeck customer portal upgraded; client data preserved"
      elif [ "$upgrade_result" != "current" ]; then
        echo "  ✗ unexpected Fleetdeck upgrade result"
        return 1
      fi
    fi
    echo "  = $fd (existing bundled source and data preserved)"
  elif [ -e "$fd" ]; then
    echo "  ✗ $fd exists but is not a Fleetdeck checkout; left untouched"
    return 1
  else
    mkdir -p "$HOME/srv" || return 1
    stage="$(mktemp -d "$HOME/srv/.fleetdeck-stage.XXXXXX")" || return 1
    if [ -e "$bundle" ] || [ -L "$bundle" ]; then
      if [ ! -d "$bundle" ] || [ -L "$bundle" ] \
         || ! "$PY" "$HERE/packaging/bundle-fleetdeck.py" verify "$bundle"; then
        echo "  ✗ packaged Fleetdeck source failed verification"
        rm -rf "$stage"
        return 1
      fi
      if ! /usr/bin/ditto "$bundle" "$stage" \
         || ! "$PY" "$HERE/packaging/bundle-fleetdeck.py" verify "$stage"; then
        echo "  ✗ could not stage the packaged Fleetdeck source"
        rm -rf "$stage"
        return 1
      fi
      echo "  + Fleetdeck staged from the setup app"
    else
      if ! command -v git >/dev/null 2>&1; then
        echo "  ✗ Fleetdeck was not bundled and Git is unavailable for the public-clone fallback"
        rm -rf "$stage"
        return 1
      fi
      if ! git clone -q --depth 1 https://github.com/widebandz/fleetdeck.git "$stage" 2>/dev/null; then
        echo "  ✗ could not fetch Fleetdeck"
        rm -rf "$stage"
        return 1
      fi
      echo "  + Fleetdeck staged from the public repository"
    fi
    if [ ! -f "$stage/install.sh" ] || ! grep -q 'CUSTOMER_MODE' "$stage/install.sh"; then
      echo "  ✗ staged Fleetdeck source lacks the customer-mode portal guard"
      rm -rf "$stage"
      return 1
    fi
    if [ -e "$fd" ] || [ -L "$fd" ] || ! mv "$stage" "$fd"; then
      echo "  ✗ $fd appeared while Fleetdeck was staged; left untouched"
      rm -rf "$stage"
      return 1
    fi
    echo "  + $fd"
  fi
  if ! grep -q 'CUSTOMER_MODE' "$fd/install.sh"; then
    phone_portal_fail "Fleetdeck source lacks customer-mode portal guard; update it before continuing"
    return 1
  fi
  if [ ! -f "$fd/config.json" ]; then
    "$PY" - "$fd/config.example.json" "$fd/config.json" "$BRAND" "$PREFIX" <<'PY' || { phone_portal_fail "Fleetdeck configuration could not be prepared"; return 1; }
import json, os, sys
source, dest, brand, prefix = sys.argv[1:]
with open(source, encoding="utf-8") as f:
    config = json.load(f)
config.update(brand=brand, label_prefix=prefix, machine="")
try:
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    pass
else:
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
PY
  else
    echo "  = $fd/config.json (operator-owned; preserved)"
  fi

  if ! "$PY" - "$fd/config.json" "$state" <<'PY' >/dev/null 2>&1
import json, sys
config = json.load(open(sys.argv[1], encoding="utf-8"))
meta = json.load(open(sys.argv[2], encoding="utf-8"))["metadata"]
onboarding = config.get("onboarding")
if onboarding is not None:
    assert isinstance(onboarding, dict)
    assert all(onboarding.get(key) == meta.get(key) for key in ("os_name", "agent_name", "first_goal"))
PY
  then
    phone_portal_fail "existing Fleetdeck onboarding identity conflicts with this setup; left untouched"
    return 1
  fi

  if ! portal_values="$("$PY" - "$fd/config.json" <<'PY'
import json, re, sys
config = json.load(open(sys.argv[1], encoding="utf-8"))
prefix = config.get("label_prefix", "com.example")
port = config.get("ports", {}).get("portal", 8790)
assert isinstance(prefix, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9.-]{1,99}", prefix) and ".." not in prefix
assert type(port) is int and 1024 <= port <= 65535
print(prefix, port)
PY
)"; then
    phone_portal_fail "Fleetdeck portal label or port is invalid"
    return 1
  fi
  read -r prefix portal_port <<<"$portal_values"
  if [ "$portal_upgraded" = "1" ]; then
    portal_pid_before="$(launchctl print "gui/$UID_N/$prefix.fleetdeck-portal" 2>/dev/null \
      | awk '$1 == "pid" && $2 == "=" { print $3; exit }')"
  fi
  if ! ( cd "$fd" && TAILSCALE_BE_CLI=1 ./install.sh portal ) \
      >"$HOME/.wideband/setup/fleetdeck-portal-install.log" 2>&1; then
    phone_portal_fail "Fleetdeck portal installation failed; see fleetdeck-portal-install.log"
    return 1
  fi
  if [ "$portal_upgraded" = "1" ] \
     && launchctl print "gui/$UID_N/$prefix.fleetdeck-portal" >/dev/null 2>&1; then
    portal_pid_after="$(launchctl print "gui/$UID_N/$prefix.fleetdeck-portal" 2>/dev/null \
      | awk '$1 == "pid" && $2 == "=" { print $3; exit }')"
    if [ -z "$portal_pid_after" ] || [ "$portal_pid_before" = "$portal_pid_after" ]; then
      launchctl kickstart -k "gui/$UID_N/$prefix.fleetdeck-portal" \
        || { phone_portal_fail "upgraded Fleetdeck portal could not restart"; return 1; }
    fi
  fi
  # Fleetdeck seeds services.json during its install. Reconcile the first goal
  # afterward if its tile is absent. Keep an already healthy first site and
  # curated services.json untouched during a portal-only source upgrade.
  if "$PY" "$HERE/first_goal/runner.py" check >/dev/null 2>&1 \
     && "$PY" - "$fd/services.json" "$state" "$HOME/.wideband/first-goal/status.json" <<'PY' >/dev/null 2>&1
import json, sys
services = json.load(open(sys.argv[1], encoding="utf-8"))
metadata = json.load(open(sys.argv[2], encoding="utf-8"))["metadata"]
goal = metadata["first_goal"]
if goal == "website":
    status = json.load(open(sys.argv[3], encoding="utf-8"))
    assert any(isinstance(item, dict) and item.get("id") == "first-project"
               and item.get("source") == "wideband-first-goal"
               and item.get("port") == status.get("port")
               for item in services["services"])
PY
  then
    echo "  = existing first project and Fleetdeck registration preserved"
  else
    if ! "$PY" "$HERE/first_goal/runner.py" apply \
         >"$HOME/.wideband/setup/first-goal-phone.log" 2>&1; then
      phone_portal_fail "first project could not register with Fleetdeck; see first-goal-phone.log"
      return 1
    fi
  fi
  if ! launchctl print "gui/$UID_N/$prefix.fleetdeck-portal" >/dev/null 2>&1; then
    phone_portal_fail "Fleetdeck portal LaunchAgent is not loaded"
    return 1
  fi
  for base in chat adopt skin; do
    if launchctl print "gui/$UID_N/$prefix.fleetdeck-$base" >/dev/null 2>&1 \
       || [ -f "$LA/$prefix.fleetdeck-$base.plist" ]; then
      phone_portal_fail "writable or operator Fleetdeck surface remains active: $base"
      return 1
    fi
  done
  if ! "$PY" - "$portal_port" <<'PY' >/dev/null 2>&1
import sys, urllib.request
with urllib.request.urlopen(f"http://127.0.0.1:{int(sys.argv[1])}/healthz", timeout=3) as r:
    assert r.status == 200 and r.read(32).strip() == b"ok"
PY
  then
    phone_portal_fail "Fleetdeck portal did not answer on loopback"
    return 1
  fi
  echo "  ✓ Fleetdeck customer portal answers on loopback"
  if ! "$PY" "$HERE/packaging/phone-stack.py" \
       >"$HOME/.wideband/setup/phone-stack-install.log" 2>&1; then
    phone_portal_fail "the real terminal network, Knowledge Graph, or tmux chat did not activate; see phone-stack-install.log"
    return 1
  fi
  echo "  ✓ real Fleetdeck board, terminal network, Knowledge Graph and tmux chat are installed"
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

if [ "$PHONE_ONLY" = "1" ]; then
  install_phone_portal
  exit $?
fi

ensure_wideband_agent || {
  echo "  ✗ could not install the branded Wideband background helper"
  exit 1
}

if [ "$IMESSAGE_ONLY" = "1" ]; then
  install_imessage_runtime || exit 1
  if [ "$RUN_VERIFY" = "0" ]; then
    echo "  iMessage runtime reconciliation finished; verification follows in the guide"
    exit 0
  fi
  exec bash "$HERE/verify.sh" --imessage-only
fi

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

# ── one-owner iMessage head runtime ─────────────────────────────────────────
install_imessage_runtime || exit 1

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
