# Wideband Setup build memory

This is the durable product and engineering context for `wb-setup`. It is meant
for the next Wideband operator or software agent who needs to continue the
build without reconstructing decisions from chat history.

## Current baseline

- Product: **Wideband Setup**, a guided installer for a custom Wideband AI
  operator workstation.
- Source target: **0.8.3** unsigned pilot. The 0.8.0 DMG passed local package
  gates and is being published without a 0.8.0 VM or phone run at the owner's
  direction. The owner selected the phone home with a
  full-board key for client Home Screen installs. Developer ID signing and
  notarization remain future production work.
- Real-stack functional checkpoint: `434970f` (`feat: pilot real Fleetdeck phone
  stack in setup`).
- Platform: Apple silicon; macOS 14 or newer for the iMessage client path (the general operator path can run on macOS 13).
- Preferred private setup port: `8803`, with automatic loopback fallback when
  that port is occupied.
- Distribution: one DMG; the pilot is ad-hoc signed and intentionally
  labeled `unsigned` until Wideband supplies its Developer ID and notarization
  credentials.
- Updates: client-controlled startup or manual checks against
  `https://os.wideband.ai/version`; artifacts and public version history live
  in GitHub Releases. The app never silently installs an update.
- Update delivery status: v0.8.0 is a public GitHub prerelease. Its Pages feed
  and a fresh public DMG download matched the exact build and SHA-256 on
  2026-10-02. The skipped VM and physical phone gates remain onsite pilot
  checks, not completed release evidence.
- v0.8.1 is also a public GitHub prerelease. The Pages workflow for source
  `1d667db` succeeded, `https://os.wideband.ai/version` advertised build
  `0.8.1-20261002205106` and its exact checksum, and a fresh public DMG
  download matched the tested SHA-256 on 2026-10-02. The onsite Mac is the
  first real-machine upgrade gate for this hotfix; no VM, restart, iMessage,
  or phone-board proof has been recorded for this exact build.
- The exact 0.8.2 build `0.8.2-20261002215109` passed source and packaged
  self-tests (97/97 each), the packaged browser E2E, recursive ad-hoc
  signature verification, arm64 binary inspection, and `hdiutil verify`.
  Its DMG SHA-256 is
  `bacc83d2fb62b5dd197e75a3645627def99158a29801cbcdd69058677c685c54`.
  A real 0.8.2 VM/reboot, physical iMessage, and iPhone board proof have not
  been recorded.
- v0.8.2 is a public GitHub prerelease at source commit `a8280ff`. The Pages
  workflow `37069641422` succeeded; `https://os.wideband.ai/version`
  advertised the exact 0.8.2 build and SHA-256, and a fresh public DMG
  download matched that hash on 2026-10-02. Onsite retry, VM/reboot,
  physical iMessage, and iPhone board proofs are still pending for this build.
- The exact 0.8.3 build `0.8.3-20261002222812` passed source and packaged
  self-tests (97/97 each), packaged browser E2E, recursive ad-hoc signature,
  arm64 binary inspection, and `hdiutil verify`. Its DMG SHA-256 is
  `1e3ca3f3f50d5bc8fcdcf92c4ed75e1023ad25ba6f8806e046680631bf954554`.
  No 0.8.3 VM/reboot, physical iMessage reply, or iPhone board proof is
  recorded; those remain onsite pilot gates.
- October 2 onsite defect: a packaged 0.8.0 private Python import wrote new
  `__pycache__` files into the manifest-protected standard library. The next
  resolver reported `invalid_manifest` and all private tools appeared missing.
  This reproduced with the exact released payload: 2,642 manifest files became
  2,711 files after ordinary imports, with 69 new `.pyc` files. The 0.8.1
  candidate stages Python's standard-library directories without owner write
  permission; the same import sequence leaves 2,642 files and resolves again.
  A newer build ID stages alongside the old version and activates a fresh
  private version without changing Homebrew. This is not evidence that the
  onsite Full Disk Access grant is present or absent.
- The exact 0.8.1 candidate build `0.8.1-20261002205106` passed source and
  packaged self-tests (97/97 each), packaged Setup browser E2E, recursive
  ad-hoc signature validation, arm64 binary inspection, and `hdiutil verify`.
  Its DMG SHA-256 is
  `9e4d8366f4204759a823fa6e1d87863110b67349746a61f4f94647463478188d`.
  The exact packaged private tool payload remained at 2,642 files after
  imports, resolver recheck, and same-build activation. The 0.8.1 VM, reboot,
  iMessage, and iPhone checks have not been run.
- October 2 fresh-Mac Fleetdeck defect: the client map answered HTTP 200 with
  `status=partial` and `summary.live_sessions=null` while no tmux server had
  ever been started. The 0.8.1 phone-stack installer required an integer count
  and stopped before its chat/ttyd step. The 0.8.2 candidate recognizes only
  tmux's exact missing-server response as zero observed sessions; unrelated
  command failures remain unknown. A source regression uses an isolated tmux
  socket and asserts a zero count. The 0.8.1 client guide also hid its phone
  install retry button for `needs_attention`; 0.8.2 exposes an explicit retry.
  The retry restarts the map LaunchAgent before the data probe so an unchanged
  plist cannot keep an older map process running after a Setup update.
  The 8790 portal, 4181 graph proxy, and 18790 map were listening on the
  client, but their full data and phone handoff were not yet verified.
- After 0.8.2 cleared the map gate onsite, `:8783` and its ttyd child `:8784`
  both listened, but the client terminal probe failed with no tmux server.
  The reviewed customer chat server called tmux `list-sessions` from its
  health request and returned 500 for the exact missing-server response.
  The 0.8.3 candidate reports an empty terminal list for only that response,
  retains errors for other tmux failures, and restarts the managed chat job
  on retry. Owner-chat binding uses `imsg` chats/group/history under Wideband
  Agent and does not call tmux; its earlier failure remains a separate gate.
  The onsite report also found ttyd's internal basic-auth argument in a chat
  log with mode 0644. The 0.8.3 candidate prepares managed logs mode 0600,
  discards ttyd child output, rotates the installer-generated internal ttyd
  credential, and clears the older chat log during retry. Customized auth
  stops for review. The bind handoff now records only an allowlisted failure
  code; its raw stdout/stderr remain temporary and private. The installed
  Wideband Agent can remain at its older build when the normalized source
  revision is unchanged; the different embedded CDHash alone does not call
  for replacement or a new macOS grant. A bare 8790 request returning 403 is
  the intended owner access boundary, not a portal outage.
- Last release Apple Silicon VM checkpoint: 2026-09-28. The exact 0.7.0 DMG
  upgraded the earlier clean UTM pilot and recovered its private board, map,
  graph, terminal, Notes, and setup link. The earlier clean-install/reboot and
  owner iPhone proof are recorded below.
- Local 0.7.1 preparation checkpoint: a pre-version candidate build
  `0.7.0-20260930000358` passed isolated WebKit phone-layout, video, private
  access, board-return, and PWA metadata checks on a copied bundle with
  synthetic services. The exact 0.7.1 DMG is audited separately before release.

