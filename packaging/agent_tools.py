"""Package and activate the private browser tools used by customer agents."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.request

VERSION = "1.58.2"
MANIFEST = ".wideband-agent-tools.json"
PACKAGES = {
    "playwright": "vA30H8Nvkq/cPBnNw4Q8TWz1EJyqgpuinBcHET0YVJVFldr8JDNiU9LaWAE1KqSkRYazuaBhTpB5ZzShOezQ6A==",
    "playwright-core": "yZkEtftgwS8CsfYo7nm0KE8jsvm6i/PTgVtB8DL726wNf6H2IMsDuxCpJj59KDaxCtSnrWan2AeDqM7JBaultg==",
}


def _sha(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def _inventory(root: Path) -> dict:
    result = {}
    for path in sorted(root.rglob("*")):
        name = path.relative_to(root).as_posix()
        if name == MANIFEST:
            continue
        if path.is_symlink():
            target = os.readlink(path)
            if Path(target).is_absolute() or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError("browser tools contain an external symlink")
            result[name] = {"link": target}
        elif path.is_file():
            result[name] = {"sha256": _sha(path), "executable": bool(path.stat().st_mode & 0o111)}
        elif not path.is_dir():
            raise ValueError("browser tools contain an unsupported file")
    return result


def verify(root: Path) -> dict:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("bundled browser tools are missing")
    path = root / MANIFEST
    if path.is_symlink() or not path.is_file():
        raise ValueError("browser tools manifest is missing")
    data = json.loads(path.read_text(encoding="utf-8"))
    if (data.get("schema_version") != 1 or data.get("playwright") != VERSION
            or data.get("files") != _inventory(root)):
        raise ValueError("browser tools failed their package integrity check")
    for name in ("node_modules/playwright/cli.js", "node_modules/playwright/index.js",
                 "node_modules/playwright-core/browsers.json"):
        if name not in data["files"]:
            raise ValueError("browser tools package is incomplete")
    if not any(name.endswith("/Chromium.app/Contents/MacOS/Chromium")
               or name.endswith("/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing")
               for name in data["files"]):
        raise ValueError("bundled Chromium is missing")
    return data


def build(target: Path, node: Path) -> None:
    """Fetch pinned npm archives; install matching browsers during packaging."""
    if target.exists() or target.is_symlink():
        verify(target)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".agent-tools-", dir=target.parent) as tmp:
        staged = Path(tmp) / "payload"
        staged.mkdir()
        modules = staged / "node_modules"
        modules.mkdir()
        for package, expected in PACKAGES.items():
            archive = Path(tmp) / (package + ".tgz")
            url = f"https://registry.npmjs.org/{package}/-/{package}-{VERSION}.tgz"
            with urllib.request.urlopen(url, timeout=90) as source, archive.open("wb") as output:
                shutil.copyfileobj(source, output)
            actual = base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode()
            if actual != expected:
                raise ValueError("Playwright archive failed its pinned integrity check")
            destination = modules / package
            destination.mkdir()
            with tarfile.open(archive, "r:gz") as source:
                for entry in source:
                    parts = Path(entry.name).parts
                    if (not parts or parts[0] != "package" or any(part in ("..", ".") for part in parts)
                            or entry.name.startswith("/") or not (entry.isfile() or entry.isdir())):
                        raise ValueError("unsafe Playwright package archive")
                    relative = Path(*parts[1:])
                    output_path = destination / relative
                    if entry.isdir():
                        output_path.mkdir(parents=True, exist_ok=True)
                    else:
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        with source.extractfile(entry) as content, output_path.open("wb") as output:
                            shutil.copyfileobj(content, output)
                        output_path.chmod(0o755 if entry.mode & 0o111 else 0o644)
        env = os.environ.copy()
        env["PATH"] = f"{node.parent}:/usr/bin:/bin:/usr/sbin:/sbin"
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(staged / "browsers")
        result = subprocess.run([str(node), str(modules / "playwright/cli.js"), "install", "chromium"],
                                env=env, check=False)
        if result.returncode:
            raise ValueError("matching Chromium download did not finish")
        # Playwright's GC links name the temporary build path, not client data.
        shutil.rmtree(staged / "browsers/.links", ignore_errors=True)
        data = {"schema_version": 1, "playwright": VERSION, "files": _inventory(staged)}
        (staged / MANIFEST).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        verify(staged)
        os.replace(staged, target)


def _private(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("private browser tools path is a symlink")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("private browser tools path has unsafe ownership or permissions")


def environment(bundle: Path, node: Path) -> dict[str, str]:
    """Stage without changing any project's npm installation or browser profile."""
    data = verify(bundle)
    home = Path.home()
    _private(home / ".wideband")
    root = home / ".wideband/agent-tools"
    _private(root)
    versions = root / "versions"
    _private(versions)
    revision = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:24]
    installed = versions / revision
    if installed.is_symlink():
        raise ValueError("installed browser tools path is a symlink")
    if installed.exists():
        if verify(installed) != data:
            raise ValueError("installed browser tools were changed; previous copy retained")
    else:
        with tempfile.TemporaryDirectory(prefix=".stage-", dir=versions) as tmp:
            staged = Path(tmp) / "payload"
            shutil.copytree(bundle, staged, symlinks=True)
            staged.chmod(0o700)
            if verify(staged) != data:
                raise ValueError("browser tools staging did not preserve the package")
            try:
                os.rename(staged, installed)
            except FileExistsError:
                if verify(installed) != data:
                    raise ValueError("concurrent browser tools installation differs")
    active = root / "active"
    if active.is_symlink():
        raise ValueError("browser tools pointer is a symlink")
    fd, temp = tempfile.mkstemp(prefix=".active-", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as output:
            output.write(revision + "\n")
        os.replace(temp, active)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return {"FLEETDECK_VERIFIED_NODE": str(node),
            "FLEETDECK_PLAYWRIGHT_CLI": str(installed / "node_modules/playwright/cli.js"),
            "WB_PLAYWRIGHT_MODULE": str(installed / "node_modules/playwright/index.js"),
            "NODE_PATH": str(installed / "node_modules"),
            "PLAYWRIGHT_BROWSERS_PATH": str(installed / "browsers")}
