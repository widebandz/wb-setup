import AppKit
import ApplicationServices
import Carbon
import CoreGraphics
import Darwin
import Foundation

private let fullDiskSettings = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles")!
private let permissionRegistrationGracePeriod: TimeInterval = 5

private func openSettings(_ url: URL) {
    NSWorkspace.shared.open(url)
}

private func accessibilityGranted() -> Bool {
    AXIsProcessTrusted()
}

private func requestAccessibility() -> Bool {
    let promptKey = kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String
    let options = [promptKey: true] as CFDictionary
    let granted = AXIsProcessTrustedWithOptions(options)
    if !granted {
        // Apple's consent alert is asynchronous. Keep this launched app alive
        // long enough for the alert and TCC list entry to attach to its bundle.
        // The setup guide provides a separate direct link to System Settings
        // for machines where the client previously dismissed this alert.
        RunLoop.current.run(until: Date().addingTimeInterval(permissionRegistrationGracePeriod))
    }
    return granted
}

private func screenCaptureGranted() -> Bool {
    CGPreflightScreenCaptureAccess()
}

private func requestScreenCapture() -> Bool {
    let granted = CGRequestScreenCaptureAccess()
    if !granted {
        // Do not open System Settings over the real consent alert. The guide
        // offers a separate settings button for previously dismissed prompts.
        RunLoop.current.run(until: Date().addingTimeInterval(permissionRegistrationGracePeriod))
    }
    return granted
}

private func fullDiskGranted() -> Bool {
    // TCC.db exists for every logged-in user and is protected by Full Disk
    // Access. Read a single byte only; no private content leaves this process.
    let protectedDatabase = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/com.apple.TCC/TCC.db")
    guard let handle = try? FileHandle(forReadingFrom: protectedDatabase) else {
        return false
    }
    defer { try? handle.close() }
    return (try? handle.read(upToCount: 1)) != nil
}

private func automationStatus() -> OSStatus {
    let bundleIdentifier = Data("com.apple.MobileSMS".utf8)
    var target = AEAddressDesc()
    let createStatus: OSErr = bundleIdentifier.withUnsafeBytes { bytes in
        AECreateDesc(
            DescType(typeApplicationBundleID),
            bytes.baseAddress,
            bundleIdentifier.count,
            &target
        )
    }
    guard createStatus == noErr else {
        return OSStatus(createStatus)
    }
    defer { AEDisposeDesc(&target) }
    return AEDeterminePermissionToAutomateTarget(
        &target,
        AEEventClass(typeWildCard),
        AEEventID(typeWildCard),
        false
    )
}

private func automationGranted() -> Bool {
    automationStatus() == noErr
}

private func requestMessagesAutomation() -> Bool {
    // Asking an application for its own name can be answered locally by
    // AppleScript and therefore does not reliably provoke a protected Apple
    // Event. Counting configured accounts is a real, harmless Messages event:
    // it reads no message or conversation content and sends nothing.
    let script = NSAppleScript(source: "tell application id \"com.apple.MobileSMS\" to count accounts")
    var error: NSDictionary?
    _ = script?.executeAndReturnError(&error)
    return error == nil
}

private func runBackgroundTask() -> Never {
    guard CommandLine.arguments.count >= 4 else {
        FileHandle.standardError.write(
            Data("run-background-task requires an interpreter and script\n".utf8)
        )
        exit(64)
    }

    let process = Process()
    process.executableURL = URL(fileURLWithPath: CommandLine.arguments[2])
    process.arguments = Array(CommandLine.arguments.dropFirst(3))
    process.environment = ProcessInfo.processInfo.environment
    do {
        try process.run()
        process.waitUntilExit()
        exit(process.terminationStatus)
    } catch {
        FileHandle.standardError.write(
            Data("Could not run Wideband background task: \(error)\n".utf8)
        )
        exit(74)
    }
}

private func revealAgent() {
    NSWorkspace.shared.activateFileViewerSelecting([Bundle.main.bundleURL])
}

private func writeJSON(_ value: [String: Any]) {
    guard let data = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]) else {
        return
    }
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
}

private func permissionSnapshot(nonce: String? = nil) -> [String: Any] {
    var value: [String: Any] = [
        "accessibility": accessibilityGranted(),
        "automation_messages": automationGranted(),
        "full_disk_access": fullDiskGranted(),
        "screen_capture": screenCaptureGranted(),
        "bundle_identifier": Bundle.main.bundleIdentifier ?? "ai.wideband.agent",
        "bundle_path": Bundle.main.bundlePath,
        "generated_at": ISO8601DateFormatter().string(from: Date()),
    ]
    if let nonce {
        value["nonce"] = String(nonce.prefix(128))
    }
    return value
}

private func writePrivateStatus(nonce: String) throws {
    let directory = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent(".wideband/setup", isDirectory: true)
    try FileManager.default.createDirectory(
        at: directory,
        withIntermediateDirectories: true,
        attributes: [.posixPermissions: 0o700]
    )
    let path = directory.appendingPathComponent("agent-status.json")
    let data = try JSONSerialization.data(withJSONObject: permissionSnapshot(nonce: nonce), options: [.prettyPrinted, .sortedKeys])
    try data.write(to: path, options: .atomic)
    chmod(path.path, mode_t(S_IRUSR | S_IWUSR))
}

private func finishCheck(_ granted: Bool, name: String) -> Never {
    writeJSON(["permission": name, "granted": granted])
    exit(granted ? EXIT_SUCCESS : EXIT_FAILURE)
}

@main
struct WidebandAgent {
    static func main() {
        let command = CommandLine.arguments.dropFirst().first ?? "status"
        if command == "run-background-task" {
            runBackgroundTask()
        }

        _ = NSApplication.shared
        NSApp.setActivationPolicy(.accessory)

        switch command {
        case "status":
            writeJSON(permissionSnapshot())
        case "report":
            guard CommandLine.arguments.count >= 3 else {
                FileHandle.standardError.write(Data("report requires a nonce\n".utf8))
                exit(64)
            }
            do {
                try writePrivateStatus(nonce: CommandLine.arguments[2])
            } catch {
                FileHandle.standardError.write(Data("Could not write permission status: \(error)\n".utf8))
                exit(74)
            }
        case "check-accessibility":
            finishCheck(accessibilityGranted(), name: "accessibility")
        case "request-accessibility":
            NSApp.activate(ignoringOtherApps: true)
            finishCheck(requestAccessibility(), name: "accessibility")
        case "check-screen-capture":
            finishCheck(screenCaptureGranted(), name: "screen_capture")
        case "request-screen-capture":
            NSApp.activate(ignoringOtherApps: true)
            finishCheck(requestScreenCapture(), name: "screen_capture")
        case "check-full-disk":
            finishCheck(fullDiskGranted(), name: "full_disk_access")
        case "request-full-disk":
            NSApp.activate(ignoringOtherApps: true)
            revealAgent()
            openSettings(fullDiskSettings)
            finishCheck(fullDiskGranted(), name: "full_disk_access")
        case "check-messages-automation":
            finishCheck(automationGranted(), name: "automation_messages")
        case "request-messages-automation":
            NSApp.activate(ignoringOtherApps: true)
            finishCheck(requestMessagesAutomation(), name: "automation_messages")
        case "reveal":
            revealAgent()
        case "version":
            print(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "unknown")
        default:
            FileHandle.standardError.write(Data("Unknown Wideband Agent command: \(command)\n".utf8))
            exit(64)
        }
    }
}
