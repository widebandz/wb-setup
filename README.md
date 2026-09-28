# wb-setup

Bare M-chip Mac → a complete operator build. One line:

```bash
curl -fsSL https://raw.githubusercontent.com/widebandz/wb-setup/main/bootstrap.sh | bash
```

**Current release:** 0.6.0. Start with [BUILD-MEMORY.md](BUILD-MEMORY.md)
for the complete architecture, security boundaries, release procedure, and
proven E2E behavior. [CHANGELOG.md](CHANGELOG.md) records what changed by
release; [AGENTS.md](AGENTS.md) carries the non-negotiable context for future
software agents.

When bootstrap finishes, it opens the resumable guided installer. If the guide
was closed or the build is being resumed later, run:

```bash
bash ~/srv/wb-setup/setup.sh
```

It opens a private local guide, stores progress in `~/.wideband/setup`, and
turns the full runbook into six stages. Deterministic work runs through an
allowlist; account access, macOS permissions, and the operator interview remain
explicit human gates.

For an unattended bootstrap or a scripts-only diagnostic run, pass `--no-ui`.

The embedded guide is backed by a server bound only to `127.0.0.1`; it requires
a random token passed privately by the app. Its API exposes named actions (`install`, `verify`,
`doctor`, approved System Settings links), never a caller-supplied command.
State, interview answers, backups, and the generated build record are mode
`0600`. Project secrets are neither requested nor written to installer state.
Port 8803 is preferred; if another process owns it, the app chooses a free
loopback port and embeds that exact private surface. Clients should always
reopen Wideband Setup rather than manually typing a localhost address. The UI
polls saved state, performs focused permission checks while a permission guide
is open, displays real proof timestamps, and gives a persistent recovery banner
if its engine disconnects. The app includes an arm64 engine, so the guide
appears even before a bare Mac has Homebrew, Command Line Tools, or Python. It
calls out Homebrew's one Terminal password action and continues updating while
those tools install. Once the foundation exists, later launches run quietly
inside the branded app without requiring Terminal or browser knowledge.

## Shareable client app

The macOS package opens an embedded **Client view** by default. It uses the canonical
wideband.ai mark, palette, and type system, presents one human action at a time,
and opens the exact provider, app, or System Settings page for that action. A
responsibility strip distinguishes what Wideband installs, what the client must
approve, and what is customized together. The welcome flow explains the single
Homebrew administrator-password prompt when a new Mac still needs it. The complete six-stage checklist remains
available behind **Operator view**.

The package also installs `~/Applications/Wideband Agent.app`, the single
branded macOS permission principal. Accessibility, Screen Recording, Full Disk
Access, and Messages Automation are requested and verified against that exact
app rather than trusting a checkbox or granting broad access to Terminal.
The iMessage head runtime also launches through that app. The first client
milestone is a real two-way text: choose an OS display name, an editable agent
name, a head-agent provider, and a first goal; sign a separate agent Apple
Account into Messages; send a fresh text from the owner's phone; bind that
exact chat; and confirm the agent's reply on the phone. Apple Screen Sharing
and other support access are guided later.

The provider picker saves Claude Code, Codex, Gemini CLI, or Grok Build as a
private onboarding choice. Claude Code is the current Wideband iMessage runtime
path. The other choices are marked as previews and cannot activate the text
router until their sign-in, pane recognition, and reply path have been verified.
Changing the provider after a chat is bound requires an explicit runtime
migration so the saved choice cannot silently disagree with the active agent.

After the first real reply and the phone view are ready, the client opens the
private Fleetdeck board on their iPhone and confirms it works. That final
confirmation queues two owner-only iMessages through the guarded outbox: one
with the dashboard, agent, project, knowledge graph, live terminal, and Notes
beta links; the other with Claude and tmux commands plus the Tailscale and
Termius iPhone app links. Setup verifies each private HTTPS page before
queueing. The handoff card shows guarded outbox delivery; an uncertain send
is held for review and never retried automatically. Reopening an older
completed setup offers a manual send control instead of sending old handoff
texts automatically.

