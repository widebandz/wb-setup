WIDEBAND SETUP — UNSIGNED PILOT BUILD

1. Open the disk image.
2. Drag “Wideband Setup” into Applications.
3. Open Wideband Setup from Applications once. Because this pilot is not
   notarized, current macOS versions will show “Wideband Setup Not Opened.”
   Select Done; do not select Move to Trash.
4. Return to this disk image and open “Open Privacy & Security.” In the branded
   page, select Open Privacy & Security; if Safari asks, select Allow. Scroll to
   Security, select Open Anyway beside Wideband Setup, confirm Open Anyway, and
   enter the Mac administrator password. The app will then launch.
   (On older macOS versions, Control-click → Open may offer the exception
   directly; if it does, use that instead.)
5. Select Begin setup in the Wideband welcome popup.
6. In a generic build, answer the six plain-language setup popups. A build
   prepared specifically for your company skips these questions.
7. The browser guide opens immediately and shows live machine progress. Enter
   the Mac administrator password in Terminal when the guide requests it. The
   cursor does not move while you type; that is normal.
8. Leave Terminal open behind the browser and follow the Wideband guide. The
   app opens the correct private local page automatically; do not type a
   localhost address yourself. Each step opens the right app or System Settings
   page and tells you what to select.
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
14. Use the Live Readiness cards to distinguish the installed machine layer,
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

This pilot is unsigned. The one-time Privacy & Security → Open Anyway exception
is expected on current macOS versions.
Future production builds should use Wideband’s Developer ID so macOS can verify
the publisher and preserve a stable permission identity across updates.