Generated build IDs and hashes belong to artifacts, not source. Read
`dist/Wideband Setup.app/Contents/Resources/build-id.txt` and
`dist/SHA256SUMS.txt` for the artifact currently on disk.

## Product promise

The client receives one branded installer. Wideband performs deterministic
machine work; the client performs only actions that macOS or an account
provider requires from the owner; the operator profile and real-world handoff
are completed together.

The app must never imply that installation success means every human gate is
complete. It reports machine evidence and human confirmation as different
proof types.

The client-facing contract is:

1. Open the DMG and launch Wideband Setup.
2. For an unsigned pilot, approve the one-time Gatekeeper exception.
3. Follow one action at a time in the branded native window.
4. Enter the administrator password only into a visible macOS prompt. The
   packaged 0.8.0 client toolchain requires no Homebrew installation.
5. Approve privacy access only for the exact app named **Wideband Agent**.
6. Complete provider sign-ins and two-factor prompts personally.
7. Close and reopen `~/Applications/Wideband Setup.app` at any time to resume.

The client does not need a separate localhost URL or a second setup guide. The
DMG contains `READ ME FIRST.txt` and an **Open Privacy & Security** shortcut.

## Responsibility model

| Owner | Work |
|---|---|
| **Wideband installs** | A private, verified client toolchain, local first-job and Fleetdeck surfaces, guarded Messages runtime after account proof, app payload, verification, repair, and private state. The separate legacy operator bootstrap can still use a healthy, owned Homebrew. |
| **Client approves** | Administrator-password prompts, Gatekeeper exception for an unsigned pilot, Apple Remote Login and Screen Sharing, Full Disk Access, Accessibility, Screen Recording, Messages Automation, provider logins, and two-factor challenges. |
| **Together** | Build identity, operator interview, approved deviations, client-specific workflows, phone/Tailscale proof, test message, first scheduled brief, and final handoff. |

This ownership model appears in the UI as **Wideband installs / You approve /
We customize together** and should remain visible.

## Runtime architecture

```text
Wideband-Setup*.dmg
  └─ Wideband Setup.app (native AppKit + WebKit shell)
       ├─ app-launcher
       │    ├─ installs a resumable copy in ~/Applications
       │    ├─ installs ~/Applications/Wideband Agent.app
       │    ├─ copies the managed payload to ~/srv/wb-setup
       │    └─ starts the private engine in Terminal or background mode
       └─ WKWebView
            └─ authenticated http://127.0.0.1:<selected-port>
                 ├─ saved installer state
                 ├─ allowlisted actions and guided steps
                 ├─ live verification evidence
                 └─ support, repair, record, and recovery APIs
```

### Native shell

`packaging/WidebandSetupLauncher.swift` is a visible AppKit application with a
`WKWebView`. It shows a branded loading state while the engine starts, then
loads the authenticated local guide. External provider and System Settings
links open outside the embedded view.

The native shell also owns update consent. On the first launch it asks before
making an Internet request. If the client opts in, later launches perform one
asynchronous check without delaying the local setup engine; automatic network
errors stay quiet, while the manual menu action reports them. The menu also
lets the client disable startup checks and open the complete version history.

The schema-1 feed is capped at 64 KiB and accepted only from the exact HTTPS
host/path `os.wideband.ai/version` (including the Pages trailing-slash form).
It must identify `wideband-setup`, Apple silicon, a known artifact trust state,
a numeric release/build ID, and a lowercase SHA-256. Download, release-note,
and history links are pinned to `github.com/widebandz/wb-setup/releases` with
the version and artifact name embedded in the exact path. An update notice
opens the public release page for human review; it does not download, mount,
install, or execute the asset.

The shell reads `~/.wideband/setup/connection.json`, waits for the exact build
ID packaged with the app, and continues polling after the first load. If an
upgrade replaces an older engine or the connection changes, it reloads the new
authenticated endpoint instead of leaving the client on a stale red reconnect
screen.

### App launcher and bare-Mac boundary

`packaging/app-launcher` is the Finder entry point. It preserves previous
package copies under the private setup backup area, never overwrites an
existing client identity, and installs the exact launched app into
`~/Applications/Wideband Setup.app` so the DMG can be ejected.

On a bare Mac, the native window opens immediately from the bundled arm64
engine. The 0.8.0 client app checks its complete tool payload, installs a
private copy in the intended user's home, and does not need Homebrew or Apple
Command Line Tools to start the local core. Terminal may still host bootstrap
or recovery; later app launches start the guide quietly in the background.

If bootstrap exits after a canceled owner-phone prompt while the guide remains
live, reopening the app relaunches Terminal when bootstrap reports
`needs_attention` and the core foundation is incomplete. An active identity
prompt keeps its single Terminal session. When Terminal completes bootstrap
under the native app, its setup handoff passes `--no-open` so Safari does not
open a second installer window.

Before touching Homebrew, `lib/bootstrap-homebrew.sh` independently proves the
invoking user, UID, home owner, console user, administrator membership,
architecture, PATH, selected Apple developer directory, developer Git, and the
ownership/writability of the exact `/opt/homebrew` prefix. This is required for
machines upgraded from an older macOS release: the prefix can survive while
Command Line Tools is removed or deselected, and a previous ownership context
can make `brew` executable but unusable.

The developer-tools probe executes the selected Git binary and reports the CLT
package receipt version. A present-but-unrunnable toolchain is a separate
`needs_developer_tools_update` state. It directs the client to Apple's Software
Update and never deletes or forcibly reinstalls `/Library/Developer`.

The bootstrap never runs an ownership repair. It can print a scoped repair only
when `/opt/homebrew` is a real, recognized Homebrew directory on arm64; the
current user owns their unsymlinked home; the GUI console user matches; and the
user is an administrator. The command changes only mismatched objects on the
same filesystem and does not follow symlinks. The client must personally review
and run it, then reopen Wideband Setup so the entire preflight runs again. The
permission repair is directory-only; it does not make the entire Homebrew tree
writable file by file. A blocked health state is authoritative even when stale
tool executables remain in `bin`; those files must never turn the final state
back into a false `ready` or be invoked as a fallback.

Extended ACLs and file flags on the standard Homebrew directories are a hard
stop for generated ownership advice. The scoped repair is printed only when
plain owner/UID or owner-write bits fully explain the failure.

### Private setup engine

`setup.py` serves the UI and API on `127.0.0.1`. Port `8803` is preferred; a
free loopback port is selected automatically when it is busy. The current
port, PID, build ID, release, start time, and random token are written to a
mode-`0600` connection file.

Every `/api/*` route requires the token. Static UI assets are readable only on
the local machine. Actions are selected from explicit allowlists; requesters
cannot supply shell commands.

Important API surfaces include:

- state, manifest, health, and job status;
- named install, verify, doctor, and supported open/request actions;
- focused live permission checks;
- operator-interview preview and apply;
- build-record generation;
- redacted support-bundle export;
- recoverable deactivation; and
- authenticated shutdown.

### Saved state

The canonical state directory is `~/.wideband/setup` with directory mode
`0700`. Sensitive state and generated records use mode `0600`.

Key objects:

