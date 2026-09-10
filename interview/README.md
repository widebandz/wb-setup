# interview/ — the judgment layer

Not yet written. This directory holds the prompts for the parts of a build
that have no correct default and therefore should not be a file.

The split this repo runs on:

| Category | Form | Lives in |
|---|---|---|
| byte-identical everywhere | a file | `dotfiles/` |
| same shape, few values differ | template + substitution | `templates/` |
| genuine judgment | **an interview** | here |
| "did it work?" | assertions | `verify.sh` |

Planned:

- **`operator.md`** — produces `~/.claude/USER.md` and the global
  `CLAUDE.md`. Who the operator is, how they want to be worked with,
  what they never want done without asking. Capped at 200 lines each.
- **`sessions.md`** — produces the tmux session list and `tmux-boot.sh`.
  The rule is "one session per concern, never one per task"; which
  concerns a given operator has is not derivable, which is exactly why
  this is an interview and not a file.
- **`fleetdeck.md`** — the four values in fleetdeck's `config.json`.

The test for whether something belongs here: if two competent operators
would correctly answer differently, it is judgment. If they would answer
the same, it is a file, and shipping it as a prompt just adds a chance to
get it wrong.
