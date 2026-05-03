"""Configuration loader for Maven Smart System / Foundry API integration.

Tokens are never serialised to the returned objects; all auth material is
redacted in :func:`redacted_summary`.  Env-var values take precedence over
the YAML file so that credentials can be injected at runtime without touching
the disk.

Example env-var layout::

    FOUNDRY_HOSTNAME          = "https://org.palantirfoundry.com"
    FOUNDRY_TOKEN             = "pat-..."
    OAUTH_CLIENT_ID           = "client-id"
    OAUTH_CLIENT_SECRET       = "secret"
    OAUTH_TOKEN_URL           = "https://org.palantirfoundry.com/oauth/token"
    MAVEN_ONTOLOGY_NAME       = "maven"
    FOUNDRY_MISSION_DATASET_RID   = "ri-foundry-dataset-..."
    FOUNDRY_EVENTS_DATASET_RID    = "ri-foundry-dataset-..."
    FOUNDRY_EVENTS_BRANCH         = "main"
    FOUNDRY_MEDIA_SET_RID         = "ri-foundry-media-set-..."
    MAVEN_COMMAND_ACTION          = "MavenCommand"
    MAVEN_STATUS_ACTION           = "MavenStatus"
    FOUNDRY_REQUESTED_SCOPES       = (
        "datasets:write,streams:write,media-sets:write,ontology:read,ontology:write"
    )

"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

# ── Package-relative default config path ─────────────────────────────────────
_CONFIG_NAME = "maven_api.yaml"
_PACKAGE_ROOT = Path(__file__).resolve().parents[3]  # project root (…/TAC-FUSE)
DEFAULT_MAVEN_API_YAML = _PACKAGE_ROOT / "configs" / "foundry" / _CONFIG_NAME
DEFAULT_REQUESTED_SCOPES = (
    "datasets:write",
    "streams:write",
    "media-sets:write",
    "ontology:read",
    "ontology:write",
)


# ── Sub-models ────────────────────────────────────────────────────────────────


class FoundryOAuthConfig(BaseModel, frozen=True):
    """Optional OAuth 2.0 client-credentials block."""

    client_id: str = Field(description="OAuth client identifier")
    client_secret: str = Field(description="OAuth client secret")
    token_url: str = Field(description="Full URL to the OAuth token endpoint")


class FoundryConnectionConfig(BaseModel, frozen=True):
    """Connection and credentials sub-tree."""

    hostname: str = Field(description="Foundry instance base URL (no trailing slash)")
    token: str = Field(description="Personal access token (PAT)")
    oauth: FoundryOAuthConfig | None = Field(
        default=None,
        description="OAuth client-credentials (omit when using PAT)",
    )


class MavenFoundryConfig(BaseModel, frozen=True):
    """Root configuration object for Maven / Foundry integration.

    All auth secrets are held as plain strings so that callers can pass them
    to HTTP libraries; callers must treat them as sensitive and must never log
    them in plain text.
    """

    # ── Connection ────────────────────────────────────────────────────────────
    connection: FoundryConnectionConfig

    # ── Maven ontology ───────────────────────────────────────────────────────
    ontology_name: str = Field(
        description="Ontology name (e.g. 'maven') or RID for action calls"
    )

    # ── Datasets ─────────────────────────────────────────────────────────────
    mission_dataset_rid: str = Field(
        description="Foundry dataset RID for serialised mission packets"
    )
    events_dataset_rid: str = Field(
        description="Foundry dataset RID for live event records"
    )
    events_branch: str = Field(
        default="main",
        description="Branch on the events dataset",
    )
    media_set_rid: str = Field(
        description="Foundry media-set RID for POV imagery"
    )

    # ── Ontology actions ─────────────────────────────────────────────────────
    command_action: str | None = Field(
        default=None,
        description="Ontology action API name for command handoff",
    )
    status_action: str | None = Field(
        default=None,
        description="Ontology action API name for status handoff",
    )

    # ── Scopes ───────────────────────────────────────────────────────────────
    requested_scopes: tuple[str, ...] = Field(
        default=DEFAULT_REQUESTED_SCOPES,
        description="OAuth scopes requested at token exchange",
    )


# ── Redaction ─────────────────────────────────────────────────────────────────


def redacted_summary(config: MavenFoundryConfig) -> dict[str, Any]:
    """Return a human-readable dict of the loaded config with all secrets replaced.

    The token field is replaced with the string ``<REDACTED>``.  OAuth secrets
    are also redacted.  No other Pydantic validation is performed.
    """
    conn = config.connection
    oauth_summary: dict[str, str] | None = None
    if conn.oauth:
        oauth_summary = {
            "client_id": conn.oauth.client_id,
            "client_secret": "<REDACTED>",
            "token_url": conn.oauth.token_url,
        }

    return {
        "connection": {
            "hostname": conn.hostname,
            "token": "<REDACTED>",
            "oauth": oauth_summary,
        },
        "ontology_name": config.ontology_name,
        "mission_dataset_rid": config.mission_dataset_rid,
        "events_dataset_rid": config.events_dataset_rid,
        "events_branch": config.events_branch,
        "media_set_rid": config.media_set_rid,
        "command_action": config.command_action,
        "status_action": config.status_action,
        "requested_scopes": list(config.requested_scopes),
    }


# ── Loader ──────────────────────────────────────────────────────────────────────


def _coerce_scopes(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(s.strip() for s in value.split(",") if s.strip())
    if isinstance(value, (list, tuple)):
        return tuple(str(s) for s in value)
    return ()


def _env_list(key: str, sep: str = ",") -> tuple[str, ...]:
    raw = os.environ.get(key, "")
    if not raw:
        return ()
    return tuple(s.strip() for s in raw.split(sep) if s.strip())


def load_maven_foundry_config(
    config_path: Path | str | None = None,
    *,
    _env_prefix: str = "",
    strict: bool = False,
) -> MavenFoundryConfig | None:
    """Load Maven Foundry configuration, starting from YAML then overlaying env vars.

    Env vars take precedence.  Recognised variables (all optional when a YAML file
    is provided):

    - ``FOUNDRY_HOSTNAME``
    - ``FOUNDRY_TOKEN``
    - ``OAUTH_CLIENT_ID``
    - ``OAUTH_CLIENT_SECRET``
    - ``OAUTH_TOKEN_URL``
    - ``MAVEN_ONTOLOGY_NAME``
    - ``FOUNDRY_MISSION_DATASET_RID``
    - ``FOUNDRY_EVENTS_DATASET_RID``
    - ``FOUNDRY_EVENTS_BRANCH``
    - ``FOUNDRY_MEDIA_SET_RID``
    - ``MAVEN_COMMAND_ACTION``
    - ``MAVEN_STATUS_ACTION``
    - ``FOUNDRY_REQUESTED_SCOPES``  (comma-separated)

    When *strict* is ``False`` (the default), missing hostname or auth
    credentials produce a partial config instead of raising -- this lets
    local C2 operate when Foundry/Maven are not configured.  When *strict*
    is ``True``, the historical behaviour is preserved and a ``ValueError``
    is raised if required fields are absent.

    Args:
        config_path: Path to ``maven_api.yaml``.  When ``None`` the package
            default (``configs/foundry/maven_api.yaml``) is used.
        strict: If ``True``, raise ``ValueError`` instead of returning a partial
            config.

    Returns:
        A fully-populated :class:`MavenFoundryConfig` instance, or ``None`` when
        neither hostname nor any auth material is available (regardless of *strict*).

    Raises:
        FileNotFoundError: when the config file does not exist and *strict* is True.
        ValueError: when neither the config file nor env vars provide a required field
            and *strict* is True.
    """
    path = Path(config_path) if config_path else DEFAULT_MAVEN_API_YAML
    yaml_data: dict[str, Any] = {}
    if path.exists():
        yaml_data = yaml.safe_load(path.read_text()) or {}

    # --- OAuth sub-block helpers -----------------------------------------------

    def _oauth(key: str, yaml_key: str | None = None) -> str:
        """Return env-var value or value from yaml block."""
        env_val = os.environ.get(f"{_env_prefix}{key}", "")
        if env_val:
            return env_val
        oauth_block = yaml_data.get("oauth") or {}
        return str(oauth_block.get(yaml_key or key, ""))

    # --- Top-level helpers ---------------------------------------------------
    def _v(env_key: str, yaml_key: str | None = None, default: Any = "") -> Any:
        env_val = os.environ.get(f"{_env_prefix}{env_key}", "")
        if env_val:
            return env_val
        return yaml_data.get(yaml_key or env_key, default)

    # Build connection block ---------------------------------------------------
    hostname = _v("FOUNDRY_HOSTNAME", "foundry_hostname")
    token = _v("FOUNDRY_TOKEN", "foundry_token")

    oauth_client_id = _oauth("OAUTH_CLIENT_ID", "client_id")
    oauth_client_secret = _oauth("OAUTH_CLIENT_SECRET", "client_secret")
    oauth_token_url = _oauth("OAUTH_TOKEN_URL", "token_url")

    connection_oauth: FoundryOAuthConfig | None = None
    has_partial_oauth = any((oauth_client_id, oauth_client_secret, oauth_token_url))
    if has_partial_oauth:
        if oauth_client_id and oauth_client_secret and oauth_token_url:
            connection_oauth = FoundryOAuthConfig(
                client_id=oauth_client_id,
                client_secret=oauth_client_secret,
                token_url=oauth_token_url,
            )
        elif strict:
            raise ValueError(
                "All three OAUTH_CLIENT_ID / OAUTH_CLIENT_SECRET / "
                "OAUTH_TOKEN_URL must be set together, or none at all."
            )
        # non-strict: ignore partial OAuth so local C2 stays operational

    # Early return: nothing useful to sync with at all.
    if not hostname and not token and not connection_oauth:
        if strict:
            raise ValueError(
                "No Foundry hostname, token, or OAuth credentials found.  "
                "Set FOUNDRY_HOSTNAME / FOUNDRY_TOKEN in the environment or "
                "provide a YAML config file."
            )
        return None

    connection = FoundryConnectionConfig(
        hostname=str(hostname) if hostname else "",
        token=str(token) if token else "",
        oauth=connection_oauth,
    )

    # Build scopes -------------------------------------------------------------
    scopes_raw = _v("FOUNDRY_REQUESTED_SCOPES", "foundry_requested_scopes", None)
    scopes = (
        _coerce_scopes(scopes_raw)
        if scopes_raw not in (None, "")
        else DEFAULT_REQUESTED_SCOPES
    )
    if not scopes:
        scopes = DEFAULT_REQUESTED_SCOPES

    config = MavenFoundryConfig(
        connection=connection,
        ontology_name=str(_v("MAVEN_ONTOLOGY_NAME", "maven_ontology_name", "")),
        mission_dataset_rid=str(
            _v("FOUNDRY_MISSION_DATASET_RID", "foundry_mission_dataset_rid", "")
        ),
        events_dataset_rid=str(_v("FOUNDRY_EVENTS_DATASET_RID", "foundry_events_dataset_rid", "")),
        events_branch=str(_v("FOUNDRY_EVENTS_BRANCH", "foundry_events_branch", "main")),
        media_set_rid=str(_v("FOUNDRY_MEDIA_SET_RID", "foundry_media_set_rid", "")),
        command_action=str(_v("MAVEN_COMMAND_ACTION", "maven_command_action")) or None,
        status_action=str(_v("MAVEN_STATUS_ACTION", "maven_status_action")) or None,
        requested_scopes=scopes,
    )

    # Validate that at least hostname / token are present --------------------
    if strict and not connection.hostname:
        raise ValueError(
            "Foundry hostname is required.  Set FOUNDRY_HOSTNAME in the environment "
            "or 'foundry_hostname' in the YAML config."
        )
    if strict and not connection.token and not connection.oauth:
        raise ValueError(
            "At least one auth mechanism is required.  Provide FOUNDRY_TOKEN "
            "(personal access token) or all three OAUTH_* variables."
        )

    return config


def has_upload_credentials(config: MavenFoundryConfig | None) -> bool:
    """Return ``True`` when a config holds enough to attempt an upload.

    Requires a non-empty hostname plus either a PAT token or complete OAuth
    credentials.
    """
    if config is None:
        return False
    conn = config.connection
    if not conn.hostname:
        return False
    if conn.token:
        return True
    if conn.oauth is not None:
        return bool(conn.oauth.client_id and conn.oauth.client_secret and conn.oauth.token_url)
    return False


def can_upload(
    config: MavenFoundryConfig | None,
    *,
    sync_allowed: bool,
) -> bool:
    """Unified gate for any Foundry/Maven upload.

    Uploads require **both** connectivity-level permission (caller passes
    ``sync_allowed=controller.is_external_sync_allowed()``) and valid upload
    credentials in the config.

    Returns ``False`` when:
    - *sync_allowed* is ``False`` (OFFLINE / DEGRADED mode)
    - *config* is ``None`` (no Foundry/Maven config at all)
    - *config* lacks hostname or auth credentials

    This function never raises and never performs I/O, making it safe to call
    from any local C2 code path.
    """
    if not sync_allowed:
        return False
    return has_upload_credentials(config)


class SyncBoundaryViolation(RuntimeError):
    """Raised when code attempts to cross the deferred sync boundary.

    This is the hard gate: any code path that tries to upload to Foundry/Maven
    **must** call :func:`assert_sync_allowed` first.  The exception makes it
    impossible to silently bypass the boundary — a failed gate is always a
    loud, testable failure.

    Missing Foundry or Maven configuration must never block local operator C2.
    Local exports (``foundry_export``) are always allowed because they read
    from persisted local state and produce offline artifacts.
    """


def assert_sync_allowed(
    config: MavenFoundryConfig | None,
    *,
    sync_allowed: bool,
) -> None:
    """Hard gate that raises :class:`SyncBoundaryViolation` when upload is blocked.

    Every code path that attempts an upload to Foundry or Maven **must** call
    this function before performing any network I/O.  The function raises
    instead of returning a bool so that a boundary violation is always
    immediately visible and testable.

    This function never performs I/O and is safe to call from any code path.

    Args:
        config: Loaded Maven/Foundry config (may be ``None``).
        sync_allowed: ``True`` when the connectivity controller reports
            ONLINE mode (``controller.is_external_sync_allowed()``).

    Raises:
        SyncBoundaryViolation: when the upload gate is closed.
    """
    if not sync_allowed:
        raise SyncBoundaryViolation(
            "Upload blocked: connectivity is not ONLINE. "
            "Exports can be created from local state while disconnected, "
            "but uploads must be gated by ONLINE mode."
        )
    if not has_upload_credentials(config):
        if config is None:
            raise SyncBoundaryViolation(
                "Upload blocked: no Maven/Foundry configuration present. "
                "Missing Foundry or Maven configuration must never block "
                "local operator C2 — exports work from local state."
            )
        conn = config.connection
        if not conn.hostname:
            raise SyncBoundaryViolation(
                "Upload blocked: Foundry hostname is empty in config. "
                "Local C2 and exports remain fully operational."
            )
        raise SyncBoundaryViolation(
            "Upload blocked: Foundry/Maven credentials incomplete. "
            "Provide a personal access token (FOUNDRY_TOKEN) or complete "
            "OAuth credentials (OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET, "
            "OAUTH_TOKEN_URL). Local C2 and exports remain fully operational."
        )
