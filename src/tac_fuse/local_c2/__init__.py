"""Local C2 authority layer for disconnected hardened-laptop operations.

This package owns the state contract that lets a hardened laptop or backpack kit
continue issuing operator commands while cut off from internet, higher command,
and enterprise services.  External sync may stage/export operator intent, but it
must not be required for local command acceptance or replay.

COMMANDS ACCEPTED LOCALLY (all five work in OFFLINE / DEGRADED / ONLINE):
    Resume, Patrol, Return, Hold, Abort

TRACK MANAGEMENT:
    Alpha, Bravo, Charlie, and Delta emit local classification/prioritization
    cues.  The laptop creates persistent tracks with source attribution and
    stale-track handling.

SYNC GATE:
    External sync is gated behind ONLINE connectivity.  In OFFLINE and DEGRADED
    modes, commands are accepted locally and queued for deferred sync.
"""

from tac_fuse.local_c2.commands import (
    C2_COMMAND_OPS,
    C2Command,
    C2CommandReceipt,
    C2CommandStatus,
    LocalC2Authority,
    UnknownCommandError,
    issue_c2_command,
)
from tac_fuse.local_c2.sync_gate import (
    SyncGate,
    SyncGateStatus,
    flush_sync_queue,
    prepare_sync_payload,
)
from tac_fuse.local_c2.tracks import (
    AssetTrackCue,
    SourceAttribution,
    TrackAuthority,
    TrackStalenessPolicy,
)

__all__ = [
    "C2_COMMAND_OPS",
    "C2Command",
    "C2CommandReceipt",
    "C2CommandStatus",
    "LocalC2Authority",
    "AssetTrackCue",
    "SourceAttribution",
    "SyncGate",
    "SyncGateStatus",
    "TrackAuthority",
    "TrackStalenessPolicy",
    "UnknownCommandError",
    "flush_sync_queue",
    "issue_c2_command",
    "prepare_sync_payload",
]
