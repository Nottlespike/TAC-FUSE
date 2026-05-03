"""Tests for Maven / Foundry API configuration boundary.

All tests use fake values and make zero network calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from tac_fuse.foundry.config import (
    DEFAULT_MAVEN_API_YAML,
    FoundryConnectionConfig,
    FoundryOAuthConfig,
    MavenFoundryConfig,
    can_upload,
    has_upload_credentials,
    load_maven_foundry_config,
    redacted_summary,
)

# -- Fixtures -------------------------------------------------------------------

FAKE_ENV = {
    "FOUNDRY_HOSTNAME": "https://fake-foundry.example.com",
    "FOUNDRY_TOKEN": "pat-fake-token-00000000",
    "MAVEN_ONTOLOGY_NAME": "maven-test",
    "FOUNDRY_MISSION_DATASET_RID": "ri.foundry.main.dataset.00000000-aaaa-bbbb-cccc-dddddddddddd",
    "FOUNDRY_EVENTS_DATASET_RID": "ri.foundry.main.dataset.00000000-eeee-ffff-gggg-hhhhhhhhhhhh",
    "FOUNDRY_EVENTS_BRANCH": "staging",
    "FOUNDRY_MEDIA_SET_RID": "ri.foundry.main.media-set.00000000-iiii-jjjj-kkkk-llllllllllll",
    "MAVEN_COMMAND_ACTION": "MavenTestCommand",
    "MAVEN_STATUS_ACTION": "MavenTestStatus",
    "FOUNDRY_REQUESTED_SCOPES": "datasets:write,streams:write,ontology:read",
}


@pytest.fixture()
def fake_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Inject fake env vars for every test in this module."""
    for key, val in FAKE_ENV.items():
        monkeypatch.setenv(key, val)
    return FAKE_ENV


def _minimal_yaml(tmp_path: Path) -> Path:
    """Write a minimal YAML config file and return its path."""
    data = {
        "foundry_hostname": "https://yaml-foundry.example.com",
        "foundry_token": "pat-yaml-token-11111111",
        "maven_ontology_name": "maven-yaml",
        "foundry_mission_dataset_rid": "ri.foundry.main.dataset.yyyy-aaaa-bbbb-cccc-dddddddddddd",
        "foundry_events_dataset_rid": "ri.foundry.main.dataset.yyyy-eeee-ffff-gggg-hhhhhhhhhhhh",
        "foundry_events_branch": "yaml-branch",
        "foundry_media_set_rid": "ri.foundry.main.media-set.yyyy-iiii-jjjj-kkkk-llllllllllll",
    }
    path = tmp_path / "maven_api.yaml"
    path.write_text(yaml.dump(data, sort_keys=True))
    return path


def _yaml_with_oauth(tmp_path: Path) -> Path:
    """Write a YAML config that includes OAuth credentials."""
    data = {
        "foundry_hostname": "https://oauth-foundry.example.com",
        "foundry_token": "",
        "oauth": {
            "client_id": "fake-client-id",
            "client_secret": "fake-client-secret",
            "token_url": "https://oauth-foundry.example.com/oauth/token",
        },
        "maven_ontology_name": "maven-oauth",
        "foundry_mission_dataset_rid": "ri.foundry.main.dataset.oooo-aaaa-bbbb-cccc-dddddddddddd",
        "foundry_events_dataset_rid": "ri.foundry.main.dataset.oooo-eeee-ffff-gggg-hhhhhhhhhhhh",
        "foundry_media_set_rid": "ri.foundry.main.media-set.oooo-iiii-jjjj-kkkk-llllllllllll",
    }
    path = tmp_path / "maven_api_oauth.yaml"
    path.write_text(yaml.dump(data, sort_keys=True))
    return path


# -- Config model tests ---------------------------------------------------------


class TestFoundryOAuthConfig:
    def test_construction(self) -> None:
        cfg = FoundryOAuthConfig(
            client_id="cid",
            client_secret="csecret",
            token_url="https://example.com/oauth/token",
        )
        assert cfg.client_id == "cid"
        assert cfg.client_secret == "csecret"
        assert cfg.token_url == "https://example.com/oauth/token"

    def test_frozen(self) -> None:
        cfg = FoundryOAuthConfig(
            client_id="cid",
            client_secret="csecret",
            token_url="https://example.com/oauth/token",
        )
        with pytest.raises((TypeError, ValueError)):
            cfg.client_id = "changed"  # type: ignore[misc]