Build the generic pilot:

```bash
./packaging/build-app.sh
```

For a self-contained customer phone portal on a blank Mac, pass a reviewed
Fleetdeck checkout when building the app:

```bash
./packaging/build-app.sh --fleetdeck-source /path/to/fleetdeck
```

This option bundles only allowlisted tracked Fleetdeck installer files and
generic icons, plus the standalone customer portal. Local config, notes,
backups, `.git`, and the operator portal are excluded. Without the option,
`install.sh --phone-only` retains a public-clone fallback; the current public
Fleetdeck release lacks the customer-mode guard and will stop that step rather
than expose writable services. Use `--fleetdeck-source` for a customer handoff.
The customer portal's Notes beta has its own private store on the client's Mac;
it does not import or sync the existing Fleetdeck operator Notes store.

Build a Developer ID signed artifact without submitting it for notarization:

```bash
./packaging/build-app.sh \
  --sign-identity "Developer ID Application: Wideband AI (…)"
```

For production, first store notarization credentials in a dedicated Keychain
profile, then build, submit, wait, staple, and validate in one command:

```bash
./packaging/build-app.sh \
  --sign-identity "Developer ID Application: Wideband AI (…)" \
  --notary-profile wideband-notary
```

The same settings can be supplied as `WIDEBAND_SIGN_IDENTITY` and
`WIDEBAND_NOTARY_PROFILE` in release automation. The builder refuses to
notarize an ad-hoc build and signs the engine, permission agent, app, and disk
image consistently.

For a client handoff, copy `packaging/client-profile.example.json` outside the
repository, fill it with that client's approved build identity, then build:

```bash
./packaging/build-app.sh --profile /secure/path/client-profile.json
```

Add `--fleetdeck-source /path/to/fleetdeck` to a personalized build as well
when that client's first phone view must work without fetching Fleetdeck.

The unsigned pilot produces `dist/Wideband-Setup-unsigned.dmg`; a fully trusted
release produces `dist/Wideband-Setup.dmg`. Either is one shareable file. The
generic client build asks for the owner's phone number in one native macOS
dialog; the guided UI collects the OS name, agent name, and first goal. A
personalized build seeds its approved identity values into `~/.sop-vars` once
and skips the phone question. An existing identity file is never overwritten.
The profile contains client identity data—not credentials—and is embedded only
in the intended client's app. Do not reuse one client's DMG for another client.
Every package build also writes `dist/SHA256SUMS.txt`; compare the recipient's
DMG against it before installation or VM testing.

Because the pilot is not notarized, current macOS versions require one initial
launch attempt followed by **System Settings → Privacy & Security → Open
Anyway**. The DMG includes both `READ ME FIRST.txt` and a direct **Open Privacy
& Security** shortcut for that handoff. A signed and notarized production build
will remove this exception step.