| Path | Purpose |
|---|---|
| `connection.json` | Private runtime rendezvous; contains the local access token and must never be pasted into support channels. |
| `state.json` | Completed steps, action runs, verification, interview data, deviations, and lifecycle state. |
| `engine.log` | Local engine diagnostics; excluded from the client support ZIP. |
| `build-record.md` | Private per-machine handoff record. |
| `support/` | Redacted support bundles. |
| `package-backups/` | Replaced payload, app, and agent copies. |
| `deactivations/` | Recoverable service and agent moves plus a receipt. |

### One-owner iMessage head runtime (post-0.6.0 working tree)

The 0.6.0 permission guide checks Messages Automation but does not make
texting an agent work. The new runtime is staged as `~/bin/wb-imessage` and
four `com.$ORG.imessage-*` LaunchAgents. It requires macOS 14 or newer because
the upstream `imsg` transport does; the general setup baseline remains macOS
13 until a release decision changes it. The Brewfile trusts only
`steipete/tap/imsg`, not the entire third-party tap.

```text
owner's phone → Messages on the agent Mac → imsg watch
  → private, deduplicated inbound queue → exact bound-chat router
  → live agent pane in persistent wb-head tmux session
  → agent writes ~/wideband/head/outbox/*.txt
  → guarded outbox worker → imsg send --chat-id → owner's phone
```

The client personally signs a **separate Apple Account** into Messages and
sends the first text. `wb-imessage init` reads identity and display names from
JSON on stdin, keeping the phone number out of argv and command history. A
provider picker saves `agent_provider` in private onboarding metadata. New
builds require an explicit choice; older completed builds without that field
migrate to Claude. Codex, Gemini CLI, and Grok Build are selectable previews,
but setup refuses to activate their iMessage head sessions until each provider
has a verified sign-in, pane-recognition, instruction-file, and guarded-reply
path. A bound chat cannot change provider through onboarding because that
would mislabel the active head agent. The current tested path remains Claude.
The later `bind --confirm-separate-account` accepts only one exact, one-to-one
iMessage chat with the configured owner as its sole participant and a fresh
inbound message. It pins the live chat ID, GUID and Messages account; an
unbound or changed target does not receive messages. The client confirms the
separate-account fact and the first reply on the phone; machine checks alone
cannot prove either human fact.

The setup engine starts binding with `open -W -n` through the Wideband Agent
app bundle. Launching the executable directly from Terminal inherits Terminal's
Full Disk Access context even when the app has its own grant. App stdout and
stderr go to short-lived mode-`0600` files under private setup state. macOS
`open` may exit successfully when the app task fails, so the runner activates
services only after the exact runtime bind success line appears with no app
stderr; raw output is removed and never copied into setup state or support.

`install.sh --imessage-only` copies scripts and renders plists into a private
staging folder without running the broader workstation install. Before binding,
it also moves any exact prior Wideband iMessage plists out of
`~/Library/LaunchAgents/` and boots out those jobs: a plist left there can load
at the next GUI login even if it was never manually bootstrapped. It installs
and loads the four jobs only after the private binding exists.
`verify.sh --imessage-only --json` reports just six runtime
checks, so deferred GitHub and Fleetdeck work do not mark first text as
incomplete. Every job enters through `Wideband Agent
run-background-task`, keeping that app as the intended macOS permission
principal. The UTM pilot proved the Agent's Full Disk Access grant and a real
guarded iMessage reply received on the owner's phone. The router refuses to
type into a bare shell. The agent never
chooses an outbound recipient; the outbox rechecks the bound chat and applies
file type, ownership, text length and rate limits. An uncertain send is held
for review rather than retried, to avoid duplicate texts. Raw owner messages
and replies stay inside mode-`0700` runtime directories; installer-owned state
files use mode `0600`.

### First job and real customer phone stack (post-0.6.0 working tree)

The first-goal runner stages **one** chosen recipe: research, a starter
website, or a proposal. It creates `~/wideband/first-project` for every recipe;
the selected result becomes the first project tile. It does not install every
possible tool up front. The phone stack follows a confirmed owner iMessage
reply and the staged first project.

`~/srv/fleetdeck` (version 1.2.0, source commit `092d6be`) is the **main
Fleetdeck source repository** for this product.
The 0.7.0 pilot bundles its tracked `portal_server.py`, registry
scanner, assets, and the reviewed deployed terminal server into the DMG. The
bundle removes operator identity and adds a narrow customer access adapter.
`install.sh --phone-only` stages that reviewed bundle on the client Mac and
installs the board, the interactive tmux terminal, the local Live Terminal
Network collector, and Glitch Cat's real Knowledge Graph. It registers the
client's own services and project in that client's Fleetdeck registry. The
operator Mac's runtime database, sessions, notes, tokens, and identities are
never transferred. The Glitch Cat rights holder expressly authorized public
distribution of the reviewed source inside the 0.7.0 installer on September
28, 2026. The standalone repository remains private; this is not an open
source license for reuse outside the installer.

Five per-user LaunchAgents persist the board, map, graph engine, owner-gated
graph proxy, and terminal server. The board is private HTTPS Serve `:8790`,
the terminal `:8783`, the graph proxy `:8792` (local `:4181`), and the map
`:18970` (local `:18790`). The graph engine `:4180` and terminal's `ttyd`
child `:8784` bind loopback only and are hidden as internal plumbing on the
board. The map reads the client's actual tmux and service state; the graph
builds a private SQLite index of client-local files and shows its build
timestamp. Rebuild the graph after meaningful project or service changes; it
is a knowledge index, not a live tmux feed. The published 0.7.0 customer
adapter serves the full Fleetdeck board at `/board` and `/phone`; it does not
expose upstream Fleetdeck's clock-and-key simple screen or its four-square
switch. The board retains the real service scan rather than serving the
earlier fixed five-card customer page. Notes beta is visible from the real
board and opens its existing private route.

The phone board opens through a persistent 256-bit owner capability at
`/p/<token>/board`; it establishes a secure, HttpOnly, same-site session
cookie. Bare board/status routes, the graph's page/API, and the terminal's
HTTP/WebSocket endpoints require that owner session. The terminal additionally
checks request origin. Direct graph links start at `/p/<token>/graph`, which
establishes the same cookie before loading the real graph viewer.
The owner capability lives only in the mode-`0600`
`~/.wideband/fleetdeck/phone-access-token`; links and the PWA manifest retain
it across managed upgrades. Notes beta stores the client's notes at
`~/.wideband/fleetdeck/notes-beta.json`; it is distinct from the operator Mac's
legacy `~/.fleetdeck-notes.json`. Existing client notes and Fleetdeck config
are preserved.

Setup checks the exact Tailscale Serve mappings, protected board and map,
real graph nodes/edges, actual `wb-head` tmux session, terminal service, and
first project before offering the phone link. A loopback check is machine
proof; the owner must still open the new board on an iPhone and launch its Home
Screen icon. Owner-only setup texts are queued through the guarded iMessage
outbox only after the real phone reply and this phone-board confirmation.
The first-goal runner does not create a public Funnel link.

### 0.7.1 customer phone home (September 30, 2026 UTC)

