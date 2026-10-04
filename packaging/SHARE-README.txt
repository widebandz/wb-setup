WIDEBAND SETUP

This disk image is the complete client handoff. You do not need a separate
localhost link or technical setup guide.

1. Open the disk image.
2. Either drag “Wideband Setup” into Applications or open it directly. When it
   is opened directly, it leaves a resumable copy in your user Applications
   folder automatically.
3. Open Wideband Setup. A signed and notarized production
   build opens normally. If this copy is labeled “unsigned” and macOS shows
   “Wideband Setup Not Opened,” select Done; do not select Move to Trash.
4. For an unsigned pilot only, return to this disk image and open “Open Privacy
   & Security.” In the branded page, select Open Privacy & Security; if Safari
   asks, select Allow. Scroll to Security, select Open Anyway beside Wideband
   Setup, confirm Open Anyway, and enter the Mac administrator password.
   (On older macOS versions, Control-click → Open may offer the exception
   directly; if it does, use that instead.)
5. Select Begin guided setup in the branded Wideband Setup window.
   On first launch, choose whether the app may check
   https://os.wideband.ai/version when it starts. The check sends no setup
   answers or machine identifiers and can be changed later from the Wideband
   Setup menu.
6. Use the Wideband guide to name your OS and agent and choose their first job.
   You can prepare local tools and Fleetdeck before adding your personal phone
   number in the later iMessage connection step.
7. The guide stays inside the Wideband app and shows live machine progress.
   The client release includes its own verified Python, Node, tmux, terminal,
   and Messages tools. It will not take over a Homebrew installation owned by
   another Mac profile. Terminal may open behind the guide during first-run
   bootstrap or recovery; leave it open until the guide says it is finished.
8. Follow the Wideband guide; do not type a localhost address yourself. Each
   step opens the right provider, app, or System Settings page and tells you
   what to select. Permission checks refresh automatically while each guide is
   open.
   The local first job and Fleetdeck board can be prepared before you create
   the separate agent Apple Account. Texting and iPhone access remain later
   checks requiring your approval and a real phone test.
9. When macOS asks about Accessibility, Screen Recording, Full Disk Access, or
   Messages Automation, approve the exact app named “Wideband Agent.” The guide
   requests each permission and verifies it before marking the step complete.
10. For Remote Login, turn off “Allow full disk access for remote users” unless
   Wideband explicitly requests it. Choose “Only these users,” remove the broad
   Administrators group, and add only the intended individual administrator.
11. For remote visual support, the guide opens Apple Screen Sharing separately.
   Enable it only for the intended administrator; leave legacy VNC-password
   access off unless Wideband has explicitly asked for it.
12. Before approving Messages Automation, open Messages and finish sign-in or
   dismiss its first-run panels. Return to the guide, request the macOS prompt,
   and approve the exact app named Wideband Agent. The consent check sends no
   message and reads no message or conversation content.
13. If Apple Account sign-in failed during macOS Setup Assistant, finish setup
   first, then sign in from System Settings at the desktop. Verify Messages
   separately. This does not mean the Wideband installer failed.
14. Use the responsibility strip and Live Readiness cards to distinguish what
   Wideband installs, what you approve, and what is customized together. The
   readiness cards separate the installed machine layer,
   macOS approvals, account setup, and real-world handoff proofs. “Machine
   verified” is a live check; “You confirmed” is a client-owned account or
   outcome that the installer cannot inspect. Your last completed action is
   saved automatically; reopen Wideband Setup to resume.
    When the private Fleetdeck board works from your phone, its final guide
    confirmation queues two setup texts to your verified personal chat. They
    contain your board links, quick commands, and iPhone app links.
15. Setup tools can run a fresh check, repair the managed runtime, or export a
   redacted support ZIP. The ZIP excludes credentials, two-factor codes,
   profile answers, .sop-vars values, and raw logs. Recoverable deactivation is
   also available behind an explicit typed confirmation.
16. If the app is closed or the Mac restarts, open “Wideband Setup” from your
    user Applications folder. Do not reuse an old localhost tab; the app safely
    supplies the current private connection and resumes the saved step.
17. If another macOS profile owns Homebrew at /opt/homebrew, Wideband leaves it
    untouched and uses its private client tools. If preflight blocks, export a
    support ZIP and contact Wideband. Do not run a broad chown command.
18. When an update is available, Wideband Setup shows the version, checksum,
    and Gatekeeper state, then opens the public Wideband GitHub Release for
    review. It never installs or runs an update without you. Use Wideband Setup
    → View Version History for every published version.

Requirements
• Apple silicon Mac
• macOS 14 or newer for the iMessage client setup
• Administrator access
• Internet access and the account owner’s phone for sign-ins

The installer never sends passwords or two-factor codes to Wideband. Account
authentication happens in the provider’s browser or macOS interface. Installer
state stays private on the Mac under ~/.wideband/setup and can be resumed by
reopening the app.

If the disk image filename contains “unsigned,” the one-time Privacy & Security
→ Open Anyway exception is expected. Production disk images are Developer ID
signed, notarized, and stapled so macOS can verify Wideband as the publisher.

Wideband release-builder note (not a client step): a self-contained phone
portal build needs `./packaging/build-app.sh --fleetdeck-source /path/to/reviewed/fleetdeck --graph-source /path/to/reviewed/glitch-cat`
from a reviewed checkout. The packaged customer portal
excludes local Fleetdeck config, notes, backups, and operator source. Without
that flag, phone setup keeps a public-clone fallback, but the current public
Fleetdeck release does not yet have the customer-mode guard and that step will
stop safely.
