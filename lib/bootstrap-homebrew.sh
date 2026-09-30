#!/bin/bash
# Read-only Homebrew and developer-tools diagnostics for bootstrap.sh.
#
# This file must remain compatible with macOS /bin/bash 3.2. It deliberately
# performs no sudo action. A current-owner permission suggestion is printed
# only after the install user, home owner, GUI console user, architecture,
# prefix identity, and exact target have all been proved.

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

  # Root ownership alone is enough to reject a foreign prefix. Do not walk
  # another user's entire Cellar just to count objects we will never change.
  if [ "$WB_HB_PREFIX_OWNER" != "$WB_HB_USER" ]; then
    wb_hb_classify_prefix
    return 0
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
    if ! WB_HB_MISMATCH_COUNT="$(
      set -o pipefail
      /usr/bin/find "$WB_HB_PREFIX" -xdev ! -uid "$WB_HB_UID" -print 2>/dev/null \
        | /usr/bin/awk 'END { print NR + 0 }'
    )"; then
      WB_HB_MISMATCH_COUNT=unknown
    fi
    if ! WB_HB_NONWRITABLE_DIR_COUNT="$(
      set -o pipefail
      /usr/bin/find "$WB_HB_PREFIX" -xdev -type d -uid "$WB_HB_UID" \
        ! -perm -u+w -print 2>/dev/null \
        | /usr/bin/awk 'END { print NR + 0 }'
    )"; then
      WB_HB_NONWRITABLE_DIR_COUNT=unknown
    fi
  fi

  wb_hb_classify_prefix
}