The 0.7.1 source gives the customer portal a dedicated
clock-and-key `/phone` page while `/board` remains the full registry-driven
Fleetdeck board. The phone page reuses Fleetdeck's responsive `PHONE_PAGE`
layout with six customer keys: `BOARD`, `PROJECT`, `TERMINALS`, `GRAPH`,
`NETWORK`, and `NOTES β`. Terminal and graph keys depend on their exact
owner-gated HTTPS destinations in the live registry; missing or mismatched
services stay visible as `not ready`. The network key also requires the
owner-gated map API to return a live session from this Mac. The Wideband
video mark links back to the full board. This is an explicit customer adapter
change; a viewport, PWA install, or `fd_home` cookie did not enable the
simple screen in the published 0.7.0 artifact. The full board retains the
upstream four-square control, now linked directly to `/phone`, so an installed
phone app can return from the board without browser chrome.

The phone home, board, and `:8790` portal keep the same owner capability and
private Tailscale Serve boundary. A link to `/p/<token>/phone` establishes the
secure, HttpOnly session cookie; `/p/<token>/board` remains a separate full
board link. The Home Screen manifest starts at the capability phone route.
`/app/chat`, `/app/graph`, and `/app/netmap` frame only the existing private
terminal, graph, and map routes inside the phone app; they add no listener.
The writable terminal requires its validated tailnet host at startup and
sets `frame-ancestors` on its own page and proxied ttyd responses to its
own origin and the exact `:8790` Fleetdeck origin. Its POST and WebSocket
origin checks remain in place.
An existing 0.7.0 Home Screen icon may keep its saved `/p/<token>/board` URL.
That link remains the full board; the owner must open the new `/phone` link
and add it to the Home Screen to change the icon's destination.
The bundled Wideband mark is one tracked, size-bounded MP4 at
`assets/wb-logo-256.mp4`; the portal serves `/wb-logo-256.mp4` only after
owner-session authorization. Setup's phone-link check now requires both phone
home and full board over private HTTPS; the phone-page probe also checks the
authenticated MP4 response. The first handoff text names the phone home and
full board separately; all eight direct Fleetdeck links fit across the two
guarded texts even with long valid names. Local tests exercise the rendered
six keys, disabled service states, asset gate, manifest, managed bundle
upgrade/restore, phone-link readiness, and handoff
rejection paths. A local unsigned pre-version candidate passed package
integrity checks. Headless WebKit on a copied bundle verified 375×667 and
393×852 phone layouts, video decode, six keys, owner-cookie/private-route
behavior, and the four-square return from the full board in a simulated
standalone context. This does not prove a physical iPhone or installed PWA.
The exact 0.7.1 DMG passed source and embedded self-tests, signature and disk
image checks, the packaged installer browser E2E, and isolated WebKit phone
checks. A physical iPhone check and a VM install of this new UI were not run.

### 0.8.0 private client toolchain and local-first setup (release validation pending)

The packaged client no longer treats `/opt/homebrew` as a prerequisite. The
release builder fetches checksum-pinned upstream sources/releases and bundles
arm64 Python 3.11, Node/npm, tmux, ttyd, and `imsg`, including needed runtime
resources. It audits Mach-O deployment targets, dependency closure, signatures,
and command startup, then writes a SHA-256 manifest for every payload file.
The app's read-only native preflight checks macOS 14+, arm64, login/home
identity, app signature, complete bundled manifest, install-path ownership,
and free space before it changes the user's files. The launcher stages the
payload under `~/.wideband/toolchain/versions/<build-id>` with private
permissions, verifies the complete copy, and atomically switches the mode-0600
`active` build pointer. Previous versions remain available for rollback.
After preflight proves that the current login owns its install paths, the
launcher changes an existing owned `~/.wideband` parent to mode 0700 before
private-tool activation. Earlier Setup builds could leave that parent at 0755,
which the new toolchain correctly rejects. The launcher reports its failing
preparation stage so an operator can distinguish this from a native preflight
or Messages failure.
An invalid active private toolchain fails closed; it never silently selects
another profile's Homebrew. Only an explicitly marked 0.7.0/0.7.1 install may
use its own independently verified healthy Homebrew during migration. No
installer path changes ownership of a foreign `/opt/homebrew` prefix.

The client guide records the selected OS and head-agent names, provider, and
first job, then may prepare the local first project and real Fleetdeck portal,
terminal, Live Terminal Network, and Knowledge Graph before the agent Apple
Account exists. A `wideband.localhost` capability URL is for same-Mac preview
only; it is not an iPhone link. Private iPhone access requires the exact
Tailscale Serve mappings and owner-gated HTTPS probes. Messages activation
still needs a separate agent Apple Account, incoming owner text, exact binding,
the stable Wideband Agent permission principal, persistent head session,
guarded outbox, and a real phone send-and-reply observation. Account-free local
setup must never mark that path complete. The legacy full workstation
reconciler is not a client core prerequisite and must not be invoked from the
client guide because it writes operator-owned `~/.claude/CLAUDE.md`.
Packaged-client bootstrap also leaves `.zshrc` and operator Claude files alone.
Selecting Claude and opening its explicit sign-in action downloads the official
installer to a private file, requires a successful fetch and shell syntax check,
then runs authentication. Preview provider choices install no provider runtime.

Source self-tests, isolated private-payload startup, complete-manifest
tampering, and rollback tests are local development evidence. Record the exact
DMG build ID, source/embedded test counts, UTM state, browser results, and
physical phone results below only after running them against that artifact.

October 2 local 0.8.0 candidate: exact DMG build
`0.8.0-20261002150746`, SHA-256
`1fbba4cc830e26b41b70112a951b39d4faa54c744c445e2a9e18e1b3c617cf6a`.
Source and packaged self-tests each passed 97/97; the packaged setup browser
E2E passed in an isolated profile. The Fleetdeck bundle check passed against
reviewed source `092d6be`, including the phone, board, logo, owner access,
and `/app` routes. The iMessage runtime and disabled-LaunchAgent recovery
tests passed with a private toolchain fixture. The app passed recursive code
signature validation, the arm64 checks, mounted DMG inspection, and DMG
checksum verification. No VM install, reboot, physical phone message, or
physical iPhone board test was run for this build at the owner's direction;
these remain client pilot gates. Tag `v0.8.0` points to source commit `dd58163`.
GitHub published the unsigned DMG, ZIP, and checksums as a prerelease. Pages
workflow `37058200837` passed; `https://os.wideband.ai/version` returned this
build and SHA-256; a fresh public DMG download had the same SHA-256. The link
was sent through the existing owner-only Trace outbox, which marked it sent.

### Canonical live Fleetdeck stack and VM parity gate (September 28, 2026)

The operator Mac's actual running apps are separate services. The Tailscale
Serve routes and local listeners were checked together; paths below identify
the deployed code, not a similarly named checkout:

