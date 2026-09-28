"""Read-only, VM-local Fleetdeck terminal map.

The installer copies this package beside its customer portal.  It has no
write route, ttyd process, or dependency on the operator's Fleetdeck files.
"""

from .reader import FleetMapCache, SnapshotError, validate_snapshot

__all__ = ["FleetMapCache", "SnapshotError", "validate_snapshot"]
