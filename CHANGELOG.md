# Changelog

All notable product and release-engineering changes to Wideband Setup are
recorded here.

## 0.7.0 — unsigned pilot (2026-09-28)

### First text and phone handoff

- Added a guided first run for a separate agent Apple Account, OS and head-agent names, a first job, and an explicit provider choice. Claude Code is the verified first-text path; Codex, Gemini CLI, and Grok Build remain preview choices that cannot activate the router yet.
- Added a bound one-to-one iMessage listener, router, persistent head session, and guarded file outbox. The first website and customer Fleetdeck phone view follow a confirmed real reply.
- Installed the reviewed real Fleetdeck service board and its live tmux terminal, read-only Live Terminal Network, Glitch Cat Knowledge Graph, first-project link, and local Notes beta. The board and companion routes use private Tailscale Serve mappings and an owner-only capability; the saved Home Screen app retains access.
- Added owner-only setup texts with the board links, Termius and Tailscale App Store links, and tmux and Claude command hints. The messages queue once through the guarded outbox after phone confirmation.
- Managed Fleetdeck portal updates preserve local notes, config, and service registration, and restore the previous portal source if activation fails. The two existing Notes stores remain separate; sync is not part of this beta.
- Setup-only updates preserve an unchanged, permission-approved Wideband Agent. A saved first-project phone link is shown only while its current Tailscale Serve route is private.
- In the pre-release UTM pilot, source and embedded suites passed 83/83. A fresh iMessage produced a VM agent reply received on the owner's iPhone; five phone-stack jobs and the head session recovered after restart. The owner confirmed the full board, apps, Home Screen icon, and receipt of both guarded setup texts on the iPhone.
- The pilot artifact is `Wideband-Setup-unsigned.dmg` with ad-hoc signatures. macOS requires the documented Privacy & Security **Open Anyway** step; this release makes no Developer ID or notarization claim.

## 0.6.0 — 2026-09-23

### Client-controlled updates

- Added a one-time native consent prompt before Wideband Setup makes any
  Internet request. Clients can allow a lightweight check at app startup,
  decline it, change the preference from the app menu, or run **Check for
  Updates…** manually.
- Added the public schema-1 feed at `https://os.wideband.ai/version`. The app
  accepts only that HTTPS endpoint, a bounded JSON response for
  `wideband-setup`, and release/download links under the public
  `widebandz/wb-setup` GitHub repository.
- Update notices show the installed and available versions, release summary,
  artifact name and size, SHA-256, and the correct Gatekeeper state. Wideband
  opens the public release page but never silently downloads, installs, or
  executes an update.
- Added **View Version History…** and made GitHub Releases the public artifact
  history while this changelog remains the source history.
- Added deterministic feed generation, validation tests, and a GitHub Pages
  deployment workflow. Publishing a release now binds one version, build ID,
  trust state, exact DMG name, size, and checksum together.

### Session identity and agent memory

- Added `bin/tm-memory`: durable identity and handoff state for tmux/SSH agent
  sessions, split into a stable `identity/<session>.md` (concern,
  responsibilities, exclusions, root, routing, chat binding, allowed tools,
  approval boundaries, owning project, bootstrap, recovery checks) and a mutable
  `state/<session>.md` (assignment, status, verified evidence, blockers, next
  safe action). Stored under `~/.config/agent-session-memory`, directory `0700`
  and files `0600`.
- `sessions.conf` is unchanged and still owned by `tm-standard`: name and root
  only. Identity lives beside it, never inside it.
- Cards declare `role: assigned` or `role: unassigned`, because not every
  session owns a durable concern. An unassigned card may be sparse; an assigned
  one must state a concern, responsibilities and exclusions and carry no
  `UNVERIFIED`. An unassigned session recovers as a fresh start and is told not
  to infer a mission from its scrollback, directory, or name. `adopt` always
  drafts `unassigned`; promotion is a human edit.
- Recovery refuses to type into a bare shell. `tm-memory resume` classifies a
  pane from its live process, never from restored scrollback, and only the
  explicit `--start` flow may type — and only an allowlisted agent launcher with
  no shell metacharacters, so an identity card cannot become arbitrary
  execution.
- An agent pane is recognised from `~/.imsg-routing.json` when present, plus a
  bare-version-number fallback so a Claude Code upgrade cannot silently make
  every Claude pane unrecognisable.
- `tmux-boot` now runs `tm-memory prime --quiet`, publishing
  `WB_SESSION_IDENTITY` into each session's tmux environment. It starts no agent
  and types into no pane; `selftest.sh` asserts the absence of `send-keys`.