On first launch, the native app asks whether the client wants it to check for
updates when it starts. No network request is made until the client chooses.
The preference can be changed from the **Wideband Setup** menu, which also has
**Check for Updates…** and **View Version History…**. The public feed is
`https://os.wideband.ai/version`; it contains release metadata only and sends
no setup answers or machine identifiers. An available update opens the public
[GitHub Release history](https://github.com/widebandz/wb-setup/releases) for
review and download. The app never installs or runs an update without the
client, and unsigned pilots continue to require the documented Gatekeeper
handoff.

Machine-owned reconciliation starts automatically in packaged client mode.
Client-owned steps remain deliberate because macOS privacy grants, account
sign-ins, two-factor authentication, and the agent interview cannot be safely
impersonated. Progress survives closing the app or restarting the Mac. The app
installs a resumable copy into `~/Applications` even when the client launches
it directly from the disk image.

Client view also includes a live readiness dashboard and **Setup tools**:

- Status labels distinguish machine-observed proof from client-confirmed
  account, two-factor, and real-world outcomes.
- **Check this Mac** refreshes the read-only machine proof.
- **Repair Wideband** idempotently reconciles the managed runtime without
  replacing client-owned project work or curated configuration.
- **Copy diagnostics** and **Export support bundle** produce a deliberately
  narrow report that excludes credentials, two-factor codes, profile answers,
  `.sop-vars` values, and raw logs.
- **Deactivate Wideband services** stops the exact managed background jobs,
  including the text runtime, first-project preview, and Fleetdeck portal,
  and moves their definitions plus `Wideband Agent.app` into a private recovery
  folder. It preserves client work, account sign-ins, and macOS privacy
  choices. Reopen the packaged app and select **Repair Wideband** to restore
  the managed runtime.

You are about to pipe a URL into a shell, so here is exactly what that
does before you run it.

---

## What bootstrap.sh does

1. **Refuses** if the machine is not arm64, is running as root, is below
   macOS 13 (macOS 14 for the iMessage client path), or the target directory
   sits inside a TCC-protected folder.
2. **Installs Claude Code** — `claude.ai/install.sh`, the official
   installer. Adds `~/.local/bin` to your PATH in `.zshrc`.
3. **Downloads this repo** to `~/srv/wb-setup` as a tarball so the versioned
   Homebrew health guard is available before the package manager is touched.
4. **Verifies and starts Homebrew in the background**, logging to
   `/tmp/wb-bootstrap-brew.log`. It separately proves the intended user,
   `/opt/homebrew` ownership and writability, PATH, architecture, and Apple
   Command Line Tools/Git. It runs the selected developer Git and reports the
   Apple package receipt, so an incompatible post-upgrade toolchain is stopped
   for Software Update instead of being accepted merely because files exist.
5. **Establishes the build identity** in `~/.sop-vars`. A personalized client
   package preloads approved values; a generic client package asks only for
   the owner's phone number. GitHub, commit identity, work repository, and
   extra graph packs can be filled in after the first text. An existing
   identity file is left alone.
6. **Places four files** — a status line script, `~/.claude/SOP.md`,
   `~/.claude/CLAUDE.md`, and `~/.claude/settings.json` (only if you do
   not already have one).
7. **Queues the human gates.** The generic bootstrap prints them; the packaged
   client app presents them later as branded, resumable popups.
8. **Runs `brew bundle`** against `Brewfile.quick` for the packaged client
   path: Python, tmux, and `imsg` on macOS 14 or newer. The full operator path
   continues to use `Brewfile`.
9. **Opens Wideband Setup** on localhost unless `--no-ui` was requested.

The Wideband payload stays under `$HOME`, asks for no passwords, and sends
nothing anywhere. Apple Command Line Tools and Homebrew write to their own
system-managed locations only after visible client approval. Wideband never
runs an ownership repair automatically; any verified `/opt/homebrew` repair is
printed for the client to review and run personally.

For a read-only post-upgrade diagnosis:

```bash
bash ~/srv/wb-setup/bootstrap.sh --diagnose-homebrew
```

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
BUILD-MEMORY.md    durable architecture, decisions, security and E2E evidence
CHANGELOG.md       release history and client-visible changes
AGENTS.md          mandatory context and guardrails for software agents
SOP.md             the full procedure, universal
PREP.md            client-facing; send the day before setup
checklist.html     detailed reference checklist; guided app remains canonical
setup.sh           opens the resumable local guide (browser fallback)
setup.py           allowlisted runner, state, readiness, support and recovery APIs
installer/         six-stage manifest and embedded web interface
packaging/          branded app/DMG builder and client-profile renderer
tests/              browser and end-to-end release checks
Brewfile           core CLIs, declarative
vars.example       template for ~/.sop-vars
bin/               tm, tm-standard, tm-memory → copied to ~/bin
dotfiles/          byte-identical artifacts: statusline, shell.zsh
templates/         __TOKEN__ files rendered by install.sh
skills/            agent skills installed for Claude and Codex
loops/             LaunchAgent jobs — cost-watch, tmux-boot, healthcheck
lib/               bare-Mac-safe Homebrew and developer-tools health guard
interview/         judgment-layer status and future interview designs
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
