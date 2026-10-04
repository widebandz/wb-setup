#!/usr/bin/env python3
"""Reuse an already built tool payload after checking its complete manifest."""

import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys


def verify(root: Path) -> None:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("toolchain source is missing or redirected")
    files = set()
    for path in root.rglob("*"):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise ValueError("toolchain cache contains an unsafe file")
        if path.is_file() and path.name != "manifest.sha256":
            files.add(path.relative_to(root).as_posix())
    manifest = root / "manifest.sha256"
    expected = set()
    for line in manifest.read_text(encoding="ascii").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (\S+)", line)
        if not match:
            raise ValueError("invalid toolchain manifest")
        digest, name = match.groups()
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or name in expected or name not in files:
            raise ValueError("unsafe toolchain manifest path")
        expected.add(name)
        actual = hashlib.sha256((root / name).read_bytes()).hexdigest()
        if actual != digest:
            raise ValueError("cached toolchain checksum differs")
    if files != expected:
        raise ValueError("cached toolchain manifest is incomplete")
    source = Path(__file__).with_name("build-toolchain.py")
    spec = importlib.util.spec_from_file_location("wideband_toolchain_build", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    pins = {name: {"url": values[0], "sha256": values[1]} for name, values in module.ARCHIVES.items()}
    if json.loads((root / "provenance.json").read_text()) != pins:
        raise ValueError("cached toolchain does not match current package pins")


if len(sys.argv) != 3:
    raise SystemExit("usage: copy-toolchain.py SOURCE TARGET")
source, target = (Path(arg).absolute() for arg in sys.argv[1:])
verify(source)
if target.exists() or target.is_symlink():
    raise SystemExit("toolchain target already exists")
shutil.copytree(source, target)
verify(target)