class TestFoundryConnectionConfig:
    def test_pat_only(self) -> None:
        cfg = FoundryConnectionConfig(hostname="https://h", token="t")
        assert cfg.oauth is None

    def test_with_oauth(self) -> None:
        oauth = FoundryOAuthConfig(
            client_id="cid", client_secret="csecret", token_url="https://t"
        )
        cfg = FoundryConnectionConfig(hostname="https://h", token="t", oauth=oauth)
        assert cfg.oauth is not None
        assert cfg.oauth.client_id == "cid"


class TestMavenFoundryConfig:
    def _make(self, **overrides: Any) -> MavenFoundryConfig:
        defaults: dict[str, Any] = {
            "connection": FoundryConnectionConfig(
                hostname="https://h", token="t"
            ),
            "ontology_name": "maven",
            "mission_dataset_rid": "ri-ds-1",
            "events_dataset_rid": "ri-ds-2",
            "media_set_rid": "ri-ms-1",
        }
        defaults.update(overrides)
        return MavenFoundryConfig(**defaults)

    def test_defaults(self) -> None:
        cfg = self._make()
        assert cfg.events_branch == "main"
        assert cfg.command_action is None
        assert cfg.status_action is None
        assert "datasets:write" in cfg.requested_scopes

    def test_optional_actions(self) -> None:
        cfg = self._make(command_action="CmdAct", status_action="StatAct")
        assert cfg.command_action == "CmdAct"
        assert cfg.status_action == "StatAct"

    def test_frozen(self) -> None:
        cfg = self._make()
        with pytest.raises((TypeError, ValueError)):
            cfg.ontology_name = "changed"  # type: ignore[misc]


# -- Redaction tests -------------------------------------------------------------


class TestRedactedSummary:
    def test_token_redacted(self) -> None:
        cfg = MavenFoundryConfig(
            connection=FoundryConnectionConfig(
                hostname="https://h", token="super-secret-token"
            ),
            ontology_name="maven",
            mission_dataset_rid="ri-ds-1",
            events_dataset_rid="ri-ds-2",
            media_set_rid="ri-ms-1",
        )
        summary = redacted_summary(cfg)
        assert summary["connection"]["token"] == "<REDACTED>"
        summary_json = json.dumps(summary)
        assert "super-secret-token" not in summary_json

    def test_oauth_secret_redacted(self) -> None:
        oauth = FoundryOAuthConfig(
            client_id="visible-id",
            client_secret="super-secret-oauth",
            token_url="https://oauth.example.com/token",
        )
        cfg = MavenFoundryConfig(
            connection=FoundryConnectionConfig(
                hostname="https://h", token="t", oauth=oauth
            ),
            ontology_name="maven",
            mission_dataset_rid="ri-ds-1",
            events_dataset_rid="ri-ds-2",
            media_set_rid="ri-ms-1",
        )
        summary = redacted_summary(cfg)
        assert summary["connection"]["oauth"]["client_id"] == "visible-id"
        assert summary["connection"]["oauth"]["client_secret"] == "<REDACTED>"
        summary_json = json.dumps(summary)
        assert "super-secret-oauth" not in summary_json

    def test_no_oauth_returns_none(self) -> None:
        cfg = MavenFoundryConfig(
            connection=FoundryConnectionConfig(hostname="https://h", token="t"),
            ontology_name="maven",
            mission_dataset_rid="ri-ds-1",
            events_dataset_rid="ri-ds-2",
            media_set_rid="ri-ms-1",
        )
        summary = redacted_summary(cfg)
        assert summary["connection"]["oauth"] is None

    def test_rids_preserved(self) -> None:
        cfg = MavenFoundryConfig(
            connection=FoundryConnectionConfig(hostname="https://h", token="t"),
            ontology_name="maven",
            mission_dataset_rid="ri-ds-1",
            events_dataset_rid="ri-ds-2",
            media_set_rid="ri-ms-1",
        )
        summary = redacted_summary(cfg)
        assert summary["mission_dataset_rid"] == "ri-ds-1"
        assert summary["events_dataset_rid"] == "ri-ds-2"
        assert summary["media_set_rid"] == "ri-ms-1"


# -- Loader tests ---------------------------------------------------------------


