#!/usr/bin/env python3
"""Validate a client JSON profile and render the private shell identity file."""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path


FIELDS = (
    "CLIENT_NAME",
    "ORG",
    "BRAND",
    "MARK",
    "GH_USER",
    "GIT_EMAIL",
    "OPERATOR_PHONE",
    "WORK_REPO",
    "GRAPH_PACK",
)


def fail(message: str) -> None:
    raise SystemExit(f"client profile: {message}")


def clean(name: str, value: object) -> str:
    if not isinstance(value, str):
        fail(f"{name} must be a string")
    result = value.strip()
    if (not result and name != "OPERATOR_PHONE") or len(result) > 300 or any(ord(char) < 32 for char in result):
        fail(f"{name} must be a valid single-line value")
    return result


def validate(values: dict[str, str]) -> None:
    rules = {
        "ORG": r"[a-z][a-z0-9-]{0,30}",
        "GH_USER": r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?",
        "GIT_EMAIL": r"[^\s@]+@[^\s@]+\.[^\s@]+",
        "OPERATOR_PHONE": r"\+[1-9][0-9]{7,14}",
        "GRAPH_PACK": r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}",
    }
    for name, pattern in rules.items():
        if name == "OPERATOR_PHONE" and not values[name]:
            continue
        if not re.fullmatch(pattern, values[name]):
            fail(f"{name} is invalid")
    if "--" in values["GH_USER"]:
        fail("GH_USER cannot contain consecutive hyphens")
    if any(char.isspace() for char in values["WORK_REPO"]):
        fail("WORK_REPO cannot contain whitespace")
    if len(values["BRAND"]) > 80:
        fail("BRAND must be at most 80 characters")
    if len(values["MARK"]) > 4 or any(char.isspace() for char in values["MARK"]):
        fail("MARK must be one visible glyph")


def main() -> None:
    if len(sys.argv) != 3:
        fail("usage: render-profile.py INPUT.json OUTPUT.env")
    source = Path(sys.argv[1]).expanduser().resolve()
    destination = Path(sys.argv[2]).expanduser().resolve()
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(str(exc))
    if not isinstance(raw, dict):
        fail("top-level JSON must be an object")
    missing = [name for name in FIELDS if name not in raw and name != "OPERATOR_PHONE"]
    if missing:
        fail(f"missing fields: {', '.join(missing)}")
    unknown = sorted(set(raw) - set(FIELDS))
    if unknown:
        fail(f"unknown fields: {', '.join(unknown)}")
    values = {name: clean(name, raw.get(name, "")) for name in FIELDS}
    validate(values)
    rendered = ["# Personalized by Wideband Setup. Private to the intended client."]
    rendered += [f"export {name}={shlex.quote(values[name])}" for name in FIELDS]
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write("\n".join(rendered) + "\n")
    os.chmod(destination, 0o600)
    print(f"Personalized for {values['CLIENT_NAME']} · {values['BRAND']}")


if __name__ == "__main__":
    main()
