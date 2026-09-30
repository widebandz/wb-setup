#!/usr/bin/env python3
"""Build the pinned, Homebrew-independent Apple Silicon client tool payload.

Run on the release Mac with Xcode Command Line Tools and CMake. All downloads
have fixed SHA-256 values. The output is a relocatable directory; the client
installer verifies its complete manifest before activating a private copy.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile


ARCHIVES = {
    "libevent": ("https://github.com/libevent/libevent/releases/download/release-2.1.12-stable/libevent-2.1.12-stable.tar.gz", "92e6de1be9ec176428fd2367677e61ceffc2ee1cb119035037a27d346b0403bb", "libevent-2.1.12-stable.tar.gz", "libevent-2.1.12-stable"),
    "utf8proc": ("https://github.com/JuliaStrings/utf8proc/archive/refs/tags/v2.11.3.tar.gz", "abfed50b6d4da51345713661370290f4f4747263ee73dc90356299dfc7990c78", "utf8proc-2.11.3.tar.gz", "utf8proc-2.11.3"),
    "tmux": ("https://github.com/tmux/tmux/releases/download/3.6a/tmux-3.6a.tar.gz", "b6d8d9c76585db8ef5fa00d4931902fa4b8cbe8166f528f44fc403961a3f3759", "tmux-3.6a.tar.gz", "tmux-3.6a"),
    "libuv": ("https://github.com/libuv/libuv/archive/refs/tags/v1.52.1.tar.gz", "478baf2599bfbc882c355288c9cb6f92e0e7dda435fa04031fa5b607cf3f414c", "libuv-v1.52.1.tar.gz", "libuv-1.52.1"),
    "json-c": ("https://s3.amazonaws.com/json-c_releases/releases/json-c-0.19.tar.gz", "37ad0249902e301bd9052bf712e511fcc6acff4ecaad4b5900aad9ce564e26de", "json-c-0.19.tar.gz", "json-c-0.19"),
    "libwebsockets": ("https://github.com/warmcat/libwebsockets/archive/refs/tags/v5.0.0.tar.gz", "f853c6582101cfcee3a5a9e28ae92ab19d9735c5f31f0bb2e9794b5106123962", "libwebsockets-v5.0.0.tar.gz", "libwebsockets-5.0.0"),
    "ttyd": ("https://github.com/tsl0922/ttyd/archive/refs/tags/1.7.7.tar.gz", "039dd995229377caee919898b7bd54484accec3bba49c118e2d5cd6ec51e3650", "ttyd-1.7.7.tar.gz", "ttyd-1.7.7"),
    "python": ("https://github.com/astral-sh/python-build-standalone/releases/download/20260924/cpython-3.11.16%2B20260924-aarch64-apple-darwin-install_only_stripped.tar.gz", "e1d745b07b6acc0641dbb3237d3c5953deeeed182141bab2242684076fd86547", "cpython-3.11.16.tar.gz", "python"),
    "node": ("https://nodejs.org/dist/v24.21.0/node-v24.21.0-darwin-arm64.tar.xz", "6239d4cf92d864487ec8cd3615038f7b67e7f58b77b21cd2f09ea9fbd68065fe", "node-v24.21.0.tar.xz", "node-v24.21.0-darwin-arm64"),
    "imsg": ("https://github.com/openclaw/imsg/releases/download/v0.15.9/imsg-macos.zip", "5d862ddbf900c36a3360d92467b51b2b7e852634fd05b544ba8489ee3946c63f", "imsg-v0.15.9.zip", "imsg-release"),
    "imsg-license": ("https://raw.githubusercontent.com/openclaw/imsg/v0.15.9/LICENSE", "14293556b79940745123d0160c71d27ed0e9fe9b8a848093f3ed78f4853caafe", "imsg-LICENSE", ""),
}


def run(*args: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    result = subprocess.run(args, cwd=cwd, env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode:
        tail = "\n".join(result.stdout.splitlines()[-25:])
        raise RuntimeError(f"toolchain build command failed: {args[0]}\n{tail}")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(work: Path, name: str) -> Path:
    url, expected, filename, root = ARCHIVES[name]
    archive = work / filename
    run("/usr/bin/curl", "--fail", "--location", "--retry", "2", "--silent", "--show-error", "--output", str(archive), url)
    if sha(archive) != expected:
        raise ValueError(f"{name} download did not match the pinned SHA-256")
    if root:
        if archive.suffix == ".zip":
            target = work / root
            target.mkdir()
            with zipfile.ZipFile(archive) as source:
                for item in source.infolist():
                    parts = Path(item.filename).parts
                    if not parts or any(part in (".", "..") for part in parts) or item.filename.startswith("/"):
                        raise ValueError(f"unsafe {name} archive entry")
                source.extractall(target)
            return target
        run("/usr/bin/tar", "-xJf" if filename.endswith(".xz") else "-xzf", str(archive), "-C", str(work))
        target = work / root
        if not target.is_dir() or target.is_symlink():
            raise ValueError(f"{name} archive root is invalid")
        return target
    return archive


def cmake_build(source: Path, build: Path, prefix: Path, *extra: str) -> None:
    run("cmake", "-S", str(source), "-B", str(build),
        "-DCMAKE_OSX_ARCHITECTURES=arm64", "-DCMAKE_OSX_DEPLOYMENT_TARGET=14.0",
        f"-DCMAKE_INSTALL_PREFIX={prefix}", f"-DCMAKE_PREFIX_PATH={prefix}", *extra)
    run("cmake", "--build", str(build), "-j8")
    run("cmake", "--install", str(build))


def compile_tools(work: Path, sources: dict[str, Path]) -> Path:
    prefix = work / "build-prefix"
    prefix.mkdir()
    env = os.environ.copy()
    env.update(MACOSX_DEPLOYMENT_TARGET="14.0", CFLAGS="-O2 -mmacosx-version-min=14.0",
               LDFLAGS="-mmacosx-version-min=14.0")
    run(str(sources["libevent"] / "configure"), f"--prefix={prefix}", "--disable-shared",
        "--enable-static", "--disable-openssl", "--disable-libevent-regress",
        "--disable-samples", cwd=sources["libevent"], env=env)
    run("make", "-j8", cwd=sources["libevent"])
    run("make", "install", cwd=sources["libevent"])

    run("make", "-j8", "libutf8proc.a", "CFLAGS=-O2 -mmacosx-version-min=14.0",
        cwd=sources["utf8proc"], env=env)
    (prefix / "include").mkdir(exist_ok=True)
    shutil.copy2(sources["utf8proc"] / "utf8proc.h", prefix / "include/utf8proc.h")
    shutil.copy2(sources["utf8proc"] / "libutf8proc.a", prefix / "lib/libutf8proc.a")

    tmux_env = env.copy()
    tmux_env.update(CPPFLAGS=f"-I{prefix}/include", LDFLAGS=f"-L{prefix}/lib -mmacosx-version-min=14.0",
                    LIBUTF8PROC_CFLAGS=f"-I{prefix}/include",
                    LIBUTF8PROC_LIBS=f"{prefix}/lib/libutf8proc.a")
    run(str(sources["tmux"] / "configure"), f"--prefix={prefix}", "--enable-utf8proc",
        cwd=sources["tmux"], env=tmux_env)
    run("make", "-j8", cwd=sources["tmux"])
    run("make", "install", cwd=sources["tmux"])

    cmake_build(sources["libuv"], work / "libuv-build", prefix,
                "-DLIBUV_BUILD_SHARED=OFF", "-DLIBUV_BUILD_TESTS=OFF", "-DLIBUV_BUILD_BENCH=OFF")
    cmake_build(sources["json-c"], work / "json-c-build", prefix,
                "-DBUILD_SHARED_LIBS=OFF", "-DBUILD_TESTING=OFF")
    cmake_build(sources["libwebsockets"], work / "lws-build", prefix,
                "-DLWS_WITH_SHARED=OFF", "-DLWS_WITH_STATIC=ON", "-DLWS_WITH_LIBUV=ON",
                "-DLWS_WITH_SSL=OFF", "-DLWS_WITH_HTTP2=OFF", "-DLWS_WITHOUT_TESTAPPS=ON",
                "-DLWS_WITHOUT_CLIENT=ON", f"-DLIBUV_INCLUDE_DIRS={prefix}/include",
                f"-DLIBUV_LIBRARIES={prefix}/lib/libuv.a")
    cmake_build(sources["ttyd"], work / "ttyd-build", prefix,
                f"-DLIBUV_INCLUDE_DIR={prefix}/include", f"-DLIBUV_LIBRARY={prefix}/lib/libuv.a",
                f"-DJSON-C_INCLUDE_DIR={prefix}/include/json-c",
                f"-DJSON-C_LIBRARY={prefix}/lib/libjson-c.a")
    return prefix


def audit_macho(root: Path) -> None:
    macho_magic = {b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"}
    candidates = [path for path in root.rglob("*") if path.is_file()
                  and path.open("rb").read(4) in macho_magic]
    if len(candidates) < 6:
        raise ValueError("the tool payload is missing a required Mach-O binary")
    for path in candidates:
        build = subprocess.check_output(["/usr/bin/otool", "-l", str(path)], text=True)
        minimums = re.findall(r"\bminos (\d+)\.(\d+)\b", build)
        if not minimums or any((int(major), int(minor)) > (14, 0) for major, minor in minimums):
            raise ValueError(f"unsupported macOS deployment target: {path.relative_to(root)}")
        deps = subprocess.check_output(["/usr/bin/otool", "-L", str(path)], text=True)
        for line in deps.splitlines():
            if not line.startswith("\t"):
                continue
            dependency = line.strip().split(" (compatibility", 1)[0]
            if dependency.startswith(("/usr/lib/", "/System/Library/")):
                continue
            if dependency == "@rpath/imsg-bridge-helper.dylib" and path.name == "imsg":
                continue
            if dependency == f"@rpath/{path.name}" and path.suffix == ".dylib":
                continue
            if dependency.startswith("@loader_path/") and (path.parent / dependency[13:]).is_file():
                continue
            raise ValueError(f"external Mach-O dependency for {path.relative_to(root)}: {dependency}")
        run("/usr/bin/codesign", "--verify", "--strict", str(path))


def package(work: Path, out: Path, sources: dict[str, Path], prefix: Path) -> None:
    out.mkdir(parents=True)
    bins = out / "bin"
    libs = out / "lib"
    licenses = out / "licenses"
    for folder in (bins, libs, licenses):
        folder.mkdir()
    python = sources["python"]
    shutil.copy2(python / "bin/python3.11", bins / "python3")
    shutil.copytree(python / "lib/python3.11", libs / "python3.11",
                    ignore=shutil.ignore_patterns("site-packages", "test", "__pycache__", "*.pyc",
                                                   "_tkinter*", "tkinter", "turtledemo", "idlelib", "turtle.py"))
    shutil.copy2(prefix / "bin/tmux", bins / "tmux")
    shutil.copy2(prefix / "bin/ttyd", bins / "ttyd")
    node = sources["node"]
    shutil.copy2(node / "bin/node", bins / "node")
    shutil.copytree(node / "lib/node_modules/npm", libs / "node_modules/npm")
    (bins / "npm").write_text(
        '#!/bin/sh\nHERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
        'exec "$HERE/node" "$HERE/../lib/node_modules/npm/bin/npm-cli.js" "$@"\n', encoding="utf-8")
    imsg = sources["imsg"]
    for name in ("imsg", "imsg-bridge-helper.dylib"):
        shutil.copy2(imsg / name, bins / name)
    for name in ("SQLite.swift_SQLite.bundle", "PhoneNumberKit_PhoneNumberKit.bundle"):
        shutil.copytree(imsg / name, bins / name)

    notice = {
        "python": (python / "lib/python3.11/LICENSE.txt"),
        "node": (node / "LICENSE"),
        "imsg": sources["imsg-license"],
        "tmux": (sources["tmux"] / "COPYING"),
        "ttyd": (sources["ttyd"] / "LICENSE"),
        "libevent": (sources["libevent"] / "LICENSE"),
        "utf8proc": (sources["utf8proc"] / "LICENSE.md"),
        "libuv": (sources["libuv"] / "LICENSE"),
        "json-c": (sources["json-c"] / "COPYING"),
        "libwebsockets": (sources["libwebsockets"] / "LICENSE"),
    }
    for name, source in notice.items():
        shutil.copy2(source, licenses / f"{name}.txt")
    provenance = {name: {"url": value[0], "sha256": value[1]}
                  for name, value in ARCHIVES.items()}
    (out / "provenance.json").write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    for path in out.rglob("*"):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError(f"unsafe tool payload entry: {path.relative_to(out)}")
        if path.is_dir():
            path.chmod(0o755)
        else:
            path.chmod(0o755 if path.parent == bins or path.suffix in (".so", ".dylib") else 0o644)
    out.chmod(0o755)
    audit_macho(out)
    expected = {
        "python3": "Python 3.11.16", "tmux": "tmux 3.6a", "ttyd": "ttyd version 1.7.7",
        "node": "v24.21.0", "npm": "11.19.0", "imsg": "0.15.9",
    }
    args = {"python3": ["-c", "import sqlite3,ssl; print('Python 3.11.16')"],
            "tmux": ["-V"], "ttyd": ["--version"], "node": ["--version"],
            "npm": ["--version"], "imsg": ["--version"]}
    for name, version in expected.items():
        output = subprocess.check_output([str(bins / name), *args[name]], text=True).strip()
        if not output.startswith(version):
            raise ValueError(f"{name} smoke check failed: {output[:80]}")
    files = sorted(path for path in out.rglob("*") if path.is_file())
    lines = []
    for path in files:
        relative = path.relative_to(out).as_posix()
        if any(ord(c) < 33 or ord(c) == 127 or c == "\\" for c in relative):
            raise ValueError(f"unsafe tool payload path: {relative}")
        lines.append(f"{sha(path)}  {relative}\n")
    manifest = out / "manifest.sha256"
    manifest.write_text("".join(lines), encoding="ascii")
    manifest.chmod(0o644)


def main() -> None:
    if len(sys.argv) != 2 or sys.platform != "darwin" or os.uname().machine != "arm64":
        raise SystemExit("usage on an Apple Silicon Mac: build-toolchain.py OUTPUT_DIRECTORY")
    out = Path(sys.argv[1]).expanduser().absolute()
    if out.exists() or out.is_symlink():
        raise SystemExit("toolchain output already exists")
    for tool in ("cmake", "make", "clang", "curl", "otool", "codesign"):
        if not shutil.which(tool):
            raise SystemExit(f"release build requires {tool}")
    with tempfile.TemporaryDirectory(prefix="wb-toolchain-build-") as temp:
        work = Path(temp)
        sources = {name: fetch(work, name) for name in ARCHIVES}
        prefix = compile_tools(work, sources)
        package(work, out, sources, prefix)
    print(f"verified private tool payload: {out}")


if __name__ == "__main__":
    main()
