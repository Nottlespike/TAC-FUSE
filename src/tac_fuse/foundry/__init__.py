"""Maven Smart System / Foundry API integration boundary.

This module enforces the deferred sync boundary: exports can be created
from local state while disconnected, but uploads must be gated by ONLINE
mode and credential presence. Missing Foundry or Maven configuration must
never block local operator C2.
"""

from __future__ import annotations

from tac_fuse.foundry.config import (
    DEFAULT_MAVEN_API_YAML,
    FoundryConnectionConfig,
    FoundryOAuthConfig,
    MavenFoundryConfig,
    SyncBoundaryViolation,
    assert_sync_allowed,
    can_upload,
    has_upload_credentials,
    load_maven_foundry_config,
    redacted_summary,
)

__all__ = [
    "DEFAULT_MAVEN_API_YAML",
    "FoundryConnectionConfig",
    "FoundryOAuthConfig",
    "MavenFoundryConfig",
    "SyncBoundaryViolation",
    "assert_sync_allowed",
    "can_upload",
    "has_upload_credentials",
    "load_maven_foundry_config",
    "redacted_summary",
]