| Phone origin | Local listener | Live deployment and role |
|---|---|---|
| `<operator-tailnet-host>:8790` | `127.0.0.1:8790` | `~/srv/fleetdeck/portal_server.py` under `com.wideband.fleetdeck-portal`; full registry-driven board from `~/srv/fleetdeck/services.json`. |
| `<operator-tailnet-host>:8783` | `127.0.0.1:8783` | `~/.config/wb-tunnel/chat_server.py` under `com.wideband.tunnel-chat`; real tmux session list and writable terminal through its loopback ttyd child on 8784. This deployed copy differs from `~/srv/fleetdeck/chat_server.py`; the pilot reviews and bundles the deployed behavior with an owner access guard. |
| `<operator-tailnet-host>:18970/fleet-map` | `127.0.0.1:18790` | `~/srv/fleetdeck-authoring/portal_server.py` under `com.wideband.fleet-map-local`; read-only Live Terminal Network from local fleet snapshot, registry, runtime, and infrastructure readers. |
| `<operator-tailnet-host>:8792` | `*:4180` on the host | `~/glitch-cat/engine/serve.mjs` under `com.wideband.graph`; the real, cited corpus Knowledge Graph with lenses and a derived SQLite index. Its API reports index build time; it is not a continuously refreshed tmux map. Bind the client VM copy to loopback. |

`~/bin/wb-portal` and `~/.config/wb-portal` are older launcher/code paths,
not the live 8790 board. `~/srv/fleetdeck-map-ui` is an earlier fleet-map
preview; the running 18970 source is `~/srv/fleetdeck-authoring`. The previous
VM's matching colors and clickable eight-node diagram were insufficient; the
0.7.0 pilot runs reviewed copies of the four actual surfaces against
**that VM's own** sessions, services, project files, and graph pack. Verify
the backing data and phone interaction, not just an HTTP 200 or matching CSS.

## Client experience

The embedded interface has two surfaces:

- **Client view** is the default. It presents the next human action, ownership,
  plain-language instructions, exact open buttons, live readiness, and clear
  completion proof.
- **Operator view** exposes all six stages, verification results, deviations,
  metadata, and build-record controls.

The welcome dialog says whether this is a new or resumed build. Client view
starts with names, first job, and the local core, then guides the separate
agent Apple Account and first text. It keeps the next action visible and
distinguishes **Machine verified** from **You confirmed**.
Support access follows the working text path.

While a permission guide is open, the UI polls focused checks automatically.
The client should not need to run the full verifier or refresh the page after a
macOS toggle changes.

The completion surface reports three independent areas:

- machine foundation;
- client profile and account readiness; and
- handoff proof.

Setup tools provide **Check this Mac**, **Repair Wideband**, **Copy
diagnostics**, **Export support bundle**, and confirmed deactivation.

## Session identity and agent memory

A tmux session outlives the agent inside it. `tmux-resurrect`/`continuum`
restore panes and scrollback; `tm-standard` restores names and project roots.
Neither restores what the agent in that session was *for*, so a session that is
killed, restored, recreated, or rebuilt on another Mac comes back nameless in
every way that matters.

`bin/tm-memory` holds that missing layer, in two files per session under
`~/.config/agent-session-memory` (directory `0700`, files `0600`):

| Path | Lifetime | Holds |
|---|---|---|
| `identity/<session>.md` | stable | concern, responsibilities, exclusions, root, routing, chat binding, allowed tools, approval boundaries, owning project, bootstrap, recovery checks |
| `state/<session>.md` | mutable | current assignment, status, last verified evidence, blockers, next safe action, related files and tickets |

The split is the design. Identity that absorbs progress notes stops being read,
and an agent that skims its own card stops honouring its exclusions. One card
per durable concern, never one per task.

Not every session has a concern, so a card declares `role: assigned` or
`role: unassigned`. An unassigned session is all state and no identity: it can
be doing real work today without owning anything durable, and it recovers as a
fresh start that is explicitly told not to infer a mission from its scrollback,
directory, or name — the failure mode for a roleless agent is inventing a role,
not forgetting one. `check` holds an assigned card to a higher bar: a concern,
non-empty responsibilities and exclusions, and no `UNVERIFIED` anywhere. That
gate is the only thing promotion means, which is why there is no `assign`
command — flipping the field is trivial, deciding the two lists is the work.

`sessions.conf` is deliberately **not** extended. It stays name + root and
`tm-standard` keeps owning it; identity lives beside it, not inside it. The
cards are operator data: `install.sh` never seeds, reads, or backs them up.

### Recovery boundaries

- **A bare shell is not an agent.** Keystrokes in `zsh`/`bash`/`sh`/`fish`
  execute as shell commands. `tm-memory resume` refuses (exit 5) unless
  `--start` runs the card's `bootstrap:`, which is allowlisted to approved
  launchers and rejected outright if it contains shell metacharacters. A card is
  data an agent can edit, so it must not be able to become arbitrary execution.
- **Restored scrollback is not authorization.** A restored pane can display a
  complete agent prompt while running nothing. Classification reads
  `pane_current_command` and never `capture-pane`, and the injected brief tells
  the recovered agent the same thing about text it finds above it.
- **`=name` is a target-session, not a target-pane.** `send-keys` and
  `display-message` reject it, and `display-message` rejects it by printing
  nothing — which reads as a healthy empty answer. Everything that touches a
  pane resolves the active `%id` through `list-panes -s` first.
- An agent pane is recognised from `~/.imsg-routing.json` when it exists, so the
  router and recovery cannot disagree. The fallback additionally treats a bare
  version number as an agent: Claude Code reports its own version as the process
  name, so a fixed list silently stops recognising every Claude pane on upgrade.
- `tmux-boot` runs `tm-memory prime --quiet`, which publishes
  `WB_SESSION_IDENTITY` into each session's tmux environment. It starts no agent
  and types into no pane — login is unattended, and `selftest.sh` asserts that
  `tmux-boot` contains no `send-keys`. Recovery into a live pane stays
  human-initiated.

`tm-memory doctor` reconciles live tmux, `sessions.conf`, `~/.imsg-routing.json`
and the cards, and reports every gap without changing anything, including
unassigned sessions that have been alive over a week and probably have a de
facto concern. `tm-memory adopt` drafts cards for uncovered live sessions from
evidence only — always `unassigned`, the router's description kept as evidence
rather than as a decision, and a bootstrap only when a pane is already running
an approved agent — and never overwrites or deletes a card.

The skill that teaches an agent to use all of this is
`skills/agent-session-memory`, installed to `~/.claude/skills/` and, when
`~/.codex` exists, `~/.codex/skills/`. Validate the whole recovery path with
`skills/agent-session-memory/scripts/selfcheck.sh`, which runs against an
isolated `tmux -L` server and a temporary memory directory so it is safe on a
live machine.

## macOS permission design

macOS privacy grants attach to a concrete code identity and resolved binary
path. Wideband therefore uses one stable branded principal:

`~/Applications/Wideband Agent.app`

The agent requests or checks:

- Full Disk Access;
- Accessibility;
- Screen Recording; and
- Messages Automation through a harmless Apple Event.

Scheduled Wideband jobs also enter through this app so macOS shows a
recognizable Wideband background item instead of generic Python or shell
processes.

Remote Login and Screen Sharing remain Apple-owned services and are guided
separately. Use **Only these users**, select the intended individual
administrator, remove broad groups, leave remote-user Full Disk Access off,
and do not enable legacy VNC-password access unless explicitly approved.

## Verification model

