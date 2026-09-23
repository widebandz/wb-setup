# Changelog

All notable product and release-engineering changes to Wideband Setup are
recorded here.

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
