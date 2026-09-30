# wb-setup

The current 0.8.0 pilot is undergoing exact-artifact validation. The latest
published download remains the
[v0.7.1 unsigned DMG](https://github.com/widebandz/wb-setup/releases/tag/v0.7.1)
until those checks and the public release finish. The new package includes a
private toolchain, so a client profile can prepare the local Fleetdeck stack
without using another profile's Homebrew or waiting for an agent Apple Account.

The source bootstrap below builds the operator foundation but does not include
those bundled customer phone apps:

```bash
curl -fsSL https://raw.githubusercontent.com/widebandz/wb-setup/main/bootstrap.sh | bash
```

**Next release:** 0.8.0. This unsigned pilot requires the documented
Privacy & Security **Open Anyway** step.
Start with [BUILD-MEMORY.md](BUILD-MEMORY.md)
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
checks and activates the bundled private toolchain before local setup, and continues updating while
those tools install. Once the foundation exists, later launches run quietly
inside the branded app without requiring Terminal or browser knowledge.

## Shareable client app

The macOS package opens an embedded **Client view** by default. It uses the canonical
wideband.ai mark, palette, and type system, presents one human action at a time,
and opens the exact provider, app, or System Settings page for that action. A
responsibility strip distinguishes what Wideband installs, what the client must
approve, and what is customized together. The welcome flow explains the single
native setup steps run. The complete six-stage checklist remains
available behind **Operator view**.

The package also installs `~/Applications/Wideband Agent.app`, the single
branded macOS permission principal. Accessibility, Screen Recording, Full Disk
Access, and Messages Automation are requested and verified against that exact
app rather than trusting a checkbox or granting broad access to Terminal.
The iMessage head runtime also launches through that app. Clients can first
name the OS and agent, choose a provider and first goal, and prepare the local
tools and Fleetdeck without an agent Apple Account. Text activation is a
separate milestone: sign a separate agent Apple Account into Messages, send a
fresh text from the owner's phone, bind that exact chat, and confirm the
agent's reply on the phone. Apple Screen Sharing and other support access are
guided later.

The provider picker saves Claude Code, Codex, Gemini CLI, or Grok Build as a
private onboarding choice. Claude Code is the current Wideband iMessage runtime
path. The packaged client installs Claude Code only after Claude is selected
and its sign-in action is opened. The other choices are marked as previews and cannot activate the text
router until their sign-in, pane recognition, and reply path have been verified.
Changing the provider after a chat is bound requires an explicit runtime
migration so the saved choice cannot silently disagree with the active agent.

After the first real reply and the phone view are ready, the client opens the
private Fleetdeck phone home on their iPhone and confirms it works. That final
confirmation queues two owner-only iMessages through the guarded outbox: one
with the phone home, full board, agent, project, knowledge graph, live terminal,
network, and Notes beta links; the other with Claude and tmux commands plus
the Tailscale and Termius iPhone app links. Setup verifies each private HTTPS
page before queueing. The handoff card shows guarded outbox delivery; an
uncertain send is held for review and never retried automatically. Reopening
an older completed setup offers a manual send control instead of sending old handoff
texts automatically.

The phone view opens a six-key Fleetdeck home at `/phone` with Board, Project,
Terminals, Graph, Network, and Notes beta. Keys for unavailable services remain
visible as `not ready`. The full service board remains at `/board`, with a
four-square link back to the phone home. Its linked apps
show live tmux sessions, the read-only Live Terminal Network from this Mac's
services and sessions, and the Glitch Cat Knowledge Graph over a local graph
pack. Notes beta stores notes privately on this Mac, separately from the
operator Fleetdeck Notes store. The board and companion apps use private
Tailscale Serve routes and owner-only access.

The earlier real-stack UTM pilot passed source and embedded self-tests (83/83
each) and a restart check. One fresh owner iMessage reached the VM agent and
its reply arrived on the owner's iPhone. The owner also confirmed the full
phone board, its apps and Home Screen icon, and receipt of both setup handoff
texts. This was a single UTM and physical iPhone pilot for the 0.7.0 board.
The 0.7.1 phone home passed isolated WebKit checks at 375×667 and 393×852
using a copied candidate bundle and synthetic services. The new UI has not
yet been checked on a physical iPhone or in an installed Home Screen app.

Build the generic pilot from the two reviewed source checkouts:

```bash
./packaging/build-app.sh --fleetdeck-source /path/to/fleetdeck --graph-source /path/to/glitch-cat
```

The build requires both sources. It bundles only allowlisted tracked Fleetdeck installer files and
generic icons, plus the standalone customer portal. Local config, notes,
backups, `.git`, and the operator portal are excluded. Missing either reviewed
bundle stops packaging before a client installer can be produced.
The customer portal's Notes beta has its own private store on the client's Mac;
it does not import or sync the existing Fleetdeck operator Notes store.

Build a Developer ID signed artifact without submitting it for notarization:

```bash
./packaging/build-app.sh \
  --fleetdeck-source /path/to/fleetdeck \
  --graph-source /path/to/glitch-cat \
  --sign-identity "Developer ID Application: Wideband AI (…)"
```

For production, first store notarization credentials in a dedicated Keychain
profile, then build, submit, wait, staple, and validate in one command:

```bash
./packaging/build-app.sh \
  --fleetdeck-source /path/to/fleetdeck \
  --graph-source /path/to/glitch-cat \
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
./packaging/build-app.sh --fleetdeck-source /path/to/fleetdeck --graph-source /path/to/glitch-cat --profile /secure/path/client-profile.json
```

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
2. **Handles the AI provider** — the packaged client defers installation until
   you select Claude and open its sign-in action. The standalone operator
   bootstrap installs Claude Code from `claude.ai/install.sh` and adds
   `~/.local/bin` to `.zshrc`.
3. **Uses the downloaded package's verified private tools** for the client
   path. The separate source bootstrap downloads this repo as a tarball.
4. **Inspects Homebrew read-only** and records whether this login owns a
   healthy prefix. The packaged client uses its own Python, Node, tmux, ttyd,
   and `imsg` even if another profile owns `/opt/homebrew`. Only the legacy
   source/operator path may install or use an owned Homebrew after its health
   checks.
5. **Establishes the build identity** in `~/.sop-vars`. A personalized client
   package preloads approved values; a generic client package asks only for
   the owner's phone number. GitHub, commit identity, work repository, and
   extra graph packs can be filled in after local setup. An existing
   identity file is left alone.
6. **Keeps operator files separate** — the packaged client leaves `.zshrc`
   and existing Claude statusline, SOP, settings, and global instructions
   untouched. The standalone operator bootstrap places those four files,
   seeding settings and global instructions only when absent.
7. **Queues the human gates.** The generic bootstrap prints them; the packaged
   client app presents them later as branded, resumable popups.
8. **Verifies private tools** from a complete SHA-256 manifest for the
   packaged client. The legacy source/operator path continues to use
   `Brewfile`; an explicitly marked older 0.7.x install may use its own
   healthy Homebrew during migration.
9. **Opens Wideband Setup** on localhost unless `--no-ui` was requested.

The Wideband client tool payload stays under `$HOME` and asks for no password.
It never changes a foreign Homebrew prefix. Account sign-ins and permissions
remain explicit owner steps; no Apple Account is needed for the local first
job and Fleetdeck installation.

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