The installer stores full `verify.sh --json` reports and a smaller focused
live report. `effective_verification()` merges the newest focused evidence into
the last full report so the UI can update a permission immediately without
discarding broader machine proof.

Stable check IDs connect `verify.sh`, the manifest, and
`TROUBLESHOOTING.md`. `selftest.sh` fails if either side drifts.

Expected incomplete items on a fresh client machine are not installer crashes.
Typical human gates include privacy approvals, Apple Account or Messages
sign-in, GitHub authentication, Tailscale authentication, power-management
approval, operator interview, and real-world phone/message proofs.

## Security and privacy invariants

- Bind the setup engine only to loopback.
- Authenticate every API call with a high-entropy per-process token.
- Keep the customer Fleetdeck board behind a private Tailscale Serve mapping
  and its separate owner-only capability link. Never put the capability in
  logs, support bundles, release artifacts, or documentation examples.
- Never log or print the token in normal startup output.
- Never add arbitrary command execution to the API.
- Keep state, interview answers, backups, records, and bundles private.
- Never collect passwords or two-factor codes.
- Never contact the public update feed before the client opts in, never include
  setup answers or a machine identifier in the request, and never turn an
  update notice into unattended code execution.
- Accept update metadata only from the pinned Wideband endpoint and accept
  artifacts/history only from the pinned public release repository. Treat the
  checksum as integrity metadata, not as a substitute for Developer ID signing
  and notarization.
- Never treat an executable `brew` file as proof that Homebrew is healthy.
- Never run recursive ownership changes automatically; prove the user and
  prefix first, print the scoped command, and require personal approval.
- Never put credentials, client profile answers, `.sop-vars` values, raw logs,
  or common contact identifiers in the support bundle.
- Never let a session identity card or handoff state hold a secret, token,
  credential, raw customer message, or an unverified assumption. Name the
  variable, never the value; `tm-memory check` rejects the common shapes, and
  the rule is broader than the regex.
- Preserve existing identity and client-owned work during install and repair.
- Deactivation may stop and move only exact Wideband-managed LaunchAgents,
  including the four iMessage jobs, first-project preview, configured
  Fleetdeck jobs, and Wideband Agent. It must not delete work or silently
  alter Apple sharing and privacy settings.
- Do not commit signing certificates, notary credentials, connection files,
  VM credentials, or personalized client profiles.

## Packaging and trust

Every client package requires explicit, reviewed Fleetdeck and Knowledge Graph
source checkouts. The builder refuses to substitute an unreviewed public clone.
Build a generic unsigned pilot:

```bash
./packaging/build-app.sh \
  --fleetdeck-source /path/to/reviewed/fleetdeck \
  --graph-source /path/to/reviewed/glitch-cat
```

Build a client-specific pilot using an identity-only profile kept outside the
repository:

```bash
./packaging/build-app.sh \
  --profile /secure/path/client-profile.json \
  --fleetdeck-source /path/to/reviewed/fleetdeck \
  --graph-source /path/to/reviewed/glitch-cat
```

Build with Developer ID signing:

```bash
./packaging/build-app.sh \
  --sign-identity "Developer ID Application: Wideband AI (…)" \
  --fleetdeck-source /path/to/reviewed/fleetdeck \
  --graph-source /path/to/reviewed/glitch-cat
```

Build, notarize, staple, and validate for production:

```bash
./packaging/build-app.sh \
  --sign-identity "Developer ID Application: Wideband AI (…)" \
  --notary-profile wideband-notary \
  --fleetdeck-source /path/to/reviewed/fleetdeck \
  --graph-source /path/to/reviewed/glitch-cat
```

Artifact names communicate trust state:

| Trust state | DMG |
|---|---|
| Ad-hoc pilot | `Wideband-Setup-unsigned.dmg` |
| Developer ID signed, not notarized | `Wideband-Setup-signed-unnotarized.dmg` |
| Signed, notarized, stapled | `Wideband-Setup.dmg` |

The unsigned one-file PyInstaller engine deliberately does not enable hardened
runtime library validation because an ad-hoc signature has no Team ID for the
expanded private `libpython`. The Wideband Agent does use hardened runtime. A
Developer ID release signs nested components and the DMG consistently.

The production signing path is implemented but has not been executed in this
repository because the Wideband Developer ID certificate and notary Keychain
profile are external credentials.

## Release and test procedure

For every source change:

```bash
./selftest.sh
git diff --check
```

For an app release:

1. Update `installer/manifest.json` and `CHANGELOG.md`.
2. Update this memory when architecture, responsibility, security, or release
   behavior changes.
3. Run the source self-test, including the pure Swift update-feed validation
   cases.
4. Run `./packaging/build-app.sh` with the intended profile and trust mode.
5. Verify the app recursively with `codesign --verify --deep --strict`.
6. Confirm setup app, engine, and agent are arm64.
7. Verify the DMG with `hdiutil verify` and preserve `dist/SHA256SUMS.txt`.
8. Generate `updates/version.json` from that exact app and DMG with
   `updates/release_feed.py`; never hand-type the build ID, size, or checksum.
9. Run the self-test embedded in the packaged payload.
10. Install the exact DMG in a clean Apple Silicon VM and compare its hash.
11. Run `tests/browser-e2e.mjs` with a fresh browser profile.
12. Exercise repair, disconnect recovery, port collision, support export, and
    resume from `~/Applications` after a reboot.
13. Push the versioned source and feed, tag the same version, create the public
    GitHub Release, and upload the exact DMG plus `SHA256SUMS.txt`.
14. Require the Pages workflow to succeed, fetch
    `https://os.wideband.ai/version` from a separate network, and compare its
    release URL and SHA-256 to the published asset before telling clients.
15. For production, additionally validate Gatekeeper, notarization, and the
    stapled ticket on a clean machine.

The browser E2E runner requires:

```bash
WB_E2E_TOKEN='<private runtime token>' \
WB_E2E_BASE='http://127.0.0.1:<forwarded-port>' \
WB_E2E_DEBUG='http://127.0.0.1:<chrome-debug-port>' \
node tests/browser-e2e.mjs
```

Never print or commit the token. The test verifies token handoff and hash
clearing, welcome/resume, ownership labels, live permission coaching, operator
view, and support tools. Its Chrome DevTools calls are bounded by timeouts so a
broken browser target fails instead of hanging indefinitely.

## Proven 0.5 E2E behavior

The 2026-09-23 Apple Silicon VM run proved:

- host and guest DMG SHA-256 matched;
- app, engine, and permission agent were arm64;
- the branded embedded window loaded and the real Accessibility alert named
  Wideband Agent;
- the browser journey passed with a fresh profile;
- repair completed and reported remaining human approvals separately;
- occupying port 8803 caused a safe fallback to another loopback port, which
  the UI and API reported accurately;
- a stale page displayed the reconnect banner and saved-progress message;
- reopening the installed app restored preferred port 8803 without Terminal;
- support ZIP and build record were mode `0600`, and the support archive did
  not contain the live token;
- unauthenticated API access returned HTTP 401;
- after a real reboot, no setup server ran until the client reopened the app;
- launching only `~/Applications/Wideband Setup.app` restored one native app
  and one embedded engine without opening Safari or Terminal; and