class TestLoadMavenFoundryConfig:
    def test_from_env(
        self, fake_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = load_maven_foundry_config(Path("/nonexistent/maven_api.yaml"))
        assert cfg.connection.hostname == FAKE_ENV["FOUNDRY_HOSTNAME"]
        assert cfg.connection.token == FAKE_ENV["FOUNDRY_TOKEN"]
        assert cfg.ontology_name == FAKE_ENV["MAVEN_ONTOLOGY_NAME"]
        assert cfg.mission_dataset_rid == FAKE_ENV["FOUNDRY_MISSION_DATASET_RID"]
        assert cfg.events_dataset_rid == FAKE_ENV["FOUNDRY_EVENTS_DATASET_RID"]
        assert cfg.events_branch == FAKE_ENV["FOUNDRY_EVENTS_BRANCH"]
        assert cfg.media_set_rid == FAKE_ENV["FOUNDRY_MEDIA_SET_RID"]
        assert cfg.command_action == FAKE_ENV["MAVEN_COMMAND_ACTION"]
        assert cfg.status_action == FAKE_ENV["MAVEN_STATUS_ACTION"]

    def test_scopes_from_env(
        self, fake_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = load_maven_foundry_config(Path("/nonexistent/maven_api.yaml"))
        assert cfg.requested_scopes == ("datasets:write", "streams:write", "ontology:read")

    def test_from_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for key in FAKE_ENV:
            monkeypatch.delenv(key, raising=False)
        yaml_path = _minimal_yaml(tmp_path)
        cfg = load_maven_foundry_config(yaml_path)
        assert cfg.connection.hostname == "https://yaml-foundry.example.com"
        assert cfg.ontology_name == "maven-yaml"
        assert cfg.events_branch == "yaml-branch"

    def test_env_overrides_yaml(
        self, tmp_path: Path, fake_env: dict[str, str]
    ) -> None:
        yaml_path = _minimal_yaml(tmp_path)
        cfg = load_maven_foundry_config(yaml_path)
        assert cfg.connection.hostname == FAKE_ENV["FOUNDRY_HOSTNAME"]
        assert cfg.ontology_name == FAKE_ENV["MAVEN_ONTOLOGY_NAME"]

    def test_yaml_oauth(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for key in FAKE_ENV:
            monkeypatch.delenv(key, raising=False)
        yaml_path = _yaml_with_oauth(tmp_path)
        monkeypatch.setenv("FOUNDRY_TOKEN", "pat-from-env")
        cfg = load_maven_foundry_config(yaml_path)
        assert cfg.connection.oauth is not None
        assert cfg.connection.oauth.client_id == "fake-client-id"
        assert cfg.connection.token == "pat-from-env"

    def test_oauth_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FOUNDRY_HOSTNAME", "https://h")
        monkeypatch.setenv("FOUNDRY_TOKEN", "")
        monkeypatch.setenv("OAUTH_CLIENT_ID", "env-cid")
        monkeypatch.setenv("OAUTH_CLIENT_SECRET", "env-csecret")
        monkeypatch.setenv("OAUTH_TOKEN_URL", "https://h/oauth/token")
        monkeypatch.setenv("MAVEN_ONTOLOGY_NAME", "maven")
        monkeypatch.setenv("FOUNDRY_MISSION_DATASET_RID", "ri-ds-1")
        monkeypatch.setenv("FOUNDRY_EVENTS_DATASET_RID", "ri-ds-2")
        monkeypatch.setenv("FOUNDRY_MEDIA_SET_RID", "ri-ms-1")
        cfg = load_maven_foundry_config(Path("/nonexistent/maven_api.yaml"))
        assert cfg.connection.oauth is not None
        assert cfg.connection.oauth.client_id == "env-cid"
        assert cfg.connection.token == ""

    def test_partial_oauth_raises_in_strict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FOUNDRY_HOSTNAME", "https://h")
        monkeypatch.setenv("FOUNDRY_TOKEN", "pat-ok")
        monkeypatch.setenv("OAUTH_CLIENT_ID", "only-id")
        monkeypatch.delenv("OAUTH_CLIENT_SECRET", raising=False)
        monkeypatch.delenv("OAUTH_TOKEN_URL", raising=False)
        monkeypatch.setenv("MAVEN_ONTOLOGY_NAME", "maven")
        monkeypatch.setenv("FOUNDRY_MISSION_DATASET_RID", "ri-ds-1")
        monkeypatch.setenv("FOUNDRY_EVENTS_DATASET_RID", "ri-ds-2")
        monkeypatch.setenv("FOUNDRY_MEDIA_SET_RID", "ri-ms-1")
        with pytest.raises(ValueError, match="All three"):
            load_maven_foundry_config(
                Path("/nonexistent/maven_api.yaml"), strict=True
            )

    def test_partial_oauth_non_strict_does_not_block_local_c2(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Partial OAuth env vars must never crash local C2 when strict=False."""
        monkeypatch.setenv("FOUNDRY_HOSTNAME", "https://h")
        monkeypatch.setenv("FOUNDRY_TOKEN", "pat-ok")
        monkeypatch.setenv("OAUTH_CLIENT_ID", "only-id")
        monkeypatch.delenv("OAUTH_CLIENT_SECRET", raising=False)
        monkeypatch.delenv("OAUTH_TOKEN_URL", raising=False)
        monkeypatch.setenv("MAVEN_ONTOLOGY_NAME", "maven")
        monkeypatch.setenv("FOUNDRY_MISSION_DATASET_RID", "ri-ds-1")
        monkeypatch.setenv("FOUNDRY_EVENTS_DATASET_RID", "ri-ds-2")
        monkeypatch.setenv("FOUNDRY_MEDIA_SET_RID", "ri-ms-1")
        # Should NOT raise -- partial OAuth is ignored gracefully
        cfg = load_maven_foundry_config(Path("/nonexistent/maven_api.yaml"))
        assert cfg is not None
        assert cfg.connection.token == "pat-ok"
        assert cfg.connection.oauth is None  # partial OAuth ignored

    def test_missing_hostname_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for key in FAKE_ENV:
            monkeypatch.delenv(key, raising=False)
        with pytest.raises(ValueError, match="hostname"):
            load_maven_foundry_config(Path("/nonexistent/maven_api.yaml"), strict=True)

    def test_missing_auth_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FOUNDRY_HOSTNAME", "https://h")
        monkeypatch.delenv("FOUNDRY_TOKEN", raising=False)
        for key in ("OAUTH_CLIENT_ID", "OAUTH_CLIENT_SECRET", "OAUTH_TOKEN_URL"):
            monkeypatch.delenv(key, raising=False)
        with pytest.raises(ValueError, match="auth mechanism"):
            load_maven_foundry_config(Path("/nonexistent/maven_api.yaml"), strict=True)

    def test_default_yaml_path(self) -> None:
        assert DEFAULT_MAVEN_API_YAML.name == "maven_api.yaml"
        assert "configs" in str(DEFAULT_MAVEN_API_YAML)

    def test_default_scopes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FOUNDRY_HOSTNAME", "https://h")
        monkeypatch.setenv("FOUNDRY_TOKEN", "t")
        monkeypatch.setenv("MAVEN_ONTOLOGY_NAME", "maven")
        monkeypatch.setenv("FOUNDRY_MISSION_DATASET_RID", "ri-ds-1")
        monkeypatch.setenv("FOUNDRY_EVENTS_DATASET_RID", "ri-ds-2")
        monkeypatch.setenv("FOUNDRY_MEDIA_SET_RID", "ri-ms-1")
        monkeypatch.delenv("FOUNDRY_REQUESTED_SCOPES", raising=False)
        cfg = load_maven_foundry_config(Path("/nonexistent/maven_api.yaml"))
        assert "datasets:write" in cfg.requested_scopes
        assert "ontology:write" in cfg.requested_scopes


# -- Upload credential gate tests -----------------------------------------------


class TestHasUploadCredentials:
    def test_none_config_returns_false(self) -> None:
        assert has_upload_credentials(None) is False

    def test_no_hostname_returns_false(self) -> None:
        cfg = MavenFoundryConfig(
            connection=FoundryConnectionConfig(hostname="", token="t"),
            ontology_name="maven",
            mission_dataset_rid="ri-ds-1",
            events_dataset_rid="ri-ds-2",
            media_set_rid="ri-ms-1",
        )
        assert has_upload_credentials(cfg) is False

    def test_hostname_plus_pat_returns_true(self) -> None:
        cfg = MavenFoundryConfig(
            connection=FoundryConnectionConfig(hostname="https://h", token="t"),
            ontology_name="maven",
            mission_dataset_rid="ri-ds-1",
            events_dataset_rid="ri-ds-2",
            media_set_rid="ri-ms-1",
        )
        assert has_upload_credentials(cfg) is True

    def test_hostname_plus_complete_oauth_returns_true(self) -> None:
        oauth = FoundryOAuthConfig(
            client_id="cid", client_secret="csecret", token_url="https://t"
        )
        cfg = MavenFoundryConfig(
            connection=FoundryConnectionConfig(hostname="https://h", token="", oauth=oauth),
            ontology_name="maven",
            mission_dataset_rid="ri-ds-1",
            events_dataset_rid="ri-ds-2",
            media_set_rid="ri-ms-1",
        )
        assert has_upload_credentials(cfg) is True

    def test_hostname_no_token_no_oauth_returns_false(self) -> None:
        cfg = MavenFoundryConfig(
            connection=FoundryConnectionConfig(hostname="https://h", token=""),
            ontology_name="maven",
            mission_dataset_rid="ri-ds-1",
            events_dataset_rid="ri-ds-2",
            media_set_rid="ri-ms-1",
        )
        assert has_upload_credentials(cfg) is False


class TestCanUpload:
    """Test the unified upload gate (connectivity + credentials)."""

    def _make_config(self) -> MavenFoundryConfig:
        return MavenFoundryConfig(
            connection=FoundryConnectionConfig(hostname="https://h", token="t"),
            ontology_name="maven",
            mission_dataset_rid="ri-ds-1",
            events_dataset_rid="ri-ds-2",
            media_set_rid="ri-ms-1",
        )

    def test_online_with_credentials_allows_upload(self) -> None:
        assert can_upload(self._make_config(), sync_allowed=True) is True

    def test_offline_blocks_upload_even_with_credentials(self) -> None:
        assert can_upload(self._make_config(), sync_allowed=False) is False

    def test_online_without_config_blocks_upload(self) -> None:
        assert can_upload(None, sync_allowed=True) is False

    def test_online_without_credentials_blocks_upload(self) -> None:
        cfg = MavenFoundryConfig(
            connection=FoundryConnectionConfig(hostname="https://h", token=""),
            ontology_name="maven",
            mission_dataset_rid="ri-ds-1",
            events_dataset_rid="ri-ds-2",
            media_set_rid="ri-ms-1",
        )
        assert can_upload(cfg, sync_allowed=True) is False

    def test_offline_without_config_blocks_upload(self) -> None:
        assert can_upload(None, sync_allowed=False) is False


class TestExportWithoutConfig:
    """Verify exports always work from local state regardless of Foundry config."""

    def test_export_works_with_no_foundry_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from tac_fuse.foundry_export import build_foundry_export
        from tac_fuse.mission_state import MissionStateStore

        # No Foundry env vars at all
        for key in FAKE_ENV:
            monkeypatch.delenv(key, raising=False)

        cfg = load_maven_foundry_config(Path("/nonexistent/maven_api.yaml"))
        assert cfg is None  # no config available
        assert has_upload_credentials(cfg) is False

        # But local C2 export still works
        store = MissionStateStore()
        store.create_task(title="Disconnected patrol")
        export = build_foundry_export(store)
        assert len(export["operator_tasks"]) == 1
        assert export["operator_tasks"][0]["title"] == "Disconnected patrol"

    def test_export_works_with_empty_hostname_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from tac_fuse.foundry_export import build_foundry_export
        from tac_fuse.mission_state import MissionStateStore

        # Only hostname, no auth
        monkeypatch.setenv("FOUNDRY_HOSTNAME", "")
        monkeypatch.delenv("FOUNDRY_TOKEN", raising=False)
        for key in FAKE_ENV:
            if key != "FOUNDRY_HOSTNAME":
                monkeypatch.delenv(key, raising=False)

        cfg = load_maven_foundry_config(Path("/nonexistent/maven_api.yaml"))
        assert cfg is None
        assert can_upload(cfg, sync_allowed=True) is False

        # Local export still works
        store = MissionStateStore()
        store.create_task(title="Air-gapped recon")
        export = build_foundry_export(store)
        assert len(export["operator_tasks"]) == 1
        assert export["operator_tasks"][0]["title"] == "Air-gapped recon"