- Added `tm-memory doctor` (drift across live tmux, `sessions.conf`, the router
  config and the cards), `adopt` (evidence-only drafts marked `UNVERIFIED`,
  never overwriting or deleting), and `backup`/`rollback`.
- Added the `agent-session-memory` skill, installed for Claude and — when
  `~/.codex` exists — Codex, with a recovery selfcheck that runs against an
  isolated `tmux -L` server so it is safe on a live machine.

## 0.5.1 — 2026-09-23

### Post-upgrade bootstrap recovery

- Fixed a path where the presence of `/opt/homebrew/bin/brew` was incorrectly
  treated as proof of a healthy Homebrew installation.
- Added a read-only `--diagnose-homebrew` mode that reports the actual invoking
  user and UID, home owner, GUI console user, administrator membership,
  architecture, PATH, selected Apple developer directory, developer Git, and
  `/opt/homebrew` ownership and writability.
- Added a distinct Apple Command Line Tools state. The app now explains that
  this is not full Xcode, requests the Apple installer when the tools are
  absent, waits for real Git evidence, and detects the post-upgrade case where
  the tools exist but are not selected.
- Verifies that the selected developer Git actually executes and reports the
  Apple CLT receipt version. Files that survive an upgrade but cannot run now
  stop in a separate Software Update state; Wideband never deletes or forcibly
  reinstalls Apple's toolchain.
- Added a guarded ownership state for a recognized but non-writable Homebrew
  prefix. Wideband never executes `chown`; it prints a same-filesystem,
  no-symlink-follow repair only after the intended user and exact prefix have
  been proven, and requires the client to approve it personally.
- Refuses to generate ownership commands when extended ACLs or file flags make
  the permission state more complex than the scoped UID/directory-mode repair.
- Made a blocked preflight authoritative: stale `git`, `jq`, or `tmux`
  executables can no longer overwrite the ownership/developer-tools state with
  a false `ready`, and no Homebrew fallback runs after the guard stops it.
- Fetches the small versioned setup payload before Homebrew so the tested
  health guard is available on a genuinely bare or partially upgraded Mac.
- Added targeted native UI coaching for developer-tools approval and Homebrew
  ownership review.

## 0.5.0 — 2026-09-23

### Client experience

- Replaced the browser-first launcher with a branded native AppKit and WebKit
  setup application.
- Added a loading surface, welcome/resume dialog, client and operator views,
  responsibility labels, one-action guidance, and a clearer completion model.
- Installed a resumable copy in `~/Applications` when launched from the DMG.
- Kept Terminal visible only for the one Homebrew administrator-password
  boundary on a bare Mac; established machines now run the engine quietly.
- Added persistent disconnect coaching and automatic recovery when the native
  shell observes a new authenticated connection.

### Verification and support

- Added focused live checks for Full Disk Access, Accessibility, Screen
  Recording, Messages Automation, Remote Login, Screen Sharing, and sleep
  state.
- Merged newer focused evidence with the last full verification report so
  permission guides update automatically.
- Added live readiness cards, proof-source labels, setup record generation,
  idempotent repair, private diagnostics, redacted support export, and
  recoverable deactivation.
- Made build records and support bundles private and excluded credentials,
  two-factor codes, profile answers, `.sop-vars` values, raw logs, and the
  runtime token from the client support path.

### Packaging and security

- Bundled an arm64 one-file engine so the guide can open before Homebrew,
  Command Line Tools, or Python exists.
- Added exact build-ID connection selection, authenticated loopback port
  fallback, local-network entitlement, and quiet embedded-mode startup.
- Kept Wideband Agent as the stable branded permission principal and routed
  managed background jobs through it.
- Added Developer ID signing, notarization, stapling, validation, and explicit
  unsigned/signed artifact naming to the release builder.
- Added an in-DMG first-launch guide and direct Privacy & Security shortcut for
  unsigned pilots.

### Quality

- Expanded the repository suite to 54 passing checks.
- Added a timeout-bounded Chrome DevTools E2E runner for token lifecycle,
  welcome/resume, ownership, live guidance, operator view, and support tools.
- Completed an Apple Silicon VM run covering the real permission prompt,
  repair, port collision, disconnect recovery, private exports, HTTP 401,
  reboot, and installed-app resume without Safari or Terminal.

## 0.4.4 — 2026-09-22

- Introduced the packaged guided client installer and branded Wideband Agent.
- Added persisted setup state, an authenticated localhost API, a six-stage
  manifest, guided permission actions, verification rollups, operator
  interview, build record, and client-profile packaging.
- Folded the first live bare-Mac lessons into bootstrap and verification:
  Homebrew password visibility, object-based success checks, PATH diagnosis,
  and the Claude installer fallback.
