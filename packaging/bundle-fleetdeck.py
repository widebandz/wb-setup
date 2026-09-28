#!/usr/bin/env python3
"""Build and verify an allowlisted customer Fleetdeck source bundle.

Only generic, tracked Fleetdeck installer/assets are copied from the reviewed
working tree. The standalone phone portal replaces the operator's large portal
module, which contains private topology and notes that must never ship.
"""

from __future__ import annotations

import hashlib
import fcntl
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile


MANIFEST = ".wideband-fleetdeck-bundle.json"
SOURCE_FILES = {
    "install.sh",
    "bin/fleetdeck",
    "VERSION",
    "LICENSE",
    "NOTICE",
    "launchagents/fleetdeck-portal.plist.tmpl",
    "assets/icon-192.png",
    "assets/icon-512.png",
}
GENERATED_FILES = {"portal_server.py", "config.example.json", "services.example.json"}
REQUIRED = SOURCE_FILES | GENERATED_FILES
UPGRADE_FILES = {"portal_server.py"}
PORTAL_SOURCE = Path(__file__).with_name("customer-portal.py")
PRIVATE_NAMES = {".git", "auth", "config.json", "services.json", ".fleetdeck-notes.json"}
PRIVATE_DIRS = {"backup", "backups", "notes"}
STATIC_IDENTITY = re.compile(
    rb"(?i)(?:[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}|[a-z0-9.-]+\.ts\.net)"
)
OPERATOR_SOURCE_MARKERS = (b"SEED_NOTES", b"NETMAP_URL", b"TRACE_IMESSAGE_HANDLE")


