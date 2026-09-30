#!/bin/bash
# Run only after the client explicitly selects Claude Code in Wideband Setup.
# Download the official installer to a private file and require a successful
# fetch and syntax check before executing it.
set -euo pipefail
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
[ "$#" -eq 1 ] && [ -x "$1" ] \
  || { printf 'Claude sign-in needs the verified Wideband Python tool.\n' >&2; exit 1; }
PYTHON="$1"

fail() {
  printf '\n  Claude sign-in stopped: %s\n' "$1" >&2
  printf '  Return to Wideband Setup and retry after resolving this problem.\n' >&2
  exit 1
}

trusted_claude() {
  "$PYTHON" - <<'PY'
import os
from pathlib import Path
import stat
import sys

home = Path.home().resolve()
for candidate in (home / ".local/bin/claude", home / "bin/claude"):
    try:
        resolved = candidate.resolve(strict=True)
        info = resolved.stat()
        if (resolved.is_relative_to(home) and stat.S_ISREG(info.st_mode)
                and info.st_uid == os.getuid() and not info.st_mode & 0o022
                and os.access(resolved, os.X_OK)):
            print(resolved)
            sys.exit(0)
    except OSError:
        pass
sys.exit(1)
PY
}

printf '\n  WIDEBAND · CLAUDE CODE\n\n'
printf '  Your selected provider will open its own browser sign-in.\n'
printf '  Wideband never receives your password or verification codes.\n\n'

if ! CLAUDE="$(trusted_claude)"; then
  for candidate in "$HOME/.local/bin/claude" "$HOME/bin/claude"; do
    if [ -e "$candidate" ] || [ -L "$candidate" ]; then
      fail "An existing Claude launcher could not be verified for this login."
    fi
  done
  installer="$(/usr/bin/mktemp "${TMPDIR:-/tmp}/wideband-claude-install.XXXXXX")" \
    || fail "Could not create a private installer file."
  /bin/chmod 600 "$installer"
  trap '/bin/rm -f -- "$installer"' EXIT
  printf '  Downloading Claude Code from claude.ai…\n'
  if ! /usr/bin/curl --fail --location --silent --show-error \
      --proto '=https' --tlsv1.2 --connect-timeout 10 --max-time 90 \
      --output "$installer" https://claude.ai/install.sh; then
    fail "The official installer could not be downloaded completely."
  fi
  [ -s "$installer" ] && /bin/bash -n "$installer" \
    || fail "The downloaded installer was empty or invalid."
  printf '  Installing Claude Code for this macOS login…\n'
  /bin/bash "$installer" || fail "The Claude Code installer failed."
  CLAUDE="$(trusted_claude)" \
    || fail "The installer did not leave a verified Claude launcher in this login."
fi

printf '  Opening Claude Code sign-in…\n'
"$CLAUDE" auth login || fail "Claude Code sign-in did not finish."
printf '\n  Return to Wideband Setup and select Check Claude sign-in.\n'
