"""Shared configuration paths for the tmux standard and fleet tools."""

from __future__ import annotations

import os
from pathlib import Path


def resolve_sessions_conf(env: dict[str, str] | None = None, home: Path | None = None) -> Path:
    """Resolve the session standard without changing any source file.

    An explicit file wins, then tm-standard's configurable directory, then the
    path seeded by the wb-setup installer on a fresh machine.
    """
    env = os.environ if env is None else env
    home = Path.home() if home is None else Path(home)
    explicit = env.get("TM_SESSIONS_CONF", "").strip()
    if explicit:
        return Path(os.path.expandvars(explicit)).expanduser()
    config_dir = env.get("TM_CONFIG_DIR", "").strip()
    if config_dir:
        return Path(os.path.expandvars(config_dir)).expanduser() / "config" / "sessions.conf"
    return home / ".config" / "tmux-command-center" / "config" / "sessions.conf"
