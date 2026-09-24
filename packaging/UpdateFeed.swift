import Foundation

struct WBUpdateFeedPayload: Decodable {
    let schema_version: Int
    let product: String
    let channel: String
    let generated_at: String
    let latest: WBUpdateReleasePayload
    let history_url: String
}

struct WBUpdateReleasePayload: Decodable {
    let version: String
    let build_id: String
    let published_at: String
    let minimum_macos: String
    let architecture: String
    let trust: String
    let requires_gatekeeper_exception: Bool
    let artifact_name: String
    let download_url: String
    let release_notes_url: String
    let sha256: String
    let size_bytes: Int64
    let summary: String
}

struct WBValidatedUpdate {
    let version: String
    let buildID: String
    let publishedAt: String
    let minimumMacOS: String
    let trust: String
    let requiresGatekeeperException: Bool
    let artifactName: String
    let downloadURL: URL
    let releaseNotesURL: URL
    let historyURL: URL
    let sha256: String
    let sizeBytes: Int64
    let summary: String
    let isNewer: Bool
}

enum WBUpdateFeedError: LocalizedError {
    case invalid(String)

    var errorDescription: String? {
        switch self {
        case .invalid(let detail):
            return "The Wideband update response was not trusted: \(detail)."
        }
    }
}

private struct WBVersion: Comparable {
    let parts: [Int]

    init?(_ value: String, componentCount: ClosedRange<Int> = 3...3) {
        let rawParts = value.split(separator: ".", omittingEmptySubsequences: false)
        guard componentCount.contains(rawParts.count) else { return nil }
        var parsed: [Int] = []
        for raw in rawParts {
            guard !raw.isEmpty, raw.allSatisfy({ $0.isNumber }), let number = Int(raw) else {
                return nil
            }
            parsed.append(number)
        }
        parts = parsed
    }

    static func < (lhs: WBVersion, rhs: WBVersion) -> Bool {
        let count = max(lhs.parts.count, rhs.parts.count)
        for index in 0..<count {
            let left = index < lhs.parts.count ? lhs.parts[index] : 0
            let right = index < rhs.parts.count ? rhs.parts[index] : 0
            if left != right { return left < right }
        }
        return false
    }
}

func wbTrustedUpdateFeedURL(_ url: URL) -> Bool {
    guard let components = URLComponents(url: url, resolvingAgainstBaseURL: false) else {
        return false
    }
    let path = components.percentEncodedPath
    return components.scheme?.lowercased() == "https"
        && components.host?.lowercased() == "os.wideband.ai"
        && (components.port == nil || components.port == 443)
        && components.user == nil
        && components.password == nil
        && components.query == nil
        && components.fragment == nil
        && (path == "/version" || path == "/version/")
}

private func wbTrustedGitHubURL(_ url: URL, path: String) -> Bool {
    guard let components = URLComponents(url: url, resolvingAgainstBaseURL: false) else {
        return false
    }
    return components.scheme?.lowercased() == "https"
        && components.host?.lowercased() == "github.com"
        && (components.port == nil || components.port == 443)
        && components.user == nil
        && components.password == nil
        && components.query == nil
        && components.fragment == nil
        && components.percentEncodedPath == path
}

private func wbISO8601Date(_ value: String) -> Bool {
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime]
    return formatter.date(from: value) != nil
}

