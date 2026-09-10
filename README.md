# wb-setup

Bare M-chip Mac → a complete operator build. One line:

```bash
curl -fsSL https://raw.githubusercontent.com/widebandz/wb-setup/main/bootstrap.sh | bash
```

You are about to pipe a URL into a shell, so here is exactly what that
does before you run it.

---

## What bootstrap.sh does

1. **Refuses** if the machine is not arm64, is running as root, is below
   macOS 13, or the target directory sits inside a TCC-protected folder.
2. **Installs Claude Code** — `claude.ai/install.sh`, the official
   installer. Adds `~/.local/bin` to your PATH in `.zshrc`.
3. **Starts Homebrew in the background**, logging to
   `/tmp/wb-bootstrap-brew.log`. Nothing after this waits on it.
4. **Downloads this repo** to `~/srv/wb-setup` as a tarball.
5. **Asks you eight questions** and writes the answers to `~/.sop-vars`.
   If that file already exists it is left alone.
6. **Places four files** — a status line script, `~/.claude/SOP.md`,
   `~/.claude/CLAUDE.md`, and `~/.claude/settings.json` (only if you do
   not already have one).
7. **Prints a checklist** of sign-ins and macOS permission dialogs to work
   through while the download runs.
8. **Runs `brew bundle`** against the `Brewfile` in this repo.

It writes nothing outside `$HOME`, asks for no passwords, and sends
nothing anywhere. The Homebrew installer it invokes will ask for `sudo`
on its own — that is Homebrew, not this script.

To watch before committing: `--no-brew --no-claude` does everything
except the two installs.

---

## Why this order

Three resources are in play on install day and they do not contend:

| Lane | Resource | Behaviour |
|---|---|---|
| **Machine** | CPU + network | unattended once started |
| **Human** | attention, 2FA | the scarce one |
| **Agent** | Claude Code | does the bulk, once authed |

Claude Code's installer has **zero dependencies** — no Node, no Homebrew,
no Command Line Tools. So it is not behind the Homebrew download, and the
agent can be live and working before the long download finishes. The
common mistake is installing Homebrew first and waiting on it.

The human lane is the real bottleneck, which is why step 7 exists: the
script hands you work to do rather than a progress bar to watch. Most of
those account sign-ins can be done the day before, on any device, and
should be.

---

## The tool budget

Before Homebrew lands, `bootstrap.sh` may use **only** `bash`, `curl`,
`tar`, `sed`, `awk`, and `grep`.

A bare macOS has no `git` and no `python3` — `/usr/bin/git` and
`/usr/bin/python3` are stubs that pop the Command Line Tools dialog and
block. That is why this repo arrives as a tarball rather than a clone.
`selftest.sh` asserts the budget, because it is the constraint most likely
to regress the next time someone adds a step.

`bash` is 3.2 on macOS. No associative arrays, no `mapfile`.

---

## Layout

```
bootstrap.sh       the one-liner target — bare-Mac safe
install.sh         phases 5, 7, 8; needs brew, jq and an authed agent
verify.sh          per-phase assertions; every failure carries a [check ID]
doctor.sh          full machine state, one pasteable block; never fixes
TROUBLESHOOTING.md the six root-cause classes, every check ID, and day two
help.html          GENERATED client page — plain-language + the full guide
render-help.py     builds help.html; selftest fails if it is stale
selftest.sh        invariants of this repo, not of the machine it built
SOP.md             the full procedure, universal
PREP.md            client-facing; send the day before setup
checklist.html     108-step interactive checklist; open it directly, no server
Brewfile           core CLIs, declarative
vars.example       template for ~/.sop-vars
bin/               tm, tm-standard → copied to ~/bin
dotfiles/          byte-identical artifacts: statusline, shell.zsh
templates/         __TOKEN__ files rendered by install.sh
loops/             LaunchAgent jobs — cost-watch, tmux-boot, healthcheck
interview/         the judgment layer (not yet written)
```

Loops carry no hardcoded identity. `cost-watch` reads `~/.sop-vars`;
`tmux-boot` and `healthcheck` need no identity at all. `selftest.sh`
asserts that property rather than asserting every loop reads the file —
those are different claims, and only the first one is the invariant.

**Deterministic things are files. Judgment is a prompt.** The status line
is a file because it is solved and has two non-obvious failure modes an
LLM would eventually get wrong. The tmux session list is a prompt because
which sessions an operator needs is not derivable.

---

## Identity

Everything identity-shaped lives in `~/.sop-vars` and nothing else. No
script in this repo hardcodes an org, a phone number, or a hostname.

`MACHINE` and `TAILNET` are deliberately not variables — they resolve
from Tailscale at runtime. Pinning them is how a build stops being
portable.

---

## Verifying a build

```bash
bash verify.sh          # everything
bash verify.sh --quick  # skip network-bound checks
```

Assertions, not executions. Exit code is the number of failures, so it
composes into a gate.

A verifier that reports all green on a machine with known gaps is broken.
If a fresh build prints nothing but `✓`, distrust the verifier before
trusting the build.

## When something breaks

```bash
bash doctor.sh > /tmp/doctor.txt    # paste this to the agent
```

Each `✗` from `verify.sh` carries a stable ID — `[P0-FDA]`, `[P8-EXIT]` —
with a matching section in `TROUBLESHOOTING.md`. `selftest.sh` asserts the
two stay in sync **both ways**: an ID with no section fails, and a section
for a check that no longer exists fails too. The guide cannot rot quietly.

`doctor.sh` reports resolved real paths, launchd exit codes, and drift
between installed artifacts and the repo — the three things that are almost
never in a description of the problem and almost always in the cause.
