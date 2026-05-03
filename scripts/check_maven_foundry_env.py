"""Redacted environment check for Maven / Foundry API configuration.

Reports which configuration values are present without printing any secrets.
Exit code 0 when all required values are set; 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure the project source is importable when running the script directly.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SYS_PATH_APPEND = str(_PROJECT_ROOT / "src")
if _SYS_PATH_APPEND not in sys.path:
    sys.path.insert(0, _SYS_PATH_APPEND)

from tac_fuse.foundry.config import (  # noqa: E402
    MavenFoundryConfig,
    load_maven_foundry_config,
    redacted_summary,
)


def _presence_map(config: MavenFoundryConfig) -> dict[str, dict[str, bool | str]]:
    """Return a dict indicating presence of every config key (no secrets)."""
    conn = config.connection
    oauth_present = conn.oauth is not None

    return {
        "connection": {
            "hostname": bool(conn.hostname),
            "token": bool(conn.token),
            "oauth_present": oauth_present,
        },
        "ontology_name": bool(config.ontology_name),
        "mission_dataset_rid": bool(config.mission_dataset_rid),
        "events_dataset_rid": bool(config.events_dataset_rid),
        "events_branch": bool(config.events_branch),
        "media_set_rid": bool(config.media_set_rid),
        "command_action": bool(config.command_action),
        "status_action": bool(config.status_action),
        "requested_scopes_count": len(config.requested_scopes),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to maven_api.yaml (default: package default)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Emit machine-readable JSON instead of human output",
    )
    args = parser.parse_args(argv)

    try:
        config = load_maven_foundry_config(args.config)
    except ValueError as exc:
        print(f"CONFIGURATION ERROR: {exc}", file=sys.stderr)
        # Still report what we can by falling back to a partial check.
        _print_missing(args.json_output)
        return 1
    except FileNotFoundError as exc:
        print(f"CONFIGURATION ERROR: {exc}", file=sys.stderr)
        _print_missing(args.json_output)
        return 1

    presence = _presence_map(config)
    summary = redacted_summary(config)

    if args.json_output:
        print(json.dumps({"presence": presence, "redacted": summary}, indent=2, sort_keys=True))
    else:
        print("Maven / Foundry API environment check")
        print("=" * 40)
        _print_section("Connection", presence["connection"])
        for key in (
            "ontology_name",
            "mission_dataset_rid",
            "events_dataset_rid",
            "events_branch",
            "media_set_rid",
            "command_action",
            "status_action",
        ):
            status = "SET" if presence[key] else "MISSING"
            print(f"  {key}: {status}")
        print(f"  requested_scopes: {presence['requested_scopes_count']} scope(s)")
        print()
        print("Redacted configuration:")
        print(json.dumps(summary, indent=2, sort_keys=True))

    # All required fields present?
    required_ok = (
        presence["connection"]["hostname"]
        and (presence["connection"]["token"] or presence["connection"]["oauth_present"])
        and presence["ontology_name"]
        and presence["mission_dataset_rid"]
        and presence["events_dataset_rid"]
        and presence["media_set_rid"]
    )
    return 0 if required_ok else 1


def _print_section(
    name: str,
    mapping: dict[str, bool | str | int],
) -> None:
    print(f"  {name}:")
    for key, val in mapping.items():
        if isinstance(val, bool):
            status = "SET" if val else "MISSING"
        else:
            status = str(val)
        print(f"    {key}: {status}")


def _print_missing(json_output: bool) -> None:
    """Best-effort report of which env vars are missing."""
    env_keys = [
        "FOUNDRY_HOSTNAME",
        "FOUNDRY_TOKEN",
        "OAUTH_CLIENT_ID",
        "OAUTH_CLIENT_SECRET",
        "OAUTH_TOKEN_URL",
        "MAVEN_ONTOLOGY_NAME",
        "FOUNDRY_MISSION_DATASET_RID",
        "FOUNDRY_EVENTS_DATASET_RID",
        "FOUNDRY_EVENTS_BRANCH",
        "FOUNDRY_MEDIA_SET_RID",
        "MAVEN_COMMAND_ACTION",
        "MAVEN_STATUS_ACTION",
        "FOUNDRY_REQUESTED_SCOPES",
    ]
    import os

    report = {k: bool(os.environ.get(k)) for k in env_keys}
    if json_output:
        print(json.dumps({"env_presence": report}, indent=2, sort_keys=True))
    else:
        print("Environment variable presence:")
        for k, v in report.items():
            print(f"  {k}: {'SET' if v else 'not set'}")


if __name__ == "__main__":
    sys.exit(main())