def safe_name(value: str) -> bool:
    path = PurePosixPath(value)
    parts = value.split("/")
    if not value or path.is_absolute() or any(part in {"", ".", ".."} for part in parts):
        return False
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return False
    if any(part.lower() in PRIVATE_NAMES or part.lower() in PRIVATE_DIRS for part in parts):
        return False
    if any(part.endswith("~") or ".bak" in part.lower() or ".backup" in part.lower() for part in parts):
        return False
    return value != MANIFEST


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def regular_file(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except OSError:
        return False
    return stat.S_ISREG(mode)


def check_source(root: Path) -> None:
    for name in SOURCE_FILES:
        if not regular_file(root / name):
            raise ValueError(f"missing tracked Fleetdeck customer file: {name}")
    if "CUSTOMER_MODE" not in (root / "install.sh").read_text(encoding="utf-8"):
        raise ValueError("Fleetdeck install.sh lacks the customer-mode guard")
    if "__ROOT__/portal_server.py" not in (root / "launchagents/fleetdeck-portal.plist.tmpl").read_text(encoding="utf-8"):
        raise ValueError("Fleetdeck LaunchAgent does not point to the customer portal path")


def check_bundle(root: Path) -> None:
    for name in REQUIRED:
        if not regular_file(root / name):
            raise ValueError(f"missing bundled Fleetdeck customer file: {name}")
    check_source(root)
    portal = (root / "portal_server.py").read_text(encoding="utf-8")
    # The first customer portal used `route` for the health request path.
    # Accept that verified release so it can upgrade to the current portal.
    health_markers = ('route == "/healthz"', 'raw_path == "/healthz"')
    if "def onboarding_config" not in portal or not any(marker in portal for marker in health_markers):
        raise ValueError("standalone customer portal lacks required routes")


def scan_private(root: Path, names: set[str]) -> None:
    for name in names:
        path = root / name
        data = path.read_bytes()
        if STATIC_IDENTITY.search(data) or any(marker in data for marker in OPERATOR_SOURCE_MARKERS):
            raise ValueError(f"operator identifier found in customer bundle: {name}")


def build(source: Path, target: Path) -> None:
    source = source.resolve(strict=True)
    root = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "--show-toplevel"], text=True
    ).strip()
    if Path(root).resolve() != source:
        raise ValueError("Fleetdeck source must be a repository root")
    names = subprocess.check_output(
        ["git", "-C", str(source), "ls-files", "--cached", "-z"]
    ).split(b"\0")
    paths = [os.fsdecode(name) for name in names if name]
    if not SOURCE_FILES.issubset(paths):
        raise ValueError("required Fleetdeck customer files are not tracked")
    for name in paths:
        if not safe_name(name) or not regular_file(source / name):
            raise ValueError(f"unsafe or missing tracked Fleetdeck file: {name!r}")
    check_source(source)
    if not regular_file(PORTAL_SOURCE):
        raise ValueError("standalone customer portal source is missing")
    target.mkdir(parents=True, exist_ok=False)
    try:
        hashes: dict[str, str] = {}
        for name in sorted(SOURCE_FILES):
            destination = target / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name, destination)
            hashes[name] = digest(destination)
        shutil.copy2(PORTAL_SOURCE, target / "portal_server.py")
        (target / "config.example.json").write_text(json.dumps({
            "brand": "fleetdeck", "machine": "", "label_prefix": "com.example",
            "ports": {"portal": 8790, "chat": 8783, "ttyd": 8784, "adopt": 8793},
            "agents": {"show": False, "actions": False, "include": [], "exclude": []},
        }, indent=2) + "\n", encoding="utf-8")
        (target / "services.example.json").write_text(
            json.dumps({"groups": [{"id": "apps", "label": "apps"}], "services": []}, indent=2) + "\n",
            encoding="utf-8")
        for name in GENERATED_FILES:
            hashes[name] = digest(target / name)
        (target / MANIFEST).write_text(
            json.dumps({"schema_version": 1, "source": "customer-allowlisted-working-tree",
                        "files": hashes}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        verify(target)
    except Exception:
        shutil.rmtree(target)
        raise


def verify_managed(root: Path) -> dict[str, str]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Fleetdeck source bundle path is not a real directory")
    if not regular_file(root / MANIFEST):
        raise ValueError("Fleetdeck source bundle manifest is missing")
    metadata = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    if metadata.get("schema_version") != 1 or metadata.get("source") != "customer-allowlisted-working-tree":
        raise ValueError("unsupported Fleetdeck source bundle")
    hashes = metadata.get("files")
    if not isinstance(hashes, dict) or set(hashes) != REQUIRED:
        raise ValueError("Fleetdeck source bundle file list is incomplete")
    if any(not isinstance(name, str) or not safe_name(name) or not isinstance(value, str)
           or len(value) != 64 for name, value in hashes.items()):
        raise ValueError("unsafe Fleetdeck source bundle file list")
    for name, expected in hashes.items():
        parent = root
        for part in PurePosixPath(name).parts[:-1]:
            parent = parent / part
            if parent.is_symlink():
                raise ValueError(f"Fleetdeck source bundle path contains a symlink: {name}")
        if not regular_file(root / name) or digest(root / name) != expected:
            raise ValueError(f"Fleetdeck source bundle checksum mismatch: {name}")
    check_bundle(root)
    scan_private(root, set(hashes))
    return hashes


def verify(root: Path) -> None:
    hashes = verify_managed(root)
    actual: set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Fleetdeck source bundle contains a symlink: {path}")
        if path.is_dir():
            if not safe_name(path.relative_to(root).as_posix()):
                raise ValueError(f"unsafe Fleetdeck source bundle directory: {path}")
            continue
        name = path.relative_to(root).as_posix()
        if not regular_file(path) or (name != MANIFEST and not safe_name(name)):
            raise ValueError(f"unsafe Fleetdeck source bundle file: {name}")
        if name != MANIFEST:
            actual.add(name)
    if actual != set(hashes):
        raise ValueError("Fleetdeck source bundle contains missing or extra files")


def check_current(bundle: Path, installed: Path) -> None:
    verify(bundle)
    expected = verify_managed(installed)
    packaged = json.loads((bundle / MANIFEST).read_text(encoding="utf-8"))["files"]
    if expected != packaged:
        raise ValueError("installed customer source differs from this release; review upgrade before replacing it")


def stage_copy(source: Path, directory: Path) -> Path:
    """Copy a verified file beside its destination for one atomic replacement."""
    fd, name = tempfile.mkstemp(prefix=".wideband-fleetdeck-", dir=directory)
    staged = Path(name)
    try:
        with os.fdopen(fd, "wb") as output:
            input_fd = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(input_fd, "rb") as original:
                info = os.fstat(original.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError(f"Fleetdeck upgrade source is not a regular file: {source}")
                shutil.copyfileobj(original, output)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(staged, stat.S_IMODE(info.st_mode))
        return staged
    except Exception:
        staged.unlink(missing_ok=True)
        raise


def upgrade(bundle: Path, installed: Path) -> Path | None:
    """Replace only the generated portal and manifest of a verified bundle."""
    # A separate stable lock inode still serializes upgrades after the bundle
    # manifest inode is replaced. It lives outside client-owned Fleetdeck data.
    lock_path = installed.parent / f".{installed.name}.wideband-upgrade.lock"
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        info = os.fstat(lock_fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or info.st_mode & 0o077):
            raise ValueError("Fleetdeck upgrade lock is unsafe")
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        verify(bundle)
        old_hashes = verify_managed(installed)
        old_manifest = json.loads((installed / MANIFEST).read_text(encoding="utf-8"))
        new_manifest = json.loads((bundle / MANIFEST).read_text(encoding="utf-8"))
        if ({key: value for key, value in old_manifest.items() if key != "files"}
                != {key: value for key, value in new_manifest.items() if key != "files"}):
            raise ValueError("Fleetdeck package identity or source differs; review upgrade")
        new_hashes = new_manifest["files"]
        changed = {name for name in REQUIRED if old_hashes[name] != new_hashes[name]}
        if not changed:
            return None
        if changed != UPGRADE_FILES:
            raise ValueError("Fleetdeck bundle differs outside the generated portal; review upgrade")

        backup = Path(tempfile.mkdtemp(prefix=f".{installed.name}-upgrade-backup-", dir=installed.parent))
        os.chmod(backup, 0o700)
        staged: list[Path] = []
        replaced = False
        try:
            for name in ("portal_server.py", MANIFEST):
                staged_backup = stage_copy(installed / name, backup)
                os.replace(staged_backup, backup / name)
            if digest(backup / "portal_server.py") != old_hashes["portal_server.py"]:
                raise ValueError("Fleetdeck portal changed during backup; review upgrade")
            if (backup / MANIFEST).read_bytes() != (installed / MANIFEST).read_bytes():
                raise ValueError("Fleetdeck manifest changed during backup; review upgrade")
            # Recheck after staging, immediately before either destination is
            # replaced. Other tracked files and private client files stay put.
            for name in ("portal_server.py", MANIFEST):
                staged.append(stage_copy(bundle / name, installed))
            if verify_managed(installed) != old_hashes:
                raise ValueError("Fleetdeck source changed during upgrade; review it before retrying")
            os.replace(staged[0], installed / "portal_server.py")
            replaced = True
            os.replace(staged[1], installed / MANIFEST)
            if verify_managed(installed) != new_hashes:
                raise ValueError("Fleetdeck upgrade did not verify")
            return backup
        except Exception as error:
            if replaced:
                try:
                    for name in ("portal_server.py", MANIFEST):
                        restore = stage_copy(backup / name, installed)
                        staged.append(restore)
                        os.replace(restore, installed / name)
                    if verify_managed(installed) != old_hashes:
                        raise ValueError("restored Fleetdeck source did not verify")
                except Exception as rollback_error:
                    raise RuntimeError(
                        f"Fleetdeck upgrade failed and rollback needs review; backup: {backup}"
                    ) from rollback_error
            raise ValueError(f"Fleetdeck upgrade stopped; previous source preserved: {error}") from error
        finally:
            for path in staged:
                path.unlink(missing_ok=True)
    finally:
        os.close(lock_fd)


def restore_previous(bundle: Path, installed: Path, backup: Path) -> None:
    """Restore a completed portal upgrade after its activation check fails.

    Only the two managed files are restored. Client config, notes, services and
    project work are not part of the backup or this operation.
    """
    if (backup.parent != installed.parent
            or not backup.name.startswith(f".{installed.name}-upgrade-backup-")
            or backup.is_symlink() or not backup.is_dir()):
        raise ValueError("Fleetdeck portal backup path is unsafe")
    lock_path = installed.parent / f".{installed.name}.wideband-upgrade.lock"
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        info = os.fstat(lock_fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or info.st_mode & 0o077):
            raise ValueError("Fleetdeck upgrade lock is unsafe")
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        verify(bundle)
        current_hashes = verify_managed(installed)
        packaged = json.loads((bundle / MANIFEST).read_text(encoding="utf-8"))
        if current_hashes != packaged["files"]:
            raise ValueError("Fleetdeck source changed after upgrade; preserve backup for review")
        backup_info = backup.stat()
        if backup_info.st_uid != os.getuid() or backup_info.st_mode & 0o077:
            raise ValueError("Fleetdeck portal backup permissions are unsafe")
        old_manifest_path = backup / MANIFEST
        old_portal_path = backup / "portal_server.py"
        if not regular_file(old_manifest_path) or not regular_file(old_portal_path):
            raise ValueError("Fleetdeck portal backup is incomplete")
        for path in (old_manifest_path, old_portal_path):
            item = path.stat()
            if item.st_uid != os.getuid() or item.st_nlink != 1:
                raise ValueError("Fleetdeck portal backup is unsafe")
        old_manifest = json.loads(old_manifest_path.read_text(encoding="utf-8"))
        old_hashes = old_manifest.get("files")
        if (not isinstance(old_hashes, dict) or set(old_hashes) != REQUIRED
                or {key: value for key, value in old_manifest.items() if key != "files"}
                != {key: value for key, value in packaged.items() if key != "files"}
                or {name for name in REQUIRED if old_hashes[name] != current_hashes[name]}
                != UPGRADE_FILES or digest(old_portal_path) != old_hashes["portal_server.py"]):
            raise ValueError("Fleetdeck portal backup does not match this upgrade")

        staged: list[Path] = []
        replaced = False
        try:
            for path in (old_portal_path, old_manifest_path):
                staged.append(stage_copy(path, installed))
            os.replace(staged[0], installed / "portal_server.py")
            replaced = True
            os.replace(staged[1], installed / MANIFEST)
            if verify_managed(installed) != old_hashes:
                raise ValueError("restored Fleetdeck portal did not verify")
        except Exception as error:
            if replaced:
                try:
                    for name in ("portal_server.py", MANIFEST):
                        latest = stage_copy(bundle / name, installed)
                        staged.append(latest)
                        os.replace(latest, installed / name)
                    if verify_managed(installed) != current_hashes:
                        raise ValueError("current Fleetdeck portal could not be restored")
                except Exception as repair_error:
                    raise RuntimeError(
                        f"Fleetdeck portal restore failed and needs review; backup: {backup}"
                    ) from repair_error
            raise ValueError(f"Fleetdeck portal restore stopped; backup preserved: {error}") from error
        finally:
            for path in staged:
                path.unlink(missing_ok=True)
    finally:
        os.close(lock_fd)


def main() -> int:
    try:
        if len(sys.argv) == 4 and sys.argv[1] == "build":
            build(Path(sys.argv[2]), Path(sys.argv[3]))
        elif len(sys.argv) == 3 and sys.argv[1] == "verify":
            verify(Path(sys.argv[2]))
        elif len(sys.argv) == 3 and sys.argv[1] == "verify-managed":
            verify_managed(Path(sys.argv[2]))
        elif len(sys.argv) == 4 and sys.argv[1] == "check-current":
            check_current(Path(sys.argv[2]), Path(sys.argv[3]))
        elif len(sys.argv) == 4 and sys.argv[1] == "upgrade":
            backup = upgrade(Path(sys.argv[2]), Path(sys.argv[3]))
            print("upgraded" if backup else "current")
            if backup:
                print(backup)
        elif len(sys.argv) == 5 and sys.argv[1] == "restore":
            restore_previous(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
            print("restored")
        else:
            print("usage: bundle-fleetdeck.py build SOURCE DEST | verify DEST | verify-managed INSTALLED | check-current BUNDLE INSTALLED | upgrade BUNDLE INSTALLED | restore BUNDLE INSTALLED BACKUP", file=sys.stderr)
            return 2
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError, UnicodeError) as error:
        print(f"Fleetdeck bundle: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
