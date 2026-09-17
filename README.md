# wb-setup

Bare M-chip Mac → a complete operator build. One line:

```bash
curl -fsSL https://raw.githubusercontent.com/widebandz/wb-setup/main/bootstrap.sh | bash
```

When bootstrap finishes, it opens the resumable guided installer. If the
browser was closed or the build is being resumed later, run:

```bash
bash ~/srv/wb-setup/setup.sh
```

It opens on localhost, stores progress privately in `~/.wideband/setup`, and
turns the full runbook into six stages. Deterministic work runs through an
allowlist; account access, macOS permissions, and the operator interview remain
explicit human gates.

For an unattended bootstrap or a scripts-only diagnostic run, pass `--no-ui`.

The server binds only to `127.0.0.1` and requires a random token kept in the
browser URL fragment. Its API exposes named actions (`install`, `verify`,
`doctor`, approved System Settings links), never a caller-supplied command.
State, interview answers, backups, and the generated build record are mode
`0600`. Project secrets are neither requested nor written to installer state.
Port 8803 is preferred; if another process owns it, the app chooses a free
loopback port and opens that exact private URL. Clients should always reopen
Wideband Setup rather than manually typing a localhost address. The page polls
saved state without rerunning protected checks, displays its real connection
and proof timestamps, and gives a persistent recovery banner if Terminal closes.
The app includes an arm64 localhost engine, so this guide appears even before a
bare Mac has Homebrew, Command Line Tools, or Python. It calls out the one
Terminal password action and continues updating while those tools install.

## Shareable client app

The macOS package opens in **Client view** by default. It uses the canonical
wideband.ai mark, palette, and type system, presents one human action at a time,
and opens the exact provider, app, or System Settings page for that action. A
welcome popup explains the visible Terminal window and the single Homebrew
administrator-password prompt. The complete six-stage checklist remains
available behind **Operator view**.

The package also installs `~/Applications/Wideband Agent.app`, the single
branded macOS permission principal. Accessibility, Screen Recording, Full Disk
Access, and Messages Automation are requested and verified against that exact
app rather than trusting a checkbox or granting broad access to Terminal.
Scheduled health and workspace jobs also launch through that app so macOS shows
one recognizable Wideband Agent background item instead of generic bash or
Python entries.
Apple Screen Sharing is guided separately for private visual support.
Those access steps are deliberately first in the client queue, before account
and customization work, so a support path exists while the rest is installed.

Build the generic pilot:

```bash
./packaging/build-app.sh
```

For a client handoff, copy `packaging/client-profile.example.json` outside the
repository, fill it with that client's approved build identity, then build:

```bash
./packaging/build-app.sh --profile /secure/path/client-profile.json
```

The resulting `dist/Wideband-Setup-unsigned.dmg` is one shareable file. The
generic build collects six build-identity details in plain-language macOS
popups; a personalized build seeds those approved values into `~/.sop-vars`
once and skips those questions. An existing identity file is never overwritten.
The profile contains client identity data—not credentials—and is embedded only
in the intended client's app. Do not reuse one client's DMG for another client.

Because the pilot is not notarized, current macOS versions require one initial
launch attempt followed by **System Settings → Privacy & Security → Open
Anyway**. The DMG includes both `READ ME FIRST.txt` and a direct **Open Privacy
& Security** shortcut for that handoff. A signed and notarized production build
will remove this exception step.

Machine-owned reconciliation starts automatically in packaged client mode.
Client-owned steps remain deliberate because macOS privacy grants, account
sign-ins, two-factor authentication, and the agent interview cannot be safely
impersonated. Progress survives closing the browser or restarting the Mac.

Client view also includes a live readiness dashboard and **Setup tools**:

- Status labels distinguish machine-observed proof from client-confirmed
  account, two-factor, and real-world outcomes.
- **Check this Mac** refreshes the read-only machine proof.
- **Repair Wideband** idempotently reconciles the managed runtime without
  replacing client-owned project work or curated configuration.
- **Copy diagnostics** and **Export support bundle** produce a deliberately
  narrow report that excludes credentials, two-factor codes, profile answers,
  `.sop-vars` values, and raw logs.
- **Deactivate Wideband services** stops the three managed jobs and moves their
  definitions plus `Wideband Agent.app` into a private recovery folder. It does
  not delete client work or silently change Remote Login, Screen Sharing, or
  macOS privacy choices. Reopen the packaged app and select **Repair Wideband**
  when the managed runtime should be restored.

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
5. **Establishes the build identity** in `~/.sop-vars`. A personalized client
   package preloads the approved values; the generic client package asks six
   plain-language questions in native macOS popups. If that file already
   exists it is left alone.
6. **Places four files** — a status line script, `~/.claude/SOP.md`,
   `~/.claude/CLAUDE.md`, and `~/.claude/settings.json` (only if you do
   not already have one).
7. **Queues the human gates.** The generic bootstrap prints them; the packaged
   client app presents them later as branded, resumable popups.
8. **Runs `brew bundle`** against the `Brewfile` in this repo.
9. **Opens Wideband Setup** on localhost unless `--no-ui` was requested.

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
`tar`, `sed`, `awk`, and `grep`. Packaged client mode may additionally use
macOS's built-in `/usr/bin/osascript` to collect identity through native
Wideband Setup dialogs; it still invokes no package-managed tool.

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
install.sh         phases 5, 7, 8, 9; needs brew, jq and an authed agent
verify.sh          per-phase assertions; every failure carries a [check ID]
doctor.sh          full machine state, one pasteable block; never fixes
TROUBLESHOOTING.md the six root-cause classes, every check ID, and day two
help.html          GENERATED client page — plain-language + the full guide
render-help.py     builds help.html; selftest fails if it is stale
selftest.sh        invariants of this repo, not of the machine it built
SOP.md             the full procedure, universal
PREP.md            client-facing; send the day before setup
checklist.html     106-step detailed checklist; open it directly, no server
setup.sh           opens the resumable localhost guided installer
setup.py           allowlisted runner, state, readiness, support and recovery APIs
installer/         six-stage manifest and browser interface
packaging/          branded app/DMG builder and client-profile renderer
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

For a client handoff, open **Setup tools** in Wideband Setup first. The exported
support ZIP is the safe default to share because it omits identity-file values,
profile answers, raw logs, and common credential formats. **Repair Wideband**
reconciles the same deterministic install path used during initial setup.

For an operator working directly on the Mac:

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