- the final native screen returned to the next unfinished approval with no
  stale-build reconnect error.

The reference E2E artifact was build `0.5.0-20260923054220`, SHA-256
`c8147b3597a5d9c9241fd14f4fff70fe714748269a23bf7ff92b3b3cceec9d97`.
Later documentation-only package builds should cite their own generated hash.

### 0.5.1 post-upgrade bootstrap validation

The 2026-09-23 recovery change was tested without altering the established host
configuration:

- an isolated bootstrap with a temporary `HOME` reached `ready`, produced the
  expected agent artifacts, and kept `.sop-vars` at mode `0600`;
- a read-only real-host diagnostic proved the user/home/console identity,
  arm64 architecture, selected developer Git, PATH, and a healthy Homebrew
  prefix;
- synthetic recognized-but-non-writable and symlinked prefixes were classified
  correctly, while both nonstandard repair targets were denied;
- a fresh authenticated localhost/browser run completed the client and operator
  journey and rendered distinct, actionable states for missing developer tools,
  installed-but-not-selected tools, incompatible tools, and Homebrew ownership
  review; and
- the source self-test passed 59 checks with zero failures.

These tests prove the branching and safety behavior. They do not substitute for
the read-only diagnostic from the affected client Mac, whose actual UID,
console user, prefix ownership, and developer-tools state must still be
observed before that client runs any repair.

### 0.6.0 update-channel validation

The update system is intentionally smaller than the installer and has no
privileged action:

- the pure Swift tests cover valid/newer/equal and numeric version comparison,
  the GitHub Pages trailing slash, wrong response hosts, wrong products,
  off-repository downloads, malformed checksums, missing unsigned-build
  warnings, and oversized responses;
- the native launcher is typechecked with the same `UpdateFeed.swift` compiled
  into the app;
- the feed generator derives the release, build ID, artifact size, trust state,
  and SHA-256 from the exact packaged files and refuses disagreement;
- the Pages builder revalidates the feed before it can upload either `/version`
  or the branded human-readable root; and
- the app makes automatic failures non-blocking, exposes a manual check, and
  never downloads or executes the advertised DMG.

Those tests do not prove public delivery. A release is not complete until the
GitHub Release asset exists, the Pages deployment succeeds, DNS and HTTPS for
`os.wideband.ai` resolve from outside the studio network, and the live feed's
checksum matches the downloaded public DMG.

For 0.6.0, source and embedded suites each passed 72 checks, the dedicated
Swift feed suite passed 10 adversarial/valid cases, and the app remained valid
under `codesign --verify --deep --strict` after its embedded self-test. The
three executables are arm64 and `hdiutil verify` accepted the exact DMG. GitHub
Pages built the feed successfully, and downloading the public release asset
back from GitHub produced SHA-256
`6342c3bde3a621f0282886203d544dc91740653f29caeccacda21c3284511b69`,
matching both `updates/version.json` and GitHub's asset digest. The first-run
consent sheet was launched with an isolated temporary home and visually proved
the branded question, exact URL, privacy explanation, and both choices without
touching the established setup state. The custom-domain DNS and HTTPS handoff
was later verified when `https://os.wideband.ai/version` returned 200 on
September 28, 2026.

### 0.6.0 onboarding pilot in UTM, September 28, 2026

The earlier local unsigned real-stack pilot build was
`0.6.0-20260928161906`, DMG SHA-256
`a999f594974a7209eb1b070f23270ee4630290e0c355f0923083a6d659f3874b`.
The source and embedded self-tests each pass 83/83; the DMG and recursive app
signature verify.
That exact artifact was installed in the `Wideband E2E Clean 2` macOS VM and
its phone-install action completed. At that time it was a private, unpublished
pilot, not the public 0.6.0 release: earlier on September 28, the live `os.wideband.ai/version` feed
still advertises build `0.6.0-20260924002330` and the latest GitHub Release is
`v0.6.0` from September 24. The owner later chose to publish the new version
as an explicitly unsigned pilot and authorized the reviewed Glitch Cat source
inside it. Developer ID signing and notarization remain required for a future
production release. The update client does not offer another build with the
same numeric version to 0.6.0 users.

The VM uses a dedicated agent Apple Account, an exact one-to-one owner binding,
and a signed-in Claude head session. During an isolated window, the host Trace
iMessage services were paused. A fresh owner phone text entered the VM inbox,
appeared as a matching user record in the dedicated Claude transcript, produced
one confirmed guarded outbox send, and was received on the owner's iPhone.
The host route was restored afterward. Because the two Macs share the agent
account, the VM watch, route, and outbox jobs are disabled between test windows;
the VM head-session keep job can remain active. Two earlier overlap-window
replies are held in `outbox/review` and must never be replayed automatically.

An overlap test found that booting out a LaunchAgent stopped the Wideband Agent
wrapper but left its Python listener and `imsg watch` child running. The new
Agent forwards SIGTERM to the dedicated child process group, and the watcher
cleans up `imsg` on exit. The installed updated Agent passed a live process-tree
termination check. The router now acknowledges inbound delivery only after a
matching, new Claude transcript user record; uncertain delivery remains for
review instead of silently advancing. Its focused tests pass 18/18.

The setup ledger records the owner's real reply confirmation and completed
first-website apply/check and Fleetdeck phone-install actions. The final pilot
runs five real stack jobs under LaunchAgents: full board `:8790`, interactive
tmux chat `:8783`, Live Terminal Network `:18970`, Glitch Cat engine on local
`:4180`, and its owner-gated front at public `:8792` / local `:4181`. Four
exact Tailscale Serve mappings expose the board, chat, map, and gated graph.
The board retained the client's first-project registry entry. Mobile Chrome
opened the full board and first-project site, the visible Notes beta link,
the map with observed `session:wb-head`, and the real graph with a full-width
canvas and lens menu. The graph had 360 indexed nodes and 59 edges; its
connected Surface lens drew 18 nodes and 29 edges. The live terminal listed
`wb-head` and its ttyd WebSocket upgraded to HTTP 101 and streamed frames.
Direct unauthenticated graph, board, map, and terminal requests were denied.
The map honestly marked its snapshot partial while the VM's duplicate
iMessage route and host-specific identity sources were absent.

Fleetdeck Notes beta passed HTTPS create/read and preserved its one test note
after reboot, separately from the operator notes store at mode `0600`. The
earlier starter note lacked a creation timestamp; the current page shows
"saved" for that unknown age instead of `NaNd ago`, without rewriting it.
The graph and Claude splash can truncate long labels at a 390-pixel phone
viewport; the graph canvas pans, and the terminal uses a real 48-column tmux
window. A phone live attachment leaves that size after detach if no other
client is attached. An automatic size-restoration hook is deferred because it
could resize a different client or linked window; a scoped WebSocket lease
needs its own integration test.