wb_hb_repair_available() {
  [ "$WB_HB_ARCH" = "arm64" ] \
    && [ "$WB_HB_PREFIX" = "/opt/homebrew" ] \
    && [ ! -L "$WB_HB_PREFIX" ] \
    && [ "$WB_HB_PREFIX_MARKER" = 1 ] \
    && [ "$WB_HB_PREFIX_OWNER" = "$WB_HB_USER" ] \
    && [ "$WB_HB_PREFIX_UID" = "$WB_HB_UID" ] \
    && [ "$WB_HB_MISMATCH_COUNT" = 0 ] \
    && [ "$WB_HB_IDENTITY_SAFE" = 1 ] \
    && [ "$WB_HB_ADMIN" = 1 ] \
    && [ "$WB_HB_CONSOLE_USER" = "$WB_HB_USER" ] \
    && [ "$WB_HB_ACL_ENTRY_COUNT" = 0 ] \
    && [ -z "$WB_HB_FLAGGED" ] \
    && [ "$WB_HB_PREFIX_STATE" = "not_writable" ] \
    && [ "$WB_HB_NONWRITABLE_DIR_COUNT" -gt 0 ] 2>/dev/null
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
    "  Wideband will NOT change Homebrew permissions automatically." \
    "  This prefix and every object are already owned by $WB_HB_USER." \
    "  $WB_HB_USER may review and run this scoped command:" \
    "" \
    "    /usr/bin/find /opt/homebrew -xdev -type d -uid $WB_HB_UID ! -perm -u+w -exec /bin/chmod u+rwx {} +" \
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

# Toolchain selection is deliberately independent of PATH. The private
# payload is activated by one mode-0600 build-ID file, so a replacement can be
# staged under versions/ without changing a running build. The producer must
# put SHA-256 lines in manifest.sha256 for every regular file in that version
# except manifest.sha256 itself:
#   <64 lowercase hex characters><two spaces>bin/python3
# The manifest and complete payload tree must be owned by the current user
# and private. Symlinks, extra files, ACLs, and writable group/other bits fail.
wb_tc_safe_owned() { # PATH TYPE [EXACT_MODE]
  local path="$1" kind="$2" exact="${3:-}" uid mode acl_count
  [ ! -L "$path" ] || return 1
  if [ "$kind" = d ]; then [ -d "$path" ]; else [ -f "$path" ]; fi || return 1
  uid="$(/usr/bin/stat -f '%u' "$path" 2>/dev/null)"
  [ "$uid" = "$WB_HB_UID" ] || return 1
  mode="$(/usr/bin/stat -f '%Lp' "$path" 2>/dev/null)"
  case "$mode" in ''|*[!0-7]*) return 1 ;; esac
  if [ -n "$exact" ]; then
    [ "$mode" = "$exact" ] || return 1
  else
    [ $(( (8#$mode) & 0077 )) -eq 0 ] || return 1
  fi
  acl_count="$(set -o pipefail
    /bin/ls -lde "$path" 2>/dev/null \
    | /usr/bin/awk 'NR > 1 && /^[[:space:]]*[0-9]+:/ { count++ } END { print count + 0 }')" || return 1
  [ "$acl_count" = 0 ]
}

wb_tc_manifest_hash() { # TOOL
  local tool="$1" hash
  hash="$(/usr/bin/awk -v target="bin/$tool" \
    '$2 == target { if (NF != 2) bad=1; count++; value=$1 }
     END { if (count == 1 && !bad) print value }' \
    "$WB_TOOLCHAIN_PREFIX/manifest.sha256" 2>/dev/null)"
  [[ "$hash" =~ ^[0-9a-f]{64}$ ]] || return 1
  printf '%s\n' "$hash"
}

wb_tc_manifest_verify() {
  local prefix="$WB_TOOLCHAIN_PREFIX" manifest listing expected_count actual_count entry unsafe acl_count
  manifest="$prefix/manifest.sha256"
  # Only simple relative names are representable in the hash file. Reject
  # traversal, duplicate names, control characters and shasum escapes.
  expected_count="$(/usr/bin/awk '
    {
      hash=substr($0, 1, 64); sep=substr($0, 65, 2); path=substr($0, 67)
      if (length(hash) != 64 || hash !~ /^[0-9a-f]+$/ || sep != "  " ||
          path == "" || path == "manifest.sha256" || path ~ /^\// ||
          path ~ /\/$/ || path ~ /(^|\/)\.\.?($|\/)/ ||
          path ~ /[[:cntrl:]]/ || index(path, "\\") || seen[path]++) bad=1
    }
    END { if (bad || NR == 0) exit 1; print NR }
  ' "$manifest" 2>/dev/null)" || return 1

  # BSD find checks ownership and unsafe permissions for the whole tree in
  # one traversal. No symlink or special file may be hidden among resources.
  unsafe="$(/usr/bin/find "$prefix" -mindepth 1 \
    \( -type l -o ! -user "$WB_HB_UID" -o -perm +077 -o -perm +7000 \
       -o ! \( -type f -o -type d \) \) -print -quit 2>/dev/null)" || return 1
  [ -z "$unsafe" ] || return 1
  acl_count="$(set -o pipefail
    /usr/bin/find "$prefix" -mindepth 1 -exec /bin/ls -lde {} + 2>/dev/null \
    | /usr/bin/awk 'NR > 1 && /^[[:space:]]*[0-9]+:/ { count++ } END { print count + 0 }')" || return 1
  [ "$acl_count" = 0 ] || return 1

  listing="$(/usr/bin/mktemp /tmp/wb-toolchain-list.XXXXXX)" || return 1
  if ! /usr/bin/find "$prefix" -type f ! -path "$manifest" -print0 > "$listing" 2>/dev/null; then
    /bin/rm -f "$listing"
    return 1
  fi
  actual_count=0
  while IFS= read -r -d '' entry; do
    case "$entry" in
      *$'\n'*|*$'\r'*|*$'\t'*) /bin/rm -f "$listing"; return 1 ;;
    esac
    actual_count=$((actual_count + 1))
  done < "$listing"
  /bin/rm -f "$listing"
  [ "$actual_count" -eq "$expected_count" ] || return 1
  ( cd "$prefix" && /usr/bin/shasum -a 256 -c manifest.sha256 >/dev/null 2>&1 )
}

wb_tc_private_bin() { # TOOL; prints nothing, sets WB_TOOLCHAIN_PATH
  local tool="$1" path expected actual
  WB_TOOLCHAIN_PATH=""
  case "$tool" in
    python3|tmux|imsg|node|npm|ttyd|git|jq|gh|sqlite3|ffmpeg) ;;
    *) return 1 ;;
  esac
  path="$WB_TOOLCHAIN_BIN/$tool"
  wb_tc_safe_owned "$path" f && [ -x "$path" ] || return 1
  expected="$(wb_tc_manifest_hash "$tool")" || return 1
  actual="$(/usr/bin/shasum -a 256 "$path" 2>/dev/null | /usr/bin/awk '{print $1}')"
  [ "$actual" = "$expected" ] || return 1
  WB_TOOLCHAIN_PATH="$path"
}

