#!/bin/bash
# Read-only Homebrew and developer-tools diagnostics for bootstrap.sh.
#
# This file must remain compatible with macOS /bin/bash 3.2. It deliberately
# performs no sudo action. An ownership repair is printed only after the
# install user, home owner, GUI console user, architecture, prefix identity,
# and exact target have all been proved.

wb_hb_identity_probe() {
  WB_HB_USER="$(/usr/bin/id -un 2>/dev/null)"
  WB_HB_UID="$(/usr/bin/id -u 2>/dev/null)"
  WB_HB_HOME_OWNER="$(/usr/bin/stat -f '%Su' "$HOME" 2>/dev/null)"
  WB_HB_CONSOLE_USER="$(/usr/bin/stat -f '%Su' /dev/console 2>/dev/null)"
  WB_HB_ARCH="$(/usr/bin/uname -m 2>/dev/null)"
  WB_HB_ADMIN=0
  /usr/bin/id -Gn 2>/dev/null | /usr/bin/grep -qw admin && WB_HB_ADMIN=1
  WB_HB_IDENTITY_SAFE=0
  case "$WB_HB_UID" in
    ''|*[!0-9]*|0) ;;
    *)
      if [ -n "$WB_HB_USER" ] \
         && [ "$WB_HB_HOME_OWNER" = "$WB_HB_USER" ] \
         && [ -d "$HOME" ] \
         && [ ! -L "$HOME" ]; then
        WB_HB_IDENTITY_SAFE=1
      fi
      ;;
  esac
}

wb_hb_classify_clt() {
  WB_HB_CLT_READY=0
  if [ "$WB_HB_CLT_SELECTED_WORKS" = 1 ]; then
    WB_HB_CLT_READY=1
    WB_HB_CLT_STATE="ready"
  elif [ "$WB_HB_CLT_DEFAULT_WORKS" = 1 ]; then
    WB_HB_CLT_STATE="installed_not_selected"
  elif [ "$WB_HB_CLT_SELECTED_EXISTS" = 1 ] \
    || [ "$WB_HB_CLT_DEFAULT_INSTALLED" = 1 ]; then
    WB_HB_CLT_STATE="incompatible"
  else
    WB_HB_CLT_STATE="missing"
  fi
}

wb_hb_clt_probe() {
  WB_HB_CLT_PATH="$(/usr/bin/xcode-select -p 2>/dev/null)"
  WB_HB_CLT_VERSION="$(
    /usr/sbin/pkgutil --pkg-info=com.apple.pkg.CLTools_Executables 2>/dev/null \
      | /usr/bin/awk -F': ' '$1 == "version" { print $2; exit }'
  )"
  WB_HB_CLT_DEFAULT_INSTALLED=0
  WB_HB_CLT_SELECTED_EXISTS=0
  WB_HB_CLT_SELECTED_WORKS=0
  WB_HB_CLT_DEFAULT_WORKS=0
  WB_HB_GIT_VERSION=""
  if [ -x /Library/Developer/CommandLineTools/usr/bin/git ]; then
    WB_HB_CLT_DEFAULT_INSTALLED=1
  fi
  if [ -n "$WB_HB_CLT_PATH" ] \
     && [ -d "$WB_HB_CLT_PATH" ] \
     && [ -x "$WB_HB_CLT_PATH/usr/bin/git" ]; then
    WB_HB_CLT_SELECTED_EXISTS=1
  fi
  if [ "$WB_HB_CLT_SELECTED_EXISTS" = 1 ] \
     && WB_HB_GIT_VERSION="$("$WB_HB_CLT_PATH/usr/bin/git" --version 2>/dev/null)"; then
    WB_HB_CLT_SELECTED_WORKS=1
  elif [ "$WB_HB_CLT_DEFAULT_INSTALLED" = 1 ] \
     && WB_HB_GIT_VERSION="$(/Library/Developer/CommandLineTools/usr/bin/git --version 2>/dev/null)"; then
    WB_HB_CLT_DEFAULT_WORKS=1
  else
    WB_HB_GIT_VERSION="unavailable"
  fi
  wb_hb_classify_clt
}

wb_hb_classify_prefix() {
  if [ "$WB_HB_PREFIX_MARKER" != 1 ]; then
    WB_HB_PREFIX_STATE="unrecognized"
  elif [ "$WB_HB_PREFIX_OWNER" != "$WB_HB_USER" ] \
    || [ "${WB_HB_MISMATCH_COUNT:-0}" != 0 ]; then
    WB_HB_PREFIX_STATE="wrong_owner"
  elif [ "$WB_HB_PREFIX_WRITABLE" != 1 ] \
    || [ -n "$WB_HB_NONWRITABLE" ] \
    || [ "${WB_HB_NONWRITABLE_DIR_COUNT:-0}" != 0 ]; then
    WB_HB_PREFIX_STATE="not_writable"
  else
    WB_HB_PREFIX_STATE="healthy"
  fi
}

