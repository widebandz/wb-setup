#!/usr/bin/env python3
"""Build and validate the public Wideband Setup update feed."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import plistlib
import tempfile
import urllib.parse
from typing import Any


REPOSITORY = "widebandz/wb-setup"
TRUST_BY_ARTIFACT = {
    "Wideband-Setup-unsigned.dmg": ("ad-hoc", True),
    "Wideband-Setup-signed-unnotarized.dmg": ("developer-id", True),
    "Wideband-Setup.dmg": ("notarized", False),
}


def iso8601(value: str) -> bool:
    try:
        dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return value.endswith("Z")


def version(value: str, lengths: tuple[int, ...] = (3,)) -> bool:
    parts = value.split(".")
    return len(parts) in lengths and all(part.isdigit() and part for part in parts)


def exact_github_url(value: str, path: str) -> bool:
    parsed = urllib.parse.urlsplit(value)
    return (
        parsed.scheme == "https"
        and parsed.hostname == "github.com"
        and parsed.port in (None, 443)
        and not parsed.username
        and not parsed.password
        and parsed.path == path
        and not parsed.query
        and not parsed.fragment
    )


def validate_feed(feed: dict[str, Any]) -> None:
    if feed.get("schema_version") != 1:
        raise ValueError("schema_version must be 1")
    if feed.get("product") != "wideband-setup":
        raise ValueError("product must be wideband-setup")
    if feed.get("channel") not in {"pilot", "stable"}:
        raise ValueError("channel must be pilot or stable")
    if not isinstance(feed.get("generated_at"), str) or not iso8601(feed["generated_at"]):
        raise ValueError("generated_at must be UTC ISO-8601")

    latest = feed.get("latest")
    if not isinstance(latest, dict):
        raise ValueError("latest release is missing")
    release = latest.get("version")
    if not isinstance(release, str) or not version(release):
        raise ValueError("latest.version must have three numeric components")
    build_id = latest.get("build_id")
    prefix = f"{release}-"
    if not isinstance(build_id, str) or not build_id.startswith(prefix):
        raise ValueError("build_id must start with the release")
    suffix = build_id[len(prefix) :]
    if len(suffix) != 14 or not suffix.isdigit():
        raise ValueError("build_id must end with a 14-digit UTC build number")
    if not isinstance(latest.get("published_at"), str) or not iso8601(latest["published_at"]):
        raise ValueError("published_at must be UTC ISO-8601")
    if not isinstance(latest.get("minimum_macos"), str) or not version(latest["minimum_macos"], (2, 3)):
        raise ValueError("minimum_macos is malformed")
    if latest.get("architecture") != "arm64":
        raise ValueError("only the arm64 release channel is supported")

    artifact = latest.get("artifact_name")
    if artifact not in TRUST_BY_ARTIFACT:
        raise ValueError("artifact_name is not a recognized Wideband DMG")
    expected_trust, expected_exception = TRUST_BY_ARTIFACT[artifact]
    if latest.get("trust") != expected_trust:
        raise ValueError("artifact_name and trust disagree")
    if latest.get("requires_gatekeeper_exception") is not expected_exception:
        raise ValueError("artifact trust and Gatekeeper guidance disagree")

    expected_download = f"/{REPOSITORY}/releases/download/v{release}/{artifact}"
    if not isinstance(latest.get("download_url"), str) or not exact_github_url(
        latest["download_url"], expected_download
    ):
        raise ValueError("download_url must be the exact versioned Wideband GitHub asset")
    if not isinstance(latest.get("release_notes_url"), str) or not exact_github_url(
        latest["release_notes_url"], f"/{REPOSITORY}/releases/tag/v{release}"
    ):
        raise ValueError("release_notes_url must be the exact Wideband GitHub release")
    if not isinstance(feed.get("history_url"), str) or not exact_github_url(
        feed["history_url"], f"/{REPOSITORY}/releases"
    ):
        raise ValueError("history_url must be the Wideband GitHub release history")

    digest = latest.get("sha256")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("sha256 must be 64 lowercase hexadecimal characters")
    if not isinstance(latest.get("size_bytes"), int) or latest["size_bytes"] <= 0:
        raise ValueError("size_bytes must be positive")
    summary = latest.get("summary")
    if not isinstance(summary, str) or not summary or summary.strip() != summary or len(summary) > 400:
        raise ValueError("summary must be 1-400 trimmed characters")


def atomic_write(path: pathlib.Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        temporary = pathlib.Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def build_feed(
    *,
    manifest: pathlib.Path,
    app: pathlib.Path,
    artifact: pathlib.Path,
    channel: str,
    published_at: str,
    summary: str,
) -> dict[str, Any]:
    metadata = json.loads(manifest.read_text(encoding="utf-8"))
    release = metadata["release"]
    if not version(release):
        raise ValueError("installer manifest release is malformed")

    info_path = app / "Contents" / "Info.plist"
    build_path = app / "Contents" / "Resources" / "build-id.txt"
    with info_path.open("rb") as handle:
        info = plistlib.load(handle)
    app_release = info.get("CFBundleShortVersionString")
    build_number = str(info.get("CFBundleVersion", ""))
    build_id = build_path.read_text(encoding="utf-8").strip()
    if app_release != release or build_id != f"{release}-{build_number}":
        raise ValueError("app version, build ID, and installer manifest do not agree")

    artifact_name = artifact.name
    if artifact_name not in TRUST_BY_ARTIFACT:
        raise ValueError("artifact filename does not identify a supported trust state")
    trust, gatekeeper = TRUST_BY_ARTIFACT[artifact_name]
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()

    feed: dict[str, Any] = {
        "schema_version": 1,
        "product": "wideband-setup",
        "channel": channel,
        "generated_at": published_at,
        "latest": {
            "version": release,
            "build_id": build_id,
            "published_at": published_at,
            "minimum_macos": "14.0",
            "architecture": "arm64",
            "trust": trust,
            "requires_gatekeeper_exception": gatekeeper,
            "artifact_name": artifact_name,
            "download_url": f"https://github.com/{REPOSITORY}/releases/download/v{release}/{artifact_name}",
            "release_notes_url": f"https://github.com/{REPOSITORY}/releases/tag/v{release}",
            "sha256": digest,
            "size_bytes": artifact.stat().st_size,
            "summary": summary,
        },
        "history_url": f"https://github.com/{REPOSITORY}/releases",
    }
    validate_feed(feed)
    return feed


def main() -> int:
    root = pathlib.Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=pathlib.Path, default=root / "installer" / "manifest.json")
    parser.add_argument("--app", type=pathlib.Path, default=root / "dist" / "Wideband Setup.app")
    parser.add_argument("--artifact", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, default=root / "updates" / "version.json")
    parser.add_argument("--channel", choices=("pilot", "stable"), default="pilot")
    parser.add_argument("--published-at")
    parser.add_argument(
        "--summary",
        default="Adds client-controlled update checks, public release history, and durable SSH agent-session memory.",
    )
    args = parser.parse_args()
    published_at = args.published_at or dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
    feed = build_feed(
        manifest=args.manifest,
        app=args.app,
        artifact=args.artifact,
        channel=args.channel,
        published_at=published_at,
        summary=args.summary,
    )
    atomic_write(args.output, (json.dumps(feed, indent=2, sort_keys=False) + "\n").encode())
    print(f"wrote {args.output} for Wideband Setup {feed['latest']['version']}")
    print(f"sha256 {feed['latest']['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
