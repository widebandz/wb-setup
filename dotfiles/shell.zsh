# shell.zsh — operator shell conveniences.
# Sourced from ~/.zshrc by wb-setup install.sh. Edit here, re-run install.sh.

# ── claude --yolo ───────────────────────────────────────────────────────────
# Translates --yolo to --dangerously-skip-permissions and passes everything
# else through untouched.
#
# Worth knowing what it does before you reach for it: the flag stops Claude
# Code asking before it edits files or runs commands. That is the right trade
# in a scratch session or a throwaway worktree, and the wrong one in a repo
# with a production deploy hook. The long name is deliberate friction; this
# alias removes the friction, not the consequence.
#
# `command claude` rather than a wrapper script in ~/bin, so the real binary
# keeps its own path and its auto-update keeps working.
claude() {
  local args=() a
  for a in "$@"; do
    case "$a" in
      --yolo) args+=(--dangerously-skip-permissions) ;;
      *)      args+=("$a") ;;
    esac
  done
  command claude "${args[@]}"
}

# ── tmux ────────────────────────────────────────────────────────────────────
# tm ls          every running session (tmux list-sessions)
# tm-standard    drift: which standard sessions are up, and where
alias tms='tm-standard'
