#!/usr/bin/env python3
"""Build the static GitHub Pages payload for os.wideband.ai."""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil

from release_feed import validate_feed


def main() -> int:
    root = pathlib.Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()

    feed_source = root / "updates" / "version.json"
    feed = json.loads(feed_source.read_text(encoding="utf-8"))
    validate_feed(feed)

    output = args.output.resolve()
    if output == pathlib.Path("/") or output == root:
        raise ValueError("refusing an unsafe update-site output directory")
    output.mkdir(parents=True, exist_ok=True)
    (output / "version").write_bytes(feed_source.read_bytes())
    (output / "version.json").write_bytes(feed_source.read_bytes())
    (output / ".nojekyll").write_text("", encoding="utf-8")
    shutil.copy2(root / "updates" / "index.html", output / "index.html")
    shutil.copy2(root / "installer" / "wideband-mark.png", output / "wideband-mark.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