wb_hb_prefix_probe() {
  WB_HB_PREFIX="$1"
  WB_HB_PREFIX_STATE="absent"
  WB_HB_PREFIX_OWNER="missing"
  WB_HB_PREFIX_UID=""
  WB_HB_PREFIX_GROUP=""
  WB_HB_PREFIX_MODE=""
  WB_HB_PREFIX_MARKER=0
  WB_HB_PREFIX_WRITABLE=0
  WB_HB_NONWRITABLE=""
  WB_HB_MISMATCH_COUNT=0
  WB_HB_NONWRITABLE_DIR_COUNT=0
  WB_HB_ACL_ENTRY_COUNT=0
  WB_HB_FLAGGED=""
  WB_HB_PATH_READY=0
  WB_HB_PATH_BREW="$(command -v brew 2>/dev/null)"

  case ":${PATH:-}:" in
    *":$WB_HB_PREFIX/bin:"*) WB_HB_PATH_READY=1 ;;
  esac

  [ -e "$WB_HB_PREFIX" ] || return 0
  if [ -L "$WB_HB_PREFIX" ]; then
    WB_HB_PREFIX_STATE="unsafe_symlink"
    return 0
  fi
  if [ ! -d "$WB_HB_PREFIX" ]; then
    WB_HB_PREFIX_STATE="not_directory"
    return 0
  fi

  WB_HB_PREFIX_OWNER="$(/usr/bin/stat -f '%Su' "$WB_HB_PREFIX" 2>/dev/null)"
  WB_HB_PREFIX_UID="$(/usr/bin/stat -f '%u' "$WB_HB_PREFIX" 2>/dev/null)"
  WB_HB_PREFIX_GROUP="$(/usr/bin/stat -f '%Sg' "$WB_HB_PREFIX" 2>/dev/null)"
  WB_HB_PREFIX_MODE="$(/usr/bin/stat -f '%Sp' "$WB_HB_PREFIX" 2>/dev/null)"
  [ -w "$WB_HB_PREFIX" ] && WB_HB_PREFIX_WRITABLE=1

  # A lone executable or directory is not enough evidence to authorize an
  # ownership repair. Require both the public entry point and Homebrew's own
  # runtime before treating this as a recognizable installation.
  if [ -x "$WB_HB_PREFIX/bin/brew" ] \
     && [ -f "$WB_HB_PREFIX/Library/Homebrew/brew.sh" ]; then
    WB_HB_PREFIX_MARKER=1
  fi

  local candidate candidate_acls candidate_flags
  for candidate in \
    "$WB_HB_PREFIX" \
    "$WB_HB_PREFIX/bin" \
    "$WB_HB_PREFIX/Cellar" \
    "$WB_HB_PREFIX/Caskroom" \
    "$WB_HB_PREFIX/Frameworks" \
    "$WB_HB_PREFIX/etc" \
    "$WB_HB_PREFIX/include" \
    "$WB_HB_PREFIX/lib" \
    "$WB_HB_PREFIX/opt" \
    "$WB_HB_PREFIX/sbin" \
    "$WB_HB_PREFIX/share" \
    "$WB_HB_PREFIX/var"; do
    if [ -d "$candidate" ] && [ ! -w "$candidate" ]; then
      WB_HB_NONWRITABLE="${WB_HB_NONWRITABLE}${WB_HB_NONWRITABLE:+ }$candidate"
    fi
    if [ -d "$candidate" ]; then
      candidate_acls="$(
        /bin/ls -lde "$candidate" 2>/dev/null \
          | /usr/bin/awk 'NR > 1 && /^[[:space:]]*[0-9]+:/ { count++ } END { print count + 0 }'
      )"
      WB_HB_ACL_ENTRY_COUNT=$((WB_HB_ACL_ENTRY_COUNT + candidate_acls))
      candidate_flags="$(/usr/bin/stat -f '%Sf' "$candidate" 2>/dev/null)"
      if [ -n "$candidate_flags" ] && [ "$candidate_flags" != "-" ]; then
        WB_HB_FLAGGED="${WB_HB_FLAGGED}${WB_HB_FLAGGED:+ }$candidate($candidate_flags)"
      fi
    fi
  done

  if [ "$WB_HB_PREFIX_MARKER" = 1 ] && [ "$WB_HB_IDENTITY_SAFE" = 1 ]; then
    WB_HB_MISMATCH_COUNT="$(
      /usr/bin/find "$WB_HB_PREFIX" -xdev ! -uid "$WB_HB_UID" -print 2>/dev/null \
        | /usr/bin/awk 'END { print NR + 0 }'
    )"
    WB_HB_NONWRITABLE_DIR_COUNT="$(
      /usr/bin/find "$WB_HB_PREFIX" -xdev -type d -uid "$WB_HB_UID" \
        ! -perm -u+w -print 2>/dev/null \
        | /usr/bin/awk 'END { print NR + 0 }'
    )"
  fi

  wb_hb_classify_prefix
}

