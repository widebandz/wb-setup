import AppKit
import Foundation

@main
struct WidebandSetupLauncher {
    private static func showFailure(_ detail: String) {
        let application = NSApplication.shared
        application.setActivationPolicy(.accessory)
        application.activate(ignoringOtherApps: true)

        let alert = NSAlert()
        alert.alertStyle = .critical
        alert.messageText = "Wideband Setup"
        alert.informativeText = detail
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }

    static func main() {
        guard let resources = Bundle.main.resourceURL else {
            showFailure("The installer could not locate its packaged resources. Please download a fresh copy or contact Wideband.")
            return
        }

        let script = resources.appendingPathComponent("app-launcher", isDirectory: false)
        guard FileManager.default.isExecutableFile(atPath: script.path) else {
            showFailure("The installer launcher is missing or damaged. Please download a fresh copy or contact Wideband.")
            return
        }

        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/bash")
        process.arguments = [script.path]

        do {
            try process.run()
            process.waitUntilExit()
            if process.terminationStatus != 0 {
                exit(process.terminationStatus)
            }
        } catch {
            showFailure("The installer could not start. Please download a fresh copy or contact Wideband.\n\n\(error.localizedDescription)")
        }
    }
}