After a guest restart on the final DMG, all five jobs, `wb-head`, Notes,
Tailscale Serve, and the Setup phone-link readiness check recovered after GUI
login. The UTM host process remained up. Two earlier UTM host crashes were
recovered; both reports point to UTM 4.7.5's macOS screenshot/rendering path
(`NSView.cacheDisplay` → vImage), with no evidence of a guest service fault.
UTM Preferences → Display → Disable VM screenshot was enabled before the final
restart. That successful run is evidence for the workaround, not proof of the
exact graphics fault. The owner then confirmed on their iPhone that the full
private board, its apps, and the Home Screen icon worked. Setup recorded
`prove.phone-board` after `/api/phone-link` returned ready. During a short
isolated VM iMessage route window, the owner-authorized handoff queued exactly
two setup texts; the VM outbox reported `sent: 2`, `pending: 0`, `review: 0`
for that handoff. The VM's watch, route, and outbox jobs were unloaded again,
and the host Trace watch, router, chat binding, and outbox jobs were restored.
The owner separately confirmed that both setup texts arrived on their iPhone.
That physical receipt closes the guarded handoff check beyond the outbox's
send record.
During restoration, the host watch and chat-binding jobs were already loaded;
their duplicate bootstrap returned a launchd error. The host router was still
absent and was bootstrapped explicitly. Future route windows should verify
the router's actual state throughout instead of inferring it from the watch.

The latest Setup-only DMG upgrade kept the VM's approved Wideband Agent CDHash
`05ddf55e70a5c5e75bb9ebe7a43e73a600dffa72` unchanged. A fresh Agent
report returned Full Disk Access and Messages Automation as true. The Setup
engine moved to the new build, its private phone link stayed ready, and every
protected board, graph, watch, notes, and PWA manifest route returned HTTPS
200. Agent revision matching now preserves a signed, unchanged Agent across
Setup-only upgrades, including an in-place Setup app replacement; changed
Agent code or a damaged signature still replaces it.

### 0.7.0 public pilot delivery, September 28, 2026

The owner authorized public distribution of the reviewed Glitch Cat source
inside this installer and chose an explicitly unsigned pilot. Source and host
packaged self-tests passed 83/83; the exact UTM guest payload passed 81/81
because that guest has no Node CLI for two conditional JavaScript parse checks.
The browser E2E passed on the immediately preceding documentation-only build.
The final DMG build `0.7.0-20260928185839` passed recursive ad-hoc signature,
arm64, disk-image, bundle-manifest, and private-file checks. Its SHA-256 is
`659b97a1129ecbdaa1cbb66b47e07c008b2981da3cff64ab4774d317c258f759`.

That exact DMG matched the guest hash and upgraded the UTM pilot. Setup opened
at the exact build; the phone link was ready, four private Serve routes and
their real board/map/graph/terminal pages responded, the live terminal had a
session, five stack jobs stayed loaded, and Notes retained its data. The VM's
duplicate iMessage watch/router/outbox jobs stayed unloaded. GitHub Release
`v0.7.0` publishes the DMG and checksums as a prerelease. GitHub Pages workflow
`36469456141` succeeded, the branded feed returned the exact build and hash
from the VM network, and a new public DMG download matched it. The published
pilot is ad-hoc signed and requires macOS Open Anyway on first launch; it is
not Developer ID signed or notarized.
Cool published the community announcement in Skool's Releases category at
`https://www.skool.com/wideband-8959/wideband-setup-v070-is-live-fleetdeck-imessage-pilot`.
The rendered post retained the direct DMG link, checksum, pilot limitations,
and install guidance; its email broadcast was left off.

### 0.7.1 public phone UI pilot delivery, September 30, 2026 UTC

Source commit `8bd9d33` and tag `v0.7.1` contain the private clock-and-key
Fleetdeck phone home, board return, animated Wideband mark, in-app service
links, and the Setup phone link/handoff change. The iMessage router, guarded
outbox, provider path, permission logic, and Wideband Agent revision are
unchanged. Existing 0.7.0 Home Screen icons retain their saved board URL until
the owner adds the new phone-home link to the Home Screen.

The exact DMG build `0.7.1-20260930003207` passed source and embedded
self-tests 83/83 each; Fleetdeck bundle, phone-link, and handoff tests 14/14,
12/12, and 19/19; packaged installer browser E2E; and isolated WebKit phone
checks at 375×667 and 393×852, including MP4 playback and board return.
Recursive ad-hoc signature, arm64, disk-image, managed bundle, and checksum
checks passed. The new 0.7.1 phone UI was not installed in UTM or tested on a
physical iPhone; the 0.7.0 real-stack proof does not cover this changed UI.

GitHub Release `v0.7.1` publishes the unsigned DMG and checksums as a
prerelease. Its DMG SHA-256 is
`0aa8f27473b6a462334f6e2027576065b63bb36dfe16558ff8a6cfd5aa8e9754`.
GitHub Pages workflow `36651064714` succeeded. From the host network,
`https://os.wideband.ai/version` returned the exact build, size, URL, and hash;
a fresh public DMG download matched the feed. An independent second-network
fetch of the branded endpoint was not available for this release check.

## Lessons that must not regress

1. A native app must follow the exact packaged build ID, not the first live
   connection file it sees. Otherwise an upgrade can strand the view on the
   old engine token.
2. Port 8803 is a preference, not an invariant. Always trust the authenticated
   connection record.
3. A checkbox is not proof. Permission and installation state must come from
   observable checks against the real object.
4. Stable macOS permissions require a stable branded app identity, not
   Terminal or a package-manager binary.
5. Reboot recovery means a clear installed-app resume path. Wideband Setup is
   not an unnecessary login item and should not silently start remote control.
6. The support path must be useful without exporting secrets or raw logs.
7. Unsigned pilots are suitable for testing, but Gatekeeper friction remains a
   real client-experience cost until notarization.
8. The physical client gates are part of the product design, not missing
   automation. The guide should make ownership and next action unmistakable.
9. A major macOS upgrade can leave `/opt/homebrew` behind while invalidating
   Command Line Tools/Git or its ownership context. Bootstrap must diagnose the
   three layers independently, execute the selected Git as proof, and stop
   safely instead of calling that state “already installed.”
10. An update channel is an execution trust boundary. Ask before the first
    network request, pin both metadata and artifact authorities, keep the
    update human-approved, and do not describe an unsigned checksum as code
    signing.

## Documentation map

| File | Audience and authority |
|---|---|
| `README.md` | Product overview, quick start, package commands, and repository map. |
| `BUILD-MEMORY.md` | Durable architecture, decisions, invariants, release process, and E2E evidence. |
| `CHANGELOG.md` | User-visible and engineering release history. |
| `PREP.md` | Client preparation sent before setup day. |
| `packaging/SHARE-README.txt` | Instructions embedded in every DMG. |
| `SOP.md` | Full operator deployment procedure. |
| `TROUBLESHOOTING.md` | Installer recovery, check-ID fixes, and day-two operations. |
| `help.html` | Generated client-friendly rendering of troubleshooting content. |
| `interview/README.md` | Judgment-layer status and ownership. |
| `skills/agent-session-memory/` | Session identity, recovery boundaries, and fleet migration for every agent on the machine. |
| `updates/` | Public update-feed schema, deterministic generator, branded Pages root, and release runbook. |
| `AGENTS.md` | Short mandatory context for future software agents. |

When behavior changes, update the authoritative source above rather than
creating a second unlinked explanation.