wb_tc_private_probe() {
  local root active version build_id tool
  WB_TOOLCHAIN_STATE=absent
  root="$HOME/.wideband/toolchain"
  active="$root/active"
  [ -e "$active" ] || [ -L "$active" ] || return 1
  WB_TOOLCHAIN_STATE=unsafe_private
  [ "$WB_HB_IDENTITY_SAFE" = 1 ] || return 1
  wb_tc_safe_owned "$HOME/.wideband" d || return 1
  wb_tc_safe_owned "$root" d || return 1
  wb_tc_safe_owned "$root/versions" d || return 1
  wb_tc_safe_owned "$active" f 600 || return 1
  build_id="$(/usr/bin/sed -n '1p' "$active" 2>/dev/null)"
  [[ "$build_id" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$ ]] || return 1
  [ "$(/usr/bin/wc -l < "$active" 2>/dev/null | /usr/bin/tr -d ' ')" = 1 ] || return 1
  version="$root/versions/$build_id"
  wb_tc_safe_owned "$version" d || return 1
  wb_tc_safe_owned "$version/bin" d || return 1
  wb_tc_safe_owned "$version/manifest.sha256" f 600 || return 1
  WB_TOOLCHAIN_PREFIX="$version"
  WB_TOOLCHAIN_BIN="$version/bin"
  WB_TOOLCHAIN_BUILD_ID="$build_id"
  if ! wb_tc_manifest_verify; then
    WB_TOOLCHAIN_STATE=invalid_manifest
    return 1
  fi
  for tool in python3 tmux imsg; do
    wb_tc_private_bin "$tool" || {
      WB_TOOLCHAIN_STATE=missing_tool
      return 1
    }
  done
  WB_TOOLCHAIN_PATH=""
  WB_TOOLCHAIN_STATE=ready
  return 0
}

wb_tc_legacy_allowed() {
  local marker="$HOME/.wideband/setup/legacy-homebrew-allowed" build_id
  wb_tc_safe_owned "$HOME/.wideband/setup" d || return 1
  wb_tc_safe_owned "$marker" f 600 || return 1
  build_id="$(/usr/bin/sed -n '1p' "$marker" 2>/dev/null)"
  case "$build_id" in 0.7.0-*|0.7.1-*) return 0 ;; esac
  return 1
}

wb_tc_resolve() { # [TOOL] — sets WB_TOOLCHAIN_{KIND,PREFIX,BIN,PATH,STATE}
  local tool="${1:-}" path
  WB_TOOLCHAIN_KIND=""
  WB_TOOLCHAIN_PREFIX=""
  WB_TOOLCHAIN_BIN=""
  WB_TOOLCHAIN_PATH=""
  WB_TOOLCHAIN_BUILD_ID=""
  WB_TOOLCHAIN_STATE=absent
  wb_hb_identity_probe
  if wb_tc_private_probe; then
    WB_TOOLCHAIN_KIND=private
    if [ -n "$tool" ]; then wb_tc_private_bin "$tool" || return 1; fi
    return 0
  fi
  # A present but invalid private activation is never silently bypassed.
  if [ "$WB_TOOLCHAIN_STATE" != absent ]; then
    WB_TOOLCHAIN_PREFIX=""
    WB_TOOLCHAIN_BIN=""
    WB_TOOLCHAIN_PATH=""
    return 1
  fi
  [ "${WB_TC_REQUIRE_PRIVATE:-0}" != 1 ] || return 1
  wb_tc_legacy_allowed || return 1
  wb_hb_clt_probe
  wb_hb_prefix_probe /opt/homebrew
  [ "$WB_HB_CLT_READY" = 1 ] \
    && [ "$WB_HB_PREFIX_STATE" = healthy ] \
    && [ "$WB_HB_ACL_ENTRY_COUNT" = 0 ] \
    && [ -z "$WB_HB_FLAGGED" ] || return 1
  WB_TOOLCHAIN_KIND=legacy_homebrew
  WB_TOOLCHAIN_PREFIX=/opt/homebrew
  WB_TOOLCHAIN_BIN=/opt/homebrew/bin
  WB_TOOLCHAIN_STATE=ready
  if [ -n "$tool" ]; then
    case "$tool" in
      python3|tmux|imsg|node|npm|ttyd|git|jq|gh|sqlite3|ffmpeg) ;;
      *) return 1 ;;
    esac
    path="$WB_TOOLCHAIN_BIN/$tool"
    [ -x "$path" ] || return 1
    WB_TOOLCHAIN_PATH="$path"
  fi
  return 0
}
