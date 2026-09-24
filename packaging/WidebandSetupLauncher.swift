import AppKit
import Foundation
import WebKit

private struct SetupConnection: Decodable, Equatable {
    let pid: Int32
    let port: Int
    let token: String
    let release: String?
    let build_id: String?
}

private final class SetupAppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate {
    private var window: NSWindow!
    private var webView: WKWebView!
    private var loadingView: NSView!
    private var statusLabel: NSTextField!
    private var launcher: Process?
    private var pollTimer: Timer?
    private var healthCheckInFlight = false
    private var dashboardURL: URL?
    private var activeConnection: SetupConnection?
    private var startupBegan = Date()
    private var updateCheckInFlight = false
    private var updateSession: URLSession?
    private var checkForUpdatesMenuItem: NSMenuItem?
    private var automaticUpdatesMenuItem: NSMenuItem?

    private let updatePreferenceKey = "WBCheckForUpdatesAtStartup"

    private var connectionURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".wideband/setup/connection.json", isDirectory: false)
    }

    private var expectedBuildID: String? {
        guard
            let url = Bundle.main.resourceURL?.appendingPathComponent("build-id.txt"),
            let value = try? String(contentsOf: url, encoding: .utf8)
                .split(whereSeparator: \.isNewline).first
        else { return nil }
        return String(value)
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        installMenu()
        buildWindow()
        NSApp.activate(ignoringOtherApps: true)
        startPackagedLauncher()
        startConnectionPolling()
        DispatchQueue.main.async { [weak self] in
            self?.offerUpdatePreferenceOrCheck()
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        return true
    }

    private func installMenu() {
        let main = NSMenu()
        let applicationItem = NSMenuItem()
        main.addItem(applicationItem)
        let applicationMenu = NSMenu()
        applicationMenu.addItem(withTitle: "About Wideband Setup", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        applicationMenu.addItem(.separator())
        let browser = applicationMenu.addItem(withTitle: "Open Guide in Browser", action: #selector(openInBrowser), keyEquivalent: "o")
        browser.keyEquivalentModifierMask = [.command, .shift]
        applicationMenu.addItem(withTitle: "Reload Guide", action: #selector(reloadGuide), keyEquivalent: "r")
        applicationMenu.addItem(.separator())
        checkForUpdatesMenuItem = applicationMenu.addItem(withTitle: "Check for Updates…", action: #selector(checkForUpdatesManually), keyEquivalent: "")
        checkForUpdatesMenuItem?.target = self
        automaticUpdatesMenuItem = applicationMenu.addItem(withTitle: "Check for Updates When Starting", action: #selector(toggleAutomaticUpdateChecks), keyEquivalent: "")
        automaticUpdatesMenuItem?.target = self
        let history = applicationMenu.addItem(withTitle: "View Version History…", action: #selector(openVersionHistory), keyEquivalent: "")
        history.target = self
        refreshUpdateMenuState()
        applicationMenu.addItem(.separator())
        applicationMenu.addItem(withTitle: "Quit Wideband Setup", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        applicationItem.submenu = applicationMenu
        NSApp.mainMenu = main
    }

    private func buildWindow() {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        webView = WKWebView(frame: .zero, configuration: configuration)
        webView.translatesAutoresizingMaskIntoConstraints = false
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.isHidden = true

        loadingView = NSView()
        loadingView.translatesAutoresizingMaskIntoConstraints = false
        loadingView.wantsLayer = true
        loadingView.layer?.backgroundColor = NSColor(calibratedRed: 0.027, green: 0.027, blue: 0.043, alpha: 1).cgColor

        let logo = NSImageView()
        logo.translatesAutoresizingMaskIntoConstraints = false
        logo.imageScaling = .scaleProportionallyUpOrDown
        if let iconURL = Bundle.main.url(forResource: "AppIcon", withExtension: "icns") {
            logo.image = NSImage(contentsOf: iconURL)
        }

        let wordmark = NSTextField(labelWithString: "WIDEBAND.AI")
        wordmark.translatesAutoresizingMaskIntoConstraints = false
        wordmark.font = NSFont.monospacedSystemFont(ofSize: 12, weight: .bold)
        wordmark.textColor = NSColor(calibratedRed: 0, green: 1, blue: 0.82, alpha: 1)
        wordmark.alignment = .center

        let title = NSTextField(labelWithString: "Preparing your private setup guide")
        title.translatesAutoresizingMaskIntoConstraints = false
        title.font = NSFont.systemFont(ofSize: 25, weight: .medium)
        title.textColor = .white
        title.alignment = .center

        statusLabel = NSTextField(wrappingLabelWithString: "Installing the verified Wideband components on this Mac…")
        statusLabel.translatesAutoresizingMaskIntoConstraints = false
        statusLabel.font = NSFont.systemFont(ofSize: 13, weight: .regular)
        statusLabel.textColor = NSColor(calibratedWhite: 0.62, alpha: 1)
        statusLabel.alignment = .center
        statusLabel.maximumNumberOfLines = 3

        let progress = NSProgressIndicator()
        progress.translatesAutoresizingMaskIntoConstraints = false
        progress.style = .spinning
        progress.controlSize = .small
        progress.startAnimation(nil)

        loadingView.addSubview(logo)
        loadingView.addSubview(wordmark)
        loadingView.addSubview(title)
        loadingView.addSubview(statusLabel)
        loadingView.addSubview(progress)

        let root = NSView()
        root.addSubview(webView)
        root.addSubview(loadingView)
        NSLayoutConstraint.activate([
            webView.leadingAnchor.constraint(equalTo: root.leadingAnchor),
            webView.trailingAnchor.constraint(equalTo: root.trailingAnchor),
            webView.topAnchor.constraint(equalTo: root.topAnchor),
            webView.bottomAnchor.constraint(equalTo: root.bottomAnchor),
            loadingView.leadingAnchor.constraint(equalTo: root.leadingAnchor),
            loadingView.trailingAnchor.constraint(equalTo: root.trailingAnchor),
            loadingView.topAnchor.constraint(equalTo: root.topAnchor),
            loadingView.bottomAnchor.constraint(equalTo: root.bottomAnchor),
            logo.widthAnchor.constraint(equalToConstant: 108),
            logo.heightAnchor.constraint(equalToConstant: 108),
            logo.centerXAnchor.constraint(equalTo: loadingView.centerXAnchor),
            logo.centerYAnchor.constraint(equalTo: loadingView.centerYAnchor, constant: -95),
            wordmark.topAnchor.constraint(equalTo: logo.bottomAnchor, constant: 15),
            wordmark.centerXAnchor.constraint(equalTo: loadingView.centerXAnchor),
            title.topAnchor.constraint(equalTo: wordmark.bottomAnchor, constant: 25),
            title.centerXAnchor.constraint(equalTo: loadingView.centerXAnchor),
            statusLabel.topAnchor.constraint(equalTo: title.bottomAnchor, constant: 13),
            statusLabel.centerXAnchor.constraint(equalTo: loadingView.centerXAnchor),
            statusLabel.widthAnchor.constraint(lessThanOrEqualToConstant: 560),
            progress.topAnchor.constraint(equalTo: statusLabel.bottomAnchor, constant: 22),
            progress.centerXAnchor.constraint(equalTo: loadingView.centerXAnchor),
        ])

        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1180, height: 780),
            styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        window.title = "Wideband Setup"
        window.titlebarAppearsTransparent = true
        window.minSize = NSSize(width: 820, height: 600)
        window.contentView = root
        window.center()
        window.makeKeyAndOrderFront(nil)
    }

    private func startPackagedLauncher() {
        guard let resources = Bundle.main.resourceURL else {
            showFailure("The installer could not locate its packaged resources. Download a fresh copy or contact Wideband.")
            return
        }
        let script = resources.appendingPathComponent("app-launcher", isDirectory: false)
        guard FileManager.default.isExecutableFile(atPath: script.path) else {
            showFailure("The installer launcher is missing or damaged. Download a fresh copy or contact Wideband.")
            return
        }

        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/bash")
        process.arguments = [script.path]
        var environment = ProcessInfo.processInfo.environment
        environment["WB_SETUP_NATIVE_PID"] = String(ProcessInfo.processInfo.processIdentifier)
        process.environment = environment
        process.terminationHandler = { [weak self] finished in
            DispatchQueue.main.async {
                guard let self, finished.terminationStatus != 0, self.dashboardURL == nil else { return }
                self.showFailure("Wideband could not prepare the local setup engine. Your existing configuration was not changed. Reopen the app to retry or contact Wideband.")
            }
        }
        do {
            try process.run()
            launcher = process
        } catch {
            showFailure("The installer could not start. Download a fresh copy or contact Wideband.\n\n\(error.localizedDescription)")
        }
    }

    private func startConnectionPolling() {
        pollTimer?.invalidate()
        pollTimer = Timer.scheduledTimer(withTimeInterval: 0.45, repeats: true) { [weak self] _ in
            self?.pollConnection()
        }
        pollConnection()
    }

    private func pollConnection() {
        guard !healthCheckInFlight else { return }
        if Date().timeIntervalSince(startupBegan) > 12 {
            statusLabel.stringValue = "Setup is still preparing. If macOS asks for your administrator password, enter it in Terminal; the password remains private."
        }
        guard
            let data = try? Data(contentsOf: connectionURL),
            let connection = try? JSONDecoder().decode(SetupConnection.self, from: data),
            connection.port > 0,
            connection.port <= 65_535,
            !connection.token.isEmpty,
            let healthURL = URL(string: "http://127.0.0.1:\(connection.port)/api/health")
        else { return }
        if let expectedBuildID, connection.build_id != expectedBuildID { return }
        if connection == activeConnection { return }

        healthCheckInFlight = true
        var request = URLRequest(url: healthURL)
        request.timeoutInterval = 1.2
        request.setValue(connection.token, forHTTPHeaderField: "X-Wideband-Token")
        URLSession.shared.dataTask(with: request) { [weak self] data, response, _ in
            DispatchQueue.main.async {
                guard let self else { return }
                self.healthCheckInFlight = false
                guard
                    let response = response as? HTTPURLResponse,
                    response.statusCode == 200,
                    let data,
                    let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                    payload["status"] as? String == "ok"
                else { return }
                self.openDashboard(connection)
            }
        }.resume()
    }

    private func openDashboard(_ connection: SetupConnection) {
        guard connection != activeConnection else { return }
        var components = URLComponents()
        components.scheme = "http"
        components.host = "127.0.0.1"
        components.port = connection.port
        components.path = "/"
        components.fragment = connection.token
        guard let url = components.url else { return }
        activeConnection = connection
        dashboardURL = url
        statusLabel.stringValue = "Opening your guided setup…"
        webView.load(URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 10))
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        loadingView.isHidden = true
        webView.isHidden = false
        window.makeFirstResponder(webView)
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        loadingView.isHidden = false
        webView.isHidden = true
        statusLabel.stringValue = "The private guide disconnected. Wideband is reconnecting automatically…"
        activeConnection = nil
        dashboardURL = nil
        startupBegan = Date()
        startConnectionPolling()
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        self.webView(webView, didFail: navigation, withError: error)
    }

    func webView(
        _ webView: WKWebView,
        decidePolicyFor navigationAction: WKNavigationAction,
        decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
    ) {
        guard let url = navigationAction.request.url else {
            decisionHandler(.cancel)
            return
        }
        if url.host == "127.0.0.1" || url.scheme == "about" {
            decisionHandler(.allow)
        } else {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
        }
    }

    func webView(
        _ webView: WKWebView,
        createWebViewWith configuration: WKWebViewConfiguration,
        for navigationAction: WKNavigationAction,
        windowFeatures: WKWindowFeatures
    ) -> WKWebView? {
        if let url = navigationAction.request.url {
            NSWorkspace.shared.open(url)
        }
        return nil
    }

    @objc private func openInBrowser() {
        guard let dashboardURL else {
            showFailure("The private setup guide is still starting. Try again in a moment.")
            return
        }
        NSWorkspace.shared.open(dashboardURL)
    }

    @objc private func reloadGuide() {
        if webView.url != nil {
            webView.reload()
        } else {
            dashboardURL = nil
            startConnectionPolling()
        }
    }

    private var currentRelease: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "unknown"
    }

    private var configuredUpdateFeedURL: URL? {
        guard
            let value = Bundle.main.object(forInfoDictionaryKey: "WBUpdateFeedURL") as? String,
            let url = URL(string: value),
            wbTrustedUpdateFeedURL(url)
        else { return nil }
        return url
    }

    private var configuredVersionHistoryURL: URL? {
        guard
            let value = Bundle.main.object(forInfoDictionaryKey: "WBUpdateHistoryURL") as? String,
            let url = URL(string: value),
            url.scheme?.lowercased() == "https",
            url.host?.lowercased() == "github.com",
            url.path == "/widebandz/wb-setup/releases"
        else { return nil }
        return url
    }

    private func offerUpdatePreferenceOrCheck() {
        let defaults = UserDefaults.standard
        guard defaults.object(forKey: updatePreferenceKey) == nil else {
            refreshUpdateMenuState()
            if defaults.bool(forKey: updatePreferenceKey) {
                checkForUpdates(showUpToDate: false)
            }
            return
        }

        let alert = NSAlert()
        alert.alertStyle = .informational
        alert.messageText = "Would you like to check for updates when Wideband Setup starts?"
        alert.informativeText = "Checking for updates requires an Internet connection.\n\nURL:\nhttps://os.wideband.ai/version\n\nNo client details, setup answers, or machine identifiers are sent. You can change this later from the Wideband Setup menu."
        alert.addButton(withTitle: "Check Automatically")
        alert.addButton(withTitle: "Not Now")
        present(alert) { [weak self] response in
            guard let self else { return }
            let enabled = response == .alertFirstButtonReturn
            defaults.set(enabled, forKey: self.updatePreferenceKey)
            self.refreshUpdateMenuState()
            if enabled {
                self.checkForUpdates(showUpToDate: false)
            }
        }
    }

    @objc private func checkForUpdatesManually() {
        checkForUpdates(showUpToDate: true)
    }

    @objc private func toggleAutomaticUpdateChecks() {
        let enabled = !UserDefaults.standard.bool(forKey: updatePreferenceKey)
        UserDefaults.standard.set(enabled, forKey: updatePreferenceKey)
        refreshUpdateMenuState()
    }

    @objc private func openVersionHistory() {
        guard let url = configuredVersionHistoryURL else {
            showFailure("The version-history link is missing or damaged. Download a fresh copy or contact Wideband.")
            return
        }
        NSWorkspace.shared.open(url)
    }

    private func refreshUpdateMenuState() {
        automaticUpdatesMenuItem?.state = UserDefaults.standard.bool(forKey: updatePreferenceKey) ? .on : .off
        checkForUpdatesMenuItem?.isEnabled = !updateCheckInFlight
        checkForUpdatesMenuItem?.title = updateCheckInFlight ? "Checking for Updates…" : "Check for Updates…"
    }

    private func checkForUpdates(showUpToDate: Bool) {
        guard !updateCheckInFlight else { return }
        guard currentRelease != "unknown", let feedURL = configuredUpdateFeedURL else {
            if showUpToDate {
                showFailure("The update checker is missing its trusted Wideband URL. Download a fresh copy or contact Wideband.")
            }
            return
        }

        updateCheckInFlight = true
        refreshUpdateMenuState()

        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpShouldSetCookies = false
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.timeoutIntervalForRequest = 8
        configuration.timeoutIntervalForResource = 12
        let session = URLSession(configuration: configuration)
        updateSession = session

        var request = URLRequest(url: feedURL)
        request.timeoutInterval = 8
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("Wideband-Setup/\(currentRelease)", forHTTPHeaderField: "User-Agent")

        session.dataTask(with: request) { [weak self] data, response, error in
            DispatchQueue.main.async {
                guard let self else { return }
                self.updateCheckInFlight = false
                self.refreshUpdateMenuState()
                session.finishTasksAndInvalidate()
                self.updateSession = nil

                guard error == nil,
                      let http = response as? HTTPURLResponse,
                      http.statusCode == 200,
                      let responseURL = http.url,
                      let data else {
                    if showUpToDate {
                        self.showUpdateCheckError("Wideband Setup could not reach https://os.wideband.ai/version. Your setup was not changed. Check the connection and try again.")
                    }
                    return
                }

                do {
                    let update = try wbValidateUpdateFeed(
                        data: data,
                        responseURL: responseURL,
                        currentVersion: self.currentRelease
                    )
                    if update.isNewer {
                        self.showAvailableUpdate(update)
                    } else if showUpToDate {
                        self.showUpToDate()
                    }
                } catch {
                    if showUpToDate {
                        self.showUpdateCheckError(error.localizedDescription)
                    }
                }
            }
        }.resume()
    }

    private func showAvailableUpdate(_ update: WBValidatedUpdate) {
        let megabytes = Double(update.sizeBytes) / 1_048_576.0
        let gatekeeper = update.requiresGatekeeperException
            ? "This pilot is not notarized, so macOS may require Privacy & Security → Open Anyway."
            : "This release is signed and notarized for macOS."
        let alert = NSAlert()
        alert.alertStyle = .informational
        alert.messageText = "Wideband Setup \(update.version) is available"
        alert.informativeText = "You have \(currentRelease).\n\n\(update.summary)\n\n\(gatekeeper) Wideband will open the public release page; it will never install an update without you.\n\nDownload: \(update.artifactName) (\(String(format: "%.1f", megabytes)) MB)\nSHA-256: \(update.sha256)"
        alert.addButton(withTitle: "View & Download")
        alert.addButton(withTitle: "Later")
        alert.addButton(withTitle: "Version History")
        present(alert) { response in
            if response == .alertFirstButtonReturn {
                NSWorkspace.shared.open(update.releaseNotesURL)
            } else if response == .alertThirdButtonReturn {
                NSWorkspace.shared.open(update.historyURL)
            }
        }
    }

    private func showUpToDate() {
        let alert = NSAlert()
        alert.alertStyle = .informational
        alert.messageText = "Wideband Setup is up to date"
        alert.informativeText = "This Mac is running Wideband Setup \(currentRelease), the newest published release."
        alert.addButton(withTitle: "OK")
        alert.addButton(withTitle: "Version History")
        present(alert) { [weak self] response in
            if response == .alertSecondButtonReturn {
                self?.openVersionHistory()
            }
        }
    }

    private func showUpdateCheckError(_ detail: String) {
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = "Couldn’t check for updates"
        alert.informativeText = detail
        alert.addButton(withTitle: "OK")
        alert.addButton(withTitle: "Version History")
        present(alert) { [weak self] response in
            if response == .alertSecondButtonReturn {
                self?.openVersionHistory()
            }
        }
    }

    private func present(_ alert: NSAlert, completion: @escaping (NSApplication.ModalResponse) -> Void) {
        NSApp.activate(ignoringOtherApps: true)
        if let window, window.isVisible {
            alert.beginSheetModal(for: window, completionHandler: completion)
        } else {
            completion(alert.runModal())
        }
    }

    private func showFailure(_ detail: String) {
        NSApp.activate(ignoringOtherApps: true)
        let alert = NSAlert()
        alert.alertStyle = .critical
        alert.messageText = "Wideband Setup"
        alert.informativeText = detail
        alert.addButton(withTitle: "OK")
        if let window, window.isVisible {
            alert.beginSheetModal(for: window)
        } else {
            alert.runModal()
        }
    }
}

@main
struct WidebandSetupLauncher {
    static func main() {
        let application = NSApplication.shared
        let delegate = SetupAppDelegate()
        application.delegate = delegate
        application.run()
    }
}
