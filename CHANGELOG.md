# Changelog

All notable product and release-engineering changes to Wideband Setup are
recorded here.

## 0.8.4 — local candidate (2026-10-04 UTC)

- Create agents from Fleetdeck at 8783 through one shared provisioner: private roster, role and workspace, provider launch, resumable context, and current process evidence in the Live Terminal Network.
- Give agents private role instructions, Python and Node scripting, native provider search, and bundled Playwright with matching Chromium. Preserve existing project instructions, dependencies, browser profiles, and operator configuration.
- Launch the local head after provider sign-in, before Messages setup. Reuse that head for exact owner-chat binding and guarded iMessage replies; show the actual messaging route in the network.
- Keep local OS installation independent of an owner phone number or Apple Account, and reconcile the managed Fleetdeck bundle when a new installer build opens.
- Automated functional, browser, VM, reboot, and physical phone testing is deferred to the owner's manual testing for this candidate.

## 0.8.3 — unsigned pilot (2026-10-02 UTC)

- Treat tmux's exact missing-server response as an empty terminal list in the customer Live terminals service. Other tmux failures remain errors. A fresh Mac can now complete Fleetdeck activation before any agent tmux session exists.
- Restart the existing authenticated terminal LaunchAgent after the customer bundle upgrade so retry uses the new server code even when its plist is unchanged.
- Keep managed service logs mode 0600, suppress ttyd child output that can echo its internal basic-auth argument, rotate the generated internal ttyd credential on phone-stack retry, and clear its older chat log. A customized credential stops for review.
- Preserve a reviewed, content-free reason code when the owner-chat bind fails. The prior generic result discarded the Agent's actual failure, while raw Messages output still must not enter Setup state or support bundles.
- The owner-chat bind remains a separate Messages/imsg gate; this change does not alter Wideband Agent Full Disk Access or text routing. The older installed Agent can be intentionally preserved when its source revision is unchanged, even though the new package embeds a differently signed build.
- The exact package passed source and embedded self-tests (97/97 each), packaged browser E2E, recursive ad-hoc signature, arm64, and DMG checks. VM, reboot, physical iMessage, and iPhone board checks remain onsite pilot gates.

## 0.8.2 — unsigned pilot (2026-10-02 UTC)

- Treat the exact tmux missing-server response on a fresh login as zero live sessions. Other tmux errors remain unknown. The Live Terminal Network now has a truthful empty state, allowing Fleetdeck installation to continue to the terminal and graph checks.
- Show a **Retry Fleetdeck installation** button when its local install needs attention. The 0.8.1 guide hid the retry behind a successful install state.
- Restart the existing read-only map LaunchAgent during the retry so an unchanged plist cannot keep the 0.8.1 collector code running after the package upgrade.
- Full Disk Access reporting remains a separate onsite diagnostic; this release does not change the Wideband Agent permission binary or its macOS grant.
- The exact package passed source and embedded self-tests (97/97 each), packaged browser E2E, recursive ad-hoc signature, arm64, and DMG checks. VM, reboot, physical iMessage, and iPhone board checks remain onsite pilot gates.

## 0.8.1 — unsigned pilot (2026-10-02 UTC)

- Keep the bundled Python standard library immutable after staging. Ordinary imports in 0.8.0 created bytecode files outside the signed tool manifest, so subsequent checks blocked Python, tmux, imsg, and Claude sign-in. The new build stages a fresh private version and verifies that repeated imports leave the manifest intact.
- Replace stale client-guide copy that said Homebrew was installing; the packaged client uses its own private tools.
- Full Disk Access on the onsite Mac remains a separate macOS permission check. A failed Setup indicator alone does not prove a denied grant.
- Source and packaged suites passed 97/97; the exact packaged payload survived Python imports and a second activation with all 2,642 manifest files unchanged. The packaged browser E2E, ad-hoc signature, and DMG checksum checks passed. VM, reboot, iMessage, and physical phone board checks remain onsite pilot gates.

## 0.8.0 — unsigned pilot (2026-10-02 UTC)

### Private tools and account-free local setup

- Bundled checksum-pinned Apple Silicon Python, Node/npm, tmux, ttyd, and `imsg` so a client installation does not depend on, use, or change another macOS profile's Homebrew. The installer checks the downloaded app and complete tool payload before copying files, then activates a private version with the previous version retained for rollback.
- Added read-only core preflight and explicit blocked states. A foreign or damaged Homebrew prefix is inventory, not an ownership-repair request for a new client install. The local first job and real Fleetdeck board, terminal, Live Terminal Network, and Knowledge Graph can be prepared before Apple Account, provider, and Messages sign-in.
- Kept iMessage activation behind a separate agent Apple Account, exact owner-chat binding, permission checks, and a physical send-and-reply proof. The guide no longer presents an unverified text route as complete.
- Deferred Claude Code installation to the selected Claude sign-in action. Client bootstrap leaves `.zshrc` and operator Claude files untouched; the sign-in action downloads the official installer to a private file and checks the fetch and script before execution. Preview providers remain pending.
- Updated the managed Fleetdeck adapter from the current reviewed source. Local-only preview uses a guarded `wideband.localhost` capability; private iPhone access still needs Tailscale Serve and owner confirmation.
- Added isolated toolchain tamper/rollback tests, preflight tests, local phone-stack checks, and customer map/graph tests. The exact DMG passed source and packaged self-tests (97/97 each), the packaged Setup browser journey, signature and checksum checks. This build has no VM, reboot, physical iMessage, or iPhone board result yet; each pilot install must complete those proofs onsite.
- Tightened an owned `~/.wideband` directory before activating private tools, including on installs created by older Setup versions. Launcher failures now identify the preparation stage instead of implying that no files changed.

## 0.7.1 — unsigned pilot (2026-09-30 UTC)

### Customer phone home

- Added a private clock-and-key Fleetdeck phone home at `/phone` while keeping the full service board at `/board`. Its six keys are Board, Project, Terminals, Graph, Network, and Notes beta; unavailable companion services remain visible as not ready. The Wideband video mark opens the full board, and the board's four-square control returns to the phone home.
- Added in-app links to the existing terminal, graph, and network views.
- Changed the private phone link, Home Screen manifest, and first setup text to open `/phone`. Setup checks the phone home, full board, and logo over private HTTPS before showing the link.
- Added bundle and browser tests for the six-key layout, video asset, in-app navigation, and preserved board access. The packaged 0.7.1 UI passed isolated WebKit checks at 375×667 and 393×852, including video playback and board return. A physical iPhone test of this new UI has not been recorded.

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
