WIDEBAND SETUP

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
6. In a generic build, answer the six plain-language setup popups. A build
   prepared specifically for your company skips these questions.
7. The guide stays inside the Wideband app and shows live machine progress.
   On a genuinely new Mac, Terminal opens behind it for Homebrew's one visible
   administrator-password prompt. The cursor does not move while you type;
   that is normal. Leave Terminal open until the guide says it is no longer
   hosting the first installation.
8. Follow the Wideband guide; do not type a localhost address yourself. Each
   step opens the right provider, app, or System Settings page and tells you
   what to select. Permission checks refresh automatically while each guide is
   open.
   The access and permission steps appear first so Wideband can help with the
   rest of setup if needed.
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
15. Setup tools can run a fresh check, repair the managed runtime, or export a
   redacted support ZIP. The ZIP excludes credentials, two-factor codes,
   profile answers, .sop-vars values, and raw logs. Recoverable deactivation is
   also available behind an explicit typed confirmation.

Requirements
• Apple silicon Mac
• macOS 13 or newer
• Administrator access
• Internet access and the account owner’s phone for sign-ins

The installer never sends passwords or two-factor codes to Wideband. Account
authentication happens in the provider’s browser or macOS interface. Installer
state stays private on the Mac under ~/.wideband/setup and can be resumed by
reopening the app.

If the disk image filename contains “unsigned,” the one-time Privacy & Security
→ Open Anyway exception is expected. Production disk images are Developer ID
signed, notarized, and stapled so macOS can verify Wideband as the publisher.