func wbValidateUpdateFeed(
    data: Data,
    responseURL: URL,
    currentVersion: String
) throws -> WBValidatedUpdate {
    guard data.count <= 65_536 else {
        throw WBUpdateFeedError.invalid("response is larger than 64 KiB")
    }
    guard wbTrustedUpdateFeedURL(responseURL) else {
        throw WBUpdateFeedError.invalid("response came from an unexpected URL")
    }
    guard let installed = WBVersion(currentVersion) else {
        throw WBUpdateFeedError.invalid("installed version is malformed")
    }

    let feed: WBUpdateFeedPayload
    do {
        feed = try JSONDecoder().decode(WBUpdateFeedPayload.self, from: data)
    } catch {
        throw WBUpdateFeedError.invalid("JSON does not match schema 1")
    }

    guard feed.schema_version == 1 else {
        throw WBUpdateFeedError.invalid("unsupported schema")
    }
    guard feed.product == "wideband-setup" else {
        throw WBUpdateFeedError.invalid("wrong product")
    }
    guard feed.channel == "pilot" || feed.channel == "stable" else {
        throw WBUpdateFeedError.invalid("unknown release channel")
    }
    guard wbISO8601Date(feed.generated_at) else {
        throw WBUpdateFeedError.invalid("generated date is malformed")
    }

    let release = feed.latest
    guard let available = WBVersion(release.version) else {
        throw WBUpdateFeedError.invalid("release version is malformed")
    }
    let buildPrefix = "\(release.version)-"
    let buildSuffix = String(release.build_id.dropFirst(buildPrefix.count))
    guard release.build_id.hasPrefix(buildPrefix), buildSuffix.count == 14,
          buildSuffix.allSatisfy({ $0.isNumber }) else {
        throw WBUpdateFeedError.invalid("build ID is malformed")
    }
    guard wbISO8601Date(release.published_at) else {
        throw WBUpdateFeedError.invalid("publication date is malformed")
    }
    guard WBVersion(release.minimum_macos, componentCount: 2...3) != nil else {
        throw WBUpdateFeedError.invalid("minimum macOS version is malformed")
    }
    guard release.architecture == "arm64" else {
        throw WBUpdateFeedError.invalid("release architecture is not Apple silicon")
    }

    let expectedArtifact: String
    switch release.trust {
    case "ad-hoc":
        expectedArtifact = "Wideband-Setup-unsigned.dmg"
        guard release.requires_gatekeeper_exception else {
            throw WBUpdateFeedError.invalid("unsigned release omits the Gatekeeper warning")
        }
    case "developer-id":
        expectedArtifact = "Wideband-Setup-signed-unnotarized.dmg"
        guard release.requires_gatekeeper_exception else {
            throw WBUpdateFeedError.invalid("unnotarized release omits the Gatekeeper warning")
        }
    case "notarized":
        expectedArtifact = "Wideband-Setup.dmg"
        guard !release.requires_gatekeeper_exception else {
            throw WBUpdateFeedError.invalid("notarized release has the wrong Gatekeeper state")
        }
    default:
        throw WBUpdateFeedError.invalid("unknown trust state")
    }
    guard release.artifact_name == expectedArtifact else {
        throw WBUpdateFeedError.invalid("artifact name does not match the trust state")
    }

    guard let downloadURL = URL(string: release.download_url),
          wbTrustedGitHubURL(
            downloadURL,
            path: "/widebandz/wb-setup/releases/download/v\(release.version)/\(expectedArtifact)"
          ) else {
        throw WBUpdateFeedError.invalid("download is outside the Wideband release repository")
    }
    guard let releaseNotesURL = URL(string: release.release_notes_url),
          wbTrustedGitHubURL(
            releaseNotesURL,
            path: "/widebandz/wb-setup/releases/tag/v\(release.version)"
          ) else {
        throw WBUpdateFeedError.invalid("release notes are outside the Wideband release repository")
    }
    guard let historyURL = URL(string: feed.history_url),
          wbTrustedGitHubURL(historyURL, path: "/widebandz/wb-setup/releases") else {
        throw WBUpdateFeedError.invalid("version history is outside the Wideband release repository")
    }

    guard release.sha256.count == 64,
          release.sha256.allSatisfy({ $0.isNumber || ("a"..."f").contains(String($0)) }) else {
        throw WBUpdateFeedError.invalid("SHA-256 is malformed")
    }
    guard release.size_bytes > 0 else {
        throw WBUpdateFeedError.invalid("artifact size is invalid")
    }
    let summary = release.summary.trimmingCharacters(in: .whitespacesAndNewlines)
    guard summary == release.summary, !summary.isEmpty, summary.count <= 400 else {
        throw WBUpdateFeedError.invalid("release summary is invalid")
    }

    return WBValidatedUpdate(
        version: release.version,
        buildID: release.build_id,
        publishedAt: release.published_at,
        minimumMacOS: release.minimum_macos,
        trust: release.trust,
        requiresGatekeeperException: release.requires_gatekeeper_exception,
        artifactName: release.artifact_name,
        downloadURL: downloadURL,
        releaseNotesURL: releaseNotesURL,
        historyURL: historyURL,
        sha256: release.sha256,
        sizeBytes: release.size_bytes,
        summary: summary,
        isNewer: installed < available
    )
}
