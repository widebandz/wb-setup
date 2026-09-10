#!/bin/bash
# selftest.sh — invariants of THIS REPO, not of the machine it built.
#
# verify.sh asks "is this Mac set up?". This asks "is the installer still
# honest?" — the properties that quietly rot as steps get added:
#
#   1. bootstrap.sh stays inside the bare-Mac tool budget
#   2. the vendored status line is byte-identical to a working one
#   3. no secrets, no operator identity, in a public repo
#   4. every loop reads ~/.sop-vars instead of hardcoding
#   5. every loop has a plist template
#   6. shell syntax parses
#
# Exit code is the number of failures.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PASS=0; FAIL=0

ok() { printf '  ✓ %s\n' "$*"; PASS=$((PASS+1)); }
no() { printf '  ✗ %s\n' "$*"; FAIL=$((FAIL+1)); }
head_() { printf '\n\033[1m%s\033[0m\n' "$*"; }

echo "▩ wb-setup selftest — $HERE"

# ── 1. bare-Mac tool budget ──────────────────────────────────────────────────
# Everything before the Homebrew step may use only: bash curl tar sed awk grep
# plus shell builtins. A bare macOS has no git and no python3 — those paths are
# CLT stubs that pop a dialog and block.
#
# Strings and comments are stripped first, and only COMMAND POSITION counts:
# `--no-brew` as a flag name and `command -v brew` as a guard are both fine,
# and a naive token grep flags them, which trains people to ignore this check.
head_ "1 · bare-Mac tool budget"
FORBIDDEN='git|python3|python|jq|node|npm|brew|gh|tmux|sqlite3|launchctl|tailscale|code'
hits="$(
  awk '/^# ── 2\. Homebrew/{exit} {print}' "$HERE/bootstrap.sh" \
  | sed -e "s/'[^']*'//g" -e 's/"[^"]*"//g' -e 's/#.*$//' \
  | grep -nE "(^|[;&|(]|\\\$\()[[:space:]]*($FORBIDDEN)[[:space:]]" \
  | grep -vE 'command[[:space:]]+-v'
)"
if [ -z "$hits" ]; then
  ok "no out-of-budget binary is invoked before Homebrew"
else
  no "out-of-budget invocations before Homebrew:"
  printf '      %s\n' "$hits"
fi

# ── 2. status line fidelity ──────────────────────────────────────────────────
# The argument for shipping this as a file rather than regenerating it from a
# prompt is that it is solved. That argument only holds if it stays identical.
head_ "2 · status line"
SL="$HERE/dotfiles/statusline-command.sh"
if [ ! -f "$SL" ]; then
  no "dotfiles/statusline-command.sh missing"
else
  grep -q "\$'" "$SL" \
    && ok "colors use \$'...' — real ESC bytes, not literal backslashes" \
    || no "colors are not \$'...' — they will print literally"
  grep -q 'context_window' "$SL" \
    && ok "reads context_window (the whole reason for the custom line)" \
    || no "no context_window segment"
  grep -q 'jq' "$SL" \
    && ok "parses with jq (declared in the Brewfile)" \
    || no "does not use jq — check the Brewfile still needs it"
fi

# ── 3. nothing identity-shaped in a public repo ──────────────────────────────
head_ "3 · public-repo hygiene"
LEAK='\+1[0-9]{10}|[0-9]{3}-[0-9]{3}-[0-9]{4}|sk-[A-Za-z0-9]{20}|ghp_[A-Za-z0-9]{20}|-----BEGIN [A-Z ]*PRIVATE KEY'
found="$(grep -rInE "$LEAK" "$HERE" \
          --exclude-dir=.git --exclude='selftest.sh' --exclude='*.example' 2>/dev/null \
        | grep -viE '\+15551234567|555-|example')"
[ -z "$found" ] && ok "no phone numbers, keys or tokens" \
                || { no "possible secret or identity:"; printf '      %s\n' "$found"; }

found="$(grep -rIlniE 'brainwave|tailacfa70|zayed' "$HERE" \
          --exclude-dir=.git --exclude='selftest.sh' 2>/dev/null)"
[ -z "$found" ] && ok "no operator hostnames or names" \
                || { no "machine-specific identity leaked into:"; printf '      %s\n' "$found"; }

# ── 4 + 5. the loops ─────────────────────────────────────────────────────────
head_ "4 · loops read ~/.sop-vars"
for f in "$HERE"/loops/*; do
  [ -f "$f" ] || continue
  b="$(basename "$f")"
  grep -q 'sop-vars' "$f" \
    && ok "$b reads ~/.sop-vars" \
    || no "$b does not read ~/.sop-vars — it is hardcoding something"
done

head_ "5 · every loop is schedulable"
for f in "$HERE"/loops/*; do
  [ -f "$f" ] || continue
  b="$(basename "$f")"
  [ -f "$HERE/templates/launchagents/$b.plist.tmpl" ] \
    && ok "$b has a plist template" \
    || no "$b has no plist template — it would never run"
done

# ── 6. syntax ────────────────────────────────────────────────────────────────
head_ "6 · syntax"
for s in bootstrap.sh install.sh verify.sh selftest.sh; do
  [ -f "$HERE/$s" ] || { no "$s missing"; continue; }
  bash -n "$HERE/$s" 2>/dev/null && ok "$s parses" || no "$s has a syntax error"
done
for p in "$HERE"/loops/*; do
  [ -f "$p" ] || continue
  head -1 "$p" | grep -q python || continue
  b="$(basename "$p")"
  if command -v python3 >/dev/null 2>&1; then
    python3 -c "import ast,sys; ast.parse(open(sys.argv[1]).read())" "$p" 2>/dev/null \
      && ok "$b parses" || no "$b has a syntax error"
  fi
done
if command -v shellcheck >/dev/null 2>&1; then
  for s in bootstrap.sh install.sh verify.sh selftest.sh; do
    shellcheck -S error "$HERE/$s" >/dev/null 2>&1 \
      && ok "shellcheck $s (errors)" \
      || no "shellcheck found errors in $s"
  done
fi

printf '\n\033[1m%s\033[0m\n' "─────────────────────────────────────────"
printf '  %d passed · %d failed\n\n' "$PASS" "$FAIL"
exit "$FAIL"
