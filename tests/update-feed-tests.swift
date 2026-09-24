import Foundation

@main
struct UpdateFeedTests {
    private static var passed = 0
    private static var failed = 0

    private static let endpoint = URL(string: "https://os.wideband.ai/version")!

    private static let validJSON = """
    {
      "schema_version": 1,
      "product": "wideband-setup",
      "channel": "pilot",
      "generated_at": "2026-09-23T20:00:00Z",
      "latest": {
        "version": "0.6.0",
        "build_id": "0.6.0-20260923200000",
        "published_at": "2026-09-23T20:00:00Z",
        "minimum_macos": "13.0",
        "architecture": "arm64",
        "trust": "ad-hoc",
        "requires_gatekeeper_exception": true,
        "artifact_name": "Wideband-Setup-unsigned.dmg",
        "download_url": "https://github.com/widebandz/wb-setup/releases/download/v0.6.0/Wideband-Setup-unsigned.dmg",
        "release_notes_url": "https://github.com/widebandz/wb-setup/releases/tag/v0.6.0",
        "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "size_bytes": 22000000,
        "summary": "Adds client-controlled update checks and a public release history."
      },
      "history_url": "https://github.com/widebandz/wb-setup/releases"
    }
    """

    private static func check(_ condition: @autoclosure () -> Bool, _ name: String) {
        if condition() {
            passed += 1
            print("  ✓ \(name)")
        } else {
            failed += 1
            print("  ✗ \(name)")
        }
    }

    private static func validates(_ json: String, current: String = "0.5.1", url: URL = endpoint) -> WBValidatedUpdate? {
        try? wbValidateUpdateFeed(data: Data(json.utf8), responseURL: url, currentVersion: current)
    }

    static func main() {
        print("▩ Wideband update-feed tests")

        let valid = validates(validJSON)
        check(valid?.isNewer == true, "a valid newer Wideband release is accepted")
        check(validates(validJSON, current: "0.6.0")?.isNewer == false, "the installed release is not offered again")

        let numeric = validJSON
            .replacingOccurrences(of: "0.6.0", with: "0.10.0")
            .replacingOccurrences(of: "20260923200000", with: "20260923200001")
        check(validates(numeric, current: "0.9.9")?.isNewer == true, "versions compare numerically, not lexicographically")

        check(
            validates(validJSON, url: URL(string: "https://wideband.ai/version")!) == nil,
            "a response from the wrong host is refused"
        )
        check(
            validates(validJSON, url: URL(string: "https://os.wideband.ai/version/")!) != nil,
            "the Pages trailing-slash form is accepted"
        )

        let wrongProduct = validJSON.replacingOccurrences(
            of: "\"product\": \"wideband-setup\"",
            with: "\"product\": \"different-product\""
        )
        check(validates(wrongProduct) == nil, "a feed for another product is refused")

        let outsideDownload = validJSON.replacingOccurrences(
            of: "https://github.com/widebandz/wb-setup/releases/download/v0.6.0/Wideband-Setup-unsigned.dmg",
            with: "https://example.com/Wideband-Setup-unsigned.dmg"
        )
        check(validates(outsideDownload) == nil, "a download outside the public Wideband repository is refused")

        let badHash = validJSON.replacingOccurrences(
            of: String(repeating: "a", count: 64),
            with: "not-a-sha256"
        )
        check(validates(badHash) == nil, "a malformed artifact checksum is refused")

        let missingGatekeeperWarning = validJSON.replacingOccurrences(
            of: "\"requires_gatekeeper_exception\": true",
            with: "\"requires_gatekeeper_exception\": false"
        )
        check(validates(missingGatekeeperWarning) == nil, "an unsigned release cannot omit the Gatekeeper warning")

        let huge = Data(repeating: 0x20, count: 65_537)
        check(
            (try? wbValidateUpdateFeed(data: huge, responseURL: endpoint, currentVersion: "0.5.1")) == nil,
            "an oversized response is refused before decoding"
        )

        print("\n  \(passed) passed · \(failed) failed")
        if failed != 0 { exit(1) }
    }
}
