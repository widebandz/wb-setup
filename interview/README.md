# interview/ — the judgment layer

The first judgment workflow is now implemented in the guided installer. The
operator interview lives in `installer/app.js` and `setup.py`, previews a
human-readable profile, enforces the 200-line cap, and writes the approved
result privately to `~/.claude/USER.md`. Existing profiles are backed up before
replacement, and the answers remain in private installer state.

This directory remains the design home for judgment workflows that do not yet
have an implemented UI. See `BUILD-MEMORY.md` for the installer architecture
and ownership boundaries.

The split this repo runs on:

| Category | Form | Lives in |
|---|---|---|
| byte-identical everywhere | a file | `dotfiles/` |
| same shape, few values differ | template + substitution | `templates/` |
| genuine judgment | **an interview** | here |
| "did it work?" | assertions | `verify.sh` |

Status:

- **Operator profile — implemented.** Produces `~/.claude/USER.md`: who the
  operator is, how they want to be worked with, and what must never happen
  without approval. Preview and explicit apply remain separate actions.
- **`sessions.md`** — produces the tmux session list and `tmux-boot.sh`.
  The rule is "one session per concern, never one per task"; which
  concerns a given operator has is not derivable, which is exactly why
  this is an interview and not a file. Not yet implemented as a standalone
  interview. What each session *is* now has a home either way:
  `skills/agent-session-memory` and `bin/tm-memory` store one identity card
  per durable concern. `tm-memory adopt` drafts them from live evidence and
  marks everything it could not verify, which is the same boundary — the
  derivable half becomes a file, the judgment half stays a question.
- **`fleetdeck.md`** — the values in fleetdeck's `config.json`. Not yet
  implemented as a standalone interview.

The test for whether something belongs here: if two competent operators
would correctly answer differently, it is judgment. If they would answer
the same, it is a file, and shipping it as a prompt just adds a chance to
get it wrong.