wb_hb_repair_available() {
  [ "$WB_HB_ARCH" = "arm64" ] \
    && [ "$WB_HB_PREFIX" = "/opt/homebrew" ] \
    && [ ! -L "$WB_HB_PREFIX" ] \
    && [ "$WB_HB_PREFIX_MARKER" = 1 ] \
    && [ "$WB_HB_IDENTITY_SAFE" = 1 ] \
    && [ "$WB_HB_ADMIN" = 1 ] \
    && [ "$WB_HB_CONSOLE_USER" = "$WB_HB_USER" ] \
    && [ "$WB_HB_ACL_ENTRY_COUNT" = 0 ] \
    && [ -z "$WB_HB_FLAGGED" ] \
    && { { [ "$WB_HB_PREFIX_STATE" = "wrong_owner" ] \
        && [ "$WB_HB_MISMATCH_COUNT" -gt 0 ] 2>/dev/null; } \
      || { [ "$WB_HB_PREFIX_STATE" = "not_writable" ] \
        && [ "$WB_HB_NONWRITABLE_DIR_COUNT" -gt 0 ] 2>/dev/null; }; }
}

wb_hb_print_repair() {
  wb_hb_repair_available || return 1
  printf '%s\n' \
    "  Verified repair boundary:" \
    "    intended user  $WB_HB_USER (uid $WB_HB_UID)" \
    "    console user   $WB_HB_CONSOLE_USER" \
    "    private prefix /opt/homebrew (not a symlink)" \
    "    current owner  $WB_HB_PREFIX_OWNER (uid ${WB_HB_PREFIX_UID:-unknown})" \
    "    ACLs / flags   none on standard Homebrew directories" \
    "" \
    "  Wideband will NOT run the ownership repair automatically." \
    "  If /opt/homebrew is intentionally this user's Homebrew installation," \
    "  $WB_HB_USER must personally review and run these exact scoped commands:" \
    "" \
    "    sudo /usr/bin/find /opt/homebrew -xdev ! -uid $WB_HB_UID -exec /usr/sbin/chown -h $WB_HB_UID {} +" \
    "    sudo /usr/bin/find /opt/homebrew -xdev -type d -uid $WB_HB_UID ! -perm -u+w -exec /bin/chmod u+rwx {} +" \
    "" \
    "  Then reopen Wideband Setup. The preflight will run again before brew."
}

wb_hb_print_report() {
  printf '%s\n' \
    "  Homebrew preflight (read-only)" \
    "    intended user  ${WB_HB_USER:-unknown} (uid ${WB_HB_UID:-unknown})" \
    "    home            $HOME (owner ${WB_HB_HOME_OWNER:-unknown})" \
    "    console user    ${WB_HB_CONSOLE_USER:-unknown}" \
    "    administrator   $([ "$WB_HB_ADMIN" = 1 ] && printf yes || printf no)" \
    "    identity safe   $([ "$WB_HB_IDENTITY_SAFE" = 1 ] && printf yes || printf no)" \
    "    architecture    ${WB_HB_ARCH:-unknown}" \
    "    PATH has brew   $([ "$WB_HB_PATH_READY" = 1 ] && printf yes || printf no)" \
    "    PATH resolves   ${WB_HB_PATH_BREW:-not found}" \
    "    developer dir   ${WB_HB_CLT_PATH:-not selected}" \
    "    developer Git   $WB_HB_CLT_STATE" \
    "    Git version     ${WB_HB_GIT_VERSION:-unavailable}" \
    "    CLT receipt     ${WB_HB_CLT_VERSION:-not found}" \
    "    prefix          $WB_HB_PREFIX" \
    "    prefix state    $WB_HB_PREFIX_STATE" \
    "    prefix owner    $WB_HB_PREFIX_OWNER${WB_HB_PREFIX_UID:+ (uid $WB_HB_PREFIX_UID)}" \
    "    prefix group    ${WB_HB_PREFIX_GROUP:-unknown}" \
    "    prefix mode     ${WB_HB_PREFIX_MODE:-unknown}" \
    "    mismatched objs $WB_HB_MISMATCH_COUNT" \
    "    locked dirs     $WB_HB_NONWRITABLE_DIR_COUNT" \
    "    ACL entries     $WB_HB_ACL_ENTRY_COUNT" \
    "    file flags      ${WB_HB_FLAGGED:-none}"
  if [ -n "$WB_HB_NONWRITABLE" ]; then
    printf '    non-writable    %s\n' "$WB_HB_NONWRITABLE"
  fi
}
