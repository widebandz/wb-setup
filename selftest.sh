#!/bin/bash
# selftest.sh — invariants of THIS REPO, not of the machine it built.
#
# verify.sh asks "is this Mac set up?". This asks "is the installer still
# honest?" — the properties that quietly rot as steps get added:
#
#   1. bootstrap.sh stays inside the bare-Mac tool budget
#   2. the vendored status line is byte-identical to a working one
#   3. no secrets, no operator identity, in a public repo
#   4. no loop hardcodes identity
#   5. every loop has a plist template
#   6. verify.sh IDs and TROUBLESHOOTING.md sections match, BOTH ways
#   7. doctor.sh diagnoses and never mutates
#   8. shell syntax parses
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
# The invariant is "no loop hardcodes identity", NOT "every loop reads
# ~/.sop-vars". A loop with no identity in it at all — tmux-boot, healthcheck —
# satisfies the intent more completely than one that reads the file. Testing for
# the file rather than for the property failed those two and was wrong to.
head_ "4 · no loop hardcodes identity"
IDENT='\+1[0-9]{10}|/Users/[a-z]|[a-z0-9-]+\.ts\.net|@[a-z0-9-]+\.(com|ai|io)'
NEEDS='OPERATOR_PHONE|GH_USER|GIT_EMAIL|WORK_REPO|GRAPH_PACK|\$ORG|\$BRAND'
for f in "$HERE"/loops/*; do
  [ -f "$f" ] || continue
  b="$(basename "$f")"
  lit="$(sed -e "s/'[^']*'//g" -e 's/#.*$//' "$f" | grep -nEo "$IDENT" | head -3)"
  if [ -n "$lit" ]; then
    no "$b contains an identity literal: $(printf '%s' "$lit" | tr '\n' ' ')"
  elif grep -qE "$NEEDS" "$f"; then
    grep -q 'sop-vars' "$f" \
      && ok "$b needs identity and reads ~/.sop-vars" \
      || no "$b references identity vars but never reads ~/.sop-vars"
  else
    ok "$b is identity-free"
  fi
done

head_ "5 · every loop is schedulable"
for f in "$HERE"/loops/*; do
  [ -f "$f" ] || continue
  b="$(basename "$f")"
  [ -f "$HERE/templates/launchagents/$b.plist.tmpl" ] \
    && ok "$b has a plist template" \
    || no "$b has no plist template — it would never run"
done

# ── 6. the guide cannot drift ────────────────────────────────────────────────
# verify.sh emits a stable ID per failure; TROUBLESHOOTING.md has a section per
# ID. Checked BOTH ways on purpose. A one-way check (every ID has a section)
# still lets the guide accumulate sections for checks that no longer exist,
# which is the quieter half of drift: nobody notices documentation for a
# failure that can no longer happen, and it slowly teaches the wrong thing.
head_ "6 · verify IDs ↔ guide sections"
if [ ! -f "$HERE/TROUBLESHOOTING.md" ]; then
  no "TROUBLESHOOTING.md missing"
else
  # IDs raised by verify.sh: the first argument to every no() call.
  ids="$(grep -oE '(^|\s)no [A-Z0-9]+-[A-Z]+' "$HERE/verify.sh" \
         | awk '{print $NF}' | sort -u)"
  # IDs documented in the guide: `## P0-FDA — …`
  docs="$(grep -oE '^## [A-Z0-9]+-[A-Z]+' "$HERE/TROUBLESHOOTING.md" \
         | awk '{print $2}' | sort -u)"
  # A section may cover two related checks (P7-CONF / P7-TPM share one), so
  # also accept IDs named in a combined heading.
  docs="$(printf '%s\n%s\n' "$docs" \
          "$(grep -oE '^## ([A-Z0-9]+-[A-Z]+ / )+[A-Z0-9]+-[A-Z]+' "$HERE/TROUBLESHOOTING.md" \
             | sed 's/^## //;s| / |\n|g')" | grep . | sort -u)"

  undocumented="$(comm -23 <(printf '%s\n' "$ids") <(printf '%s\n' "$docs"))"
  orphaned="$(comm -13 <(printf '%s\n' "$ids") <(printf '%s\n' "$docs"))"

  [ -z "$undocumented" ] \
    && ok "every verify.sh ID has a guide section ($(printf '%s' "$ids" | grep -c .) IDs)" \
    || { no "raised by verify.sh, absent from the guide:"; printf '      %s\n' $undocumented; }

  [ -z "$orphaned" ] \
    && ok "no guide section documents a check that no longer exists" \
    || { no "documented but never raised:"; printf '      %s\n' $orphaned; }
fi

# ── 7. doctor.sh diagnoses, never fixes ──────────────────────────────────────
# A diagnostic that repairs as it runs destroys the evidence of what was
# broken. Enforced statically rather than by convention.
head_ "7 · doctor.sh is read-only"
if [ ! -f "$HERE/doctor.sh" ]; then
  no "doctor.sh missing"
else
  mut="$(sed -e "s/'[^']*'//g" -e 's/#.*$//' "$HERE/doctor.sh" \
        | grep -nE '(^|[;&|(]|\$\()[[:space:]]*(cp|mv|rm|install|launchctl (bootstrap|bootout|load|unload)|brew install|npm install|git clone|chmod|mkdir)[[:space:]]')"
  [ -z "$mut" ] && ok "no mutating command in doctor.sh" \
                || { no "doctor.sh mutates:"; printf '      %s\n' "$mut"; }
fi

# ── 8. help.html is generated, not hand-edited ───────────────────────────────
# The client page embeds the guide, which would be a fourth copy of the failure
# knowledge if it were maintained by hand. Regenerate to a temp file and compare:
# a stale help.html fails here rather than quietly shipping advice that no
# longer matches TROUBLESHOOTING.md.
head_ "8 · help.html is current"
if [ ! -f "$HERE/help.html" ]; then
  no "help.html missing — run: python3 render-help.py"
elif ! command -v python3 >/dev/null 2>&1; then
  ok "help.html present (no python3 to re-render and compare)"
else
  tmp="$(mktemp)"
  if python3 "$HERE/render-help.py" "$tmp" >/dev/null 2>&1; then
    cmp -s "$tmp" "$HERE/help.html" \
      && ok "help.html matches TROUBLESHOOTING.md" \
      || no "help.html is STALE — run: python3 render-help.py"
  else
    no "render-help.py failed to run"
  fi
  rm -f "$tmp"
fi

# ── 9. syntax ────────────────────────────────────────────────────────────────
head_ "9 · syntax"
for s in bootstrap.sh install.sh verify.sh selftest.sh doctor.sh; do
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
  for s in bootstrap.sh install.sh verify.sh selftest.sh doctor.sh; do
    shellcheck -S error "$HERE/$s" >/dev/null 2>&1 \
      && ok "shellcheck $s (errors)" \
      || no "shellcheck found errors in $s"
  done
fi

printf '\n\033[1m%s\033[0m\n' "─────────────────────────────────────────"
printf '  %d passed · %d failed\n\n' "$PASS" "$FAIL"
exit "$FAIL"
