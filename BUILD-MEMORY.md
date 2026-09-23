# Wideband Setup build memory

This is the durable product and engineering context for `wb-setup`. It is meant
for the next Wideband operator or software agent who needs to continue the
build without reconstructing decisions from chat history.

## Current baseline

- Product: **Wideband Setup**, a guided installer for a custom Wideband AI
  operator workstation.
- Release: **0.5.1**.
- Functional release checkpoint: `018f829` (`ship embedded Wideband setup
  0.5`).
- Platform: Apple silicon, macOS 13 or newer.
- Preferred private setup port: `8803`, with automatic loopback fallback when
  that port is occupied.
- Distribution: one DMG; the current pilot is ad-hoc signed and intentionally
  labeled `unsigned` until Wideband supplies its Developer ID and notarization
  credentials.
- Last full Apple Silicon VM run: 2026-09-23. It covered installation, the real
  macOS permission prompt, repair, port fallback, disconnect recovery, support
  export, reboot, and resume from the installed app.

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
4. Enter the administrator password only into macOS or Homebrew's visible
   Terminal prompt on a genuinely bare Mac.
5. Approve privacy access only for the exact app named **Wideband Agent**.
6. Complete provider sign-ins and two-factor prompts personally.
7. Close and reopen `~/Applications/Wideband Setup.app` at any time to resume.

The client does not need a separate localhost URL or a second setup guide. The
DMG contains `READ ME FIRST.txt` and an **Open Privacy & Security** shortcut.

## Responsibility model

| Owner | Work |
|---|---|
| **Wideband installs** | Homebrew foundation, core CLIs, shell integration, Claude layer, tmux standard, LaunchAgents, fleetdeck, app payload, verification, repair, and private state. |
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
engine. Terminal appears behind it only because Homebrew requires one visible
administrator-password prompt. After the core foundation exists, later app
launches start the engine quietly in the background and require no browser or
Terminal knowledge.

Before touching Homebrew, `lib/bootstrap-homebrew.sh` independently proves the
invoking user, UID, home owner, console user, administrator membership,
architecture, PATH, selected Apple developer directory, developer Git, and the
ownership/writability of the exact `/opt/homebrew` prefix. This is required for
machines upgraded from an older macOS release: the prefix can survive while
Command Line Tools is removed or deselected, and a previous ownership context
can make `brew` executable but unusable.

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

## Client experience

The embedded interface has two surfaces:

- **Client view** is the default. It presents the next human action, ownership,
  plain-language instructions, exact open buttons, live readiness, and clear
  completion proof.
- **Operator view** exposes all six stages, verification results, deviations,
  metadata, and build-record controls.

The welcome dialog says whether this is a new or resumed build. Client view
frontloads access needed for support, keeps the next action visible, and
distinguishes **Machine verified** from **You confirmed**.

While a permission guide is open, the UI polls focused checks automatically.
The client should not need to run the full verifier or refresh the page after a
macOS toggle changes.

The completion surface reports three independent areas:

- machine foundation;
- client profile and account readiness; and
- handoff proof.

Setup tools provide **Check this Mac**, **Repair Wideband**, **Copy
diagnostics**, **Export support bundle**, and confirmed deactivation.

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
- Never log or print the token in normal startup output.
- Never add arbitrary command execution to the API.
- Keep state, interview answers, backups, records, and bundles private.
- Never collect passwords or two-factor codes.
- Never treat an executable `brew` file as proof that Homebrew is healthy.
- Never run recursive ownership changes automatically; prove the user and
  prefix first, print the scoped command, and require personal approval.
- Never put credentials, client profile answers, `.sop-vars` values, raw logs,
  or common contact identifiers in the support bundle.
- Preserve existing identity and client-owned work during install and repair.
- Deactivation may stop and move only the three managed LaunchAgents and
  Wideband Agent. It must not delete work or silently alter Apple sharing and
  privacy settings.
- Do not commit signing certificates, notary credentials, connection files,
  VM credentials, or personalized client profiles.

## Packaging and trust

Build a generic unsigned pilot:

```bash
./packaging/build-app.sh
```

Build a client-specific pilot using an identity-only profile kept outside the
repository:

```bash
./packaging/build-app.sh --profile /secure/path/client-profile.json
```

Build with Developer ID signing:

```bash
./packaging/build-app.sh \
  --sign-identity "Developer ID Application: Wideband AI (…)"
```

Build, notarize, staple, and validate for production:

```bash
./packaging/build-app.sh \
  --sign-identity "Developer ID Application: Wideband AI (…)" \
  --notary-profile wideband-notary
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
3. Run the source self-test.
4. Run `./packaging/build-app.sh` with the intended profile and trust mode.
5. Verify the app recursively with `codesign --verify --deep --strict`.
6. Confirm setup app, engine, and agent are arm64.
7. Verify the DMG with `hdiutil verify` and preserve `dist/SHA256SUMS.txt`.
8. Run the self-test embedded in the packaged payload.
9. Install the exact DMG in a clean Apple Silicon VM and compare its hash.
10. Run `tests/browser-e2e.mjs` with a fresh browser profile.
11. Exercise repair, disconnect recovery, port collision, support export, and
    resume from `~/Applications` after a reboot.
12. For production, additionally validate Gatekeeper, notarization, and the
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
  installed-but-not-selected tools, and Homebrew ownership review; and
- the source self-test passed 59 checks with zero failures.

These tests prove the branching and safety behavior. They do not substitute for
the read-only diagnostic from the affected client Mac, whose actual UID,
console user, prefix ownership, and developer-tools state must still be
observed before that client runs any repair.

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
   three layers independently and stop safely instead of calling that state
   “already installed.”

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
| `AGENTS.md` | Short mandatory context for future software agents. |

When behavior changes, update the authoritative source above rather than
creating a second unlinked explanation.
