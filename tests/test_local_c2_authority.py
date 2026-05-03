"""Local C2 authority layer: offline command acceptance, track management, sync gate.

These tests prove that:
1. All five canonical commands (Resume, Patrol, Return, Hold, Abort)
   are accepted locally in OFFLINE, DEGRADED, and ONLINE modes.
2. Unknown commands are rejected with clear error messages.
3. Every accepted command produces a state-first proof chain.
4. Track authority creates persistent tracks with source attribution.
5. Stale-track handling flags old tracks without deleting them.
6. Sync gate blocks external sync in OFFLINE/DEGRADED, allows in ONLINE.
7. The full denied-ops flow works end-to-end from command through export.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tac_fuse.connectivity import ConnectivityController, ConnectivityMode
from tac_fuse.local_c2 import (
    C2_COMMAND_OPS,
    C2Command,
    C2CommandReceipt,
    C2CommandStatus,
    LocalC2Authority,
    SyncGateStatus,
    TrackAuthority,
    TrackStalenessPolicy,
    UnknownCommandError,
    flush_sync_queue,
    issue_c2_command,
    prepare_sync_payload,
)
from tac_fuse.local_c2.tracks import AssetTrackCue, SourceAttribution
from tac_fuse.mission_state import MissionStateStore

# ═══════════════════════════════════════════════════════════════════════════
# Helper factories
# ═══════════════════════════════════════════════════════════════════════════


def _make_store(**kwargs: object) -> MissionStateStore:
    return MissionStateStore(**kwargs)


def _make_authority(
    mode: ConnectivityMode = ConnectivityMode.OFFLINE,
    operator: str = "field_op_1",
) -> tuple[MissionStateStore, ConnectivityController, LocalC2Authority]:
    store = _make_store(operator=operator)
    ctrl = ConnectivityController(store)
    ctrl.set_manual_override(mode)
    authority = LocalC2Authority(store, ctrl)
    return store, ctrl, authority


def _fresh_timestamp() -> str:
    return (datetime.now(UTC) + timedelta(seconds=30)).isoformat()


def _make_cue(
    asset_id: str = "uav-alpha",
    classification: str = "vehicle",
    priority: str = "high",
    cue_id: str = "cue-001",
) -> AssetTrackCue:
    return AssetTrackCue(
        cue_id=cue_id,
        asset_id=asset_id,
        classification=classification,
        priority=priority,
        source=SourceAttribution(
            source_id=f"{asset_id}_eo_rgb",
            sensor_type="eo_rgb",
            timestamp=_fresh_timestamp(),
            confidence=0.92,
        ),
        lat=38.89,
        lon=-77.03,
        alt_m=120.0,
        range_m=450.0,
    )


# ═══════════════════════════════════════════════════════════════════════════
# 1. Command acceptance — all five commands, all three connectivity modes
# ═══════════════════════════════════════════════════════════════════════════


class TestCommandAcceptance:
    """Prove all five canonical commands are accepted in every connectivity mode."""

    @pytest.mark.parametrize(
        "command",
        ["resume", "patrol", "return", "hold", "abort"],
    )
    @pytest.mark.parametrize(
        "mode",
        [ConnectivityMode.OFFLINE, ConnectivityMode.DEGRADED, ConnectivityMode.ONLINE],
    )
    def test_each_command_accepted_in_each_mode(
        self, command: str, mode: ConnectivityMode
    ) -> None:
        store, ctrl, authority = _make_authority(mode=mode)
        receipt = authority.issue(command, asset_id="uav-alpha")

        assert receipt.command == command
        assert receipt.asset_id == "uav-alpha"
        assert receipt.status == C2CommandStatus.ACCEPTED.value
        assert receipt.connectivity == mode.value

        # State-first proof chain is complete
        proof = store.verify_state_first("operator_task", receipt.task_id)
        assert proof["state_persisted"] is True
        assert proof["audit_logged"] is True
        assert proof["sync_enqueued"] is True
        assert proof["proof_complete"] is True

    def test_command_display_is_capitalized(self) -> None:
        assert C2Command.RESUME.display == "RESUME"
        assert C2Command.PATROL.display == "PATROL"
        assert C2Command.RETURN.display == "RETURN"
        assert C2Command.HOLD.display == "HOLD"
        assert C2Command.ABORT.display == "ABORT"

    def test_command_ops_set_contains_all_five(self) -> None:
        expected = {"resume", "patrol", "return", "hold", "abort"}
        assert C2_COMMAND_OPS == expected

    def test_receipt_has_operator_attribution(self) -> None:
        store, _, authority = _make_authority(operator="sergeant_miller")
        receipt = authority.issue("patrol", asset_id="uav-bravo")
        assert receipt.operator == "sergeant_miller"

    def test_receipt_task_id_matches_store(self) -> None:
        store, _, authority = _make_authority()
        receipt = authority.issue("hold", asset_id="uav-charlie")
        task = store.get_task(receipt.task_id)
        assert task is not None
        assert task["metadata"]["c2_authority"] == "local"
        assert task["metadata"]["command"] == "hold"

    def test_receipt_is_immutable(self) -> None:
        receipt = C2CommandReceipt(
            receipt_id="r1",
            command="patrol",
            asset_id="uav-alpha",
            connectivity="offline",
            status="accepted",
            task_id="t1",
            operator="op1",
            timestamp="2026-05-03T00:00:00Z",
        )
        with pytest.raises(AttributeError):
            receipt.command = "abort"  # type: ignore[misc]

    def test_receipt_to_dict_round_trips(self) -> None:
        _, _, authority = _make_authority()
        receipt = authority.issue("patrol", asset_id="uav-delta")
        d = receipt.to_dict()
        assert d["command"] == "patrol"
        assert d["asset_id"] == "uav-delta"
        assert "receipt_id" in d
        assert "timestamp" in d


# ═══════════════════════════════════════════════════════════════════════════
# 2. Unknown command rejection
# ═══════════════════════════════════════════════════════════════════════════


class TestUnknownCommandRejection:
    """Prove unknown commands are rejected with clear error messages."""

    @pytest.mark.parametrize("bad_cmd", ["fly", "land", "scan", "", "attack", "route_solve"])
    def test_unknown_commands_raise(self, bad_cmd: str) -> None:
        _, _, authority = _make_authority()
        with pytest.raises(UnknownCommandError) as exc_info:
            authority.issue(bad_cmd, asset_id="uav-alpha")
        msg = str(exc_info.value)
        assert "UNKNOWN COMMAND" in msg
        assert "ACCEPTED COMMANDS" in msg

    def test_case_insensitive_accepted(self) -> None:
        """Commands are normalized to lowercase — PATROL, Patrol, patrol all work."""
        _, _, authority = _make_authority()
        receipt = authority.issue("PATROL", asset_id="uav-alpha")
        assert receipt.command == "patrol"

    def test_unknown_command_does_not_create_task(self) -> None:
        store, _, authority = _make_authority()
        with pytest.raises(UnknownCommandError):
            authority.issue("fly_away", asset_id="uav-alpha")
        # No task created
        assert len(store.list_tasks()) == 0
        assert store.pending_sync_count() == 0


# ═══════════════════════════════════════════════════════════════════════════
# 3. State-first proof chains
# ═══════════════════════════════════════════════════════════════════════════


class TestStateFirstProofChain:
    """Prove every accepted command has a complete state-first proof chain."""

    def test_single_command_proof_chain(self) -> None:
        store, _, authority = _make_authority()
        receipt = authority.issue("patrol", asset_id="uav-alpha")

        proof = store.verify_state_first("operator_task", receipt.task_id)
        assert proof["state_persisted"] is True
        assert proof["audit_logged"] is True
        assert proof["sync_enqueued"] is True
        assert proof["proof_complete"] is True

    def test_multiple_commands_all_proven(self) -> None:
        store, _, authority = _make_authority()
        drones = ["uav-alpha", "uav-bravo", "uav-charlie", "uav-delta"]
        commands = ["patrol", "hold", "return", "resume"]

        for drone, cmd in zip(drones, commands, strict=True):
            authority.issue(cmd, asset_id=drone)

        report = store.verify_command_proof_chain()
        assert report["chain_complete"] is True
        assert report["total_tasks"] == 4
        assert report["proven"] == 4
        assert report["unproven"] == 0

    def test_abort_then_resume_proof_chain(self) -> None:
        """Emergency abort followed by resume retains complete proof chain."""
        store, _, authority = _make_authority()

        authority.issue("patrol", asset_id="uav-alpha")
        authority.issue("abort", asset_id="uav-alpha")
        authority.issue("resume", asset_id="uav-alpha")

        report = store.verify_command_proof_chain()
        assert report["chain_complete"] is True
        assert report["total_tasks"] == 3

    def test_proof_chain_survives_connectivity_transition(self) -> None:
        """Commands issued across OFFLINE → DEGRADED → ONLINE all proven."""
        store = _make_store()
        ctrl = ConnectivityController(store)
        authority = LocalC2Authority(store, ctrl)

        ctrl.set_manual_override(ConnectivityMode.OFFLINE)
        r1 = authority.issue("patrol", asset_id="uav-alpha")

        ctrl.set_manual_override(ConnectivityMode.DEGRADED)
        r2 = authority.issue("hold", asset_id="uav-bravo")

        ctrl.set_manual_override(ConnectivityMode.ONLINE)
        r3 = authority.issue("resume", asset_id="uav-charlie")

        for receipt in (r1, r2, r3):
            proof = store.verify_state_first("operator_task", receipt.task_id)
            assert proof["proof_complete"] is True

    def test_audit_log_has_c2_authority_events(self) -> None:
        store, _, authority = _make_authority()
        authority.issue("patrol", asset_id="uav-alpha")
        authority.issue("hold", asset_id="uav-bravo")

        audit = store.list_audit_events()
        assert len(audit) >= 2
        messages = [e["message"] for e in audit]
        assert any("PATROL" in m for m in messages)
        assert any("HOLD" in m for m in messages)


# ═══════════════════════════════════════════════════════════════════════════
# 4. Track authority — persistent tracks with source attribution
# ═══════════════════════════════════════════════════════════════════════════


class TestTrackAuthority:
    """Prove track authority creates persistent tracks from drone cues."""

    def test_ingest_cue_creates_track(self) -> None:
        store = _make_store()
        ta = TrackAuthority(store)
        cue = _make_cue()

        track = ta.ingest_cue(cue)
        assert track["track_id"] == "cue-001"
        assert track["asset_id"] == "uav-alpha"
        assert track["classification"] == "vehicle"
        assert track["priority"] == "high"

    def test_track_has_source_attribution(self) -> None:
        store = _make_store()
        ta = TrackAuthority(store)
        cue = _make_cue()

        track = ta.ingest_cue(cue)
        assert "source" in track
        source = track["source"]
        assert source["source_id"] == "uav-alpha_eo_rgb"
        assert source["sensor_type"] == "eo_rgb"
        assert source["confidence"] == 0.92

    def test_track_persisted_to_store(self) -> None:
        store = _make_store()
        ta = TrackAuthority(store)
        cue = _make_cue(cue_id="persist-test-001")

        ta.ingest_cue(cue)
        retrieved = ta.get_track("persist-test-001")
        assert retrieved is not None
        assert retrieved["asset_id"] == "uav-alpha"
        assert retrieved["classification"] == "vehicle"

    def test_list_tracks_by_asset(self) -> None:
        store = _make_store()
        ta = TrackAuthority(store)

        ta.ingest_cue(_make_cue(asset_id="uav-alpha", cue_id="c1"))
        ta.ingest_cue(_make_cue(asset_id="uav-bravo", cue_id="c2"))
        ta.ingest_cue(_make_cue(asset_id="uav-alpha", cue_id="c3"))

        alpha_tracks = ta.list_tracks(asset_id="uav-alpha")
        assert len(alpha_tracks) == 2
        assert all(t["asset_id"] == "uav-alpha" for t in alpha_tracks)

    def test_track_update_overwrites(self) -> None:
        store = _make_store()
        ta = TrackAuthority(store)

        ta.ingest_cue(
            _make_cue(cue_id="dup-001", classification="vehicle", priority="high")
        )
        ta.ingest_cue(
            _make_cue(cue_id="dup-001", classification="person", priority="critical")
        )

        track = ta.get_track("dup-001")
        assert track is not None
        assert track["classification"] == "person"
        assert track["priority"] == "critical"

    def test_all_four_drones_emit_cues(self) -> None:
        store = _make_store()
        ta = TrackAuthority(store)

        for i, drone in enumerate(
            ["uav-alpha", "uav-bravo", "uav-charlie", "uav-delta"]
        ):
            cue = _make_cue(
                asset_id=drone,
                cue_id=f"cue-{drone}-001",
                classification=["vehicle", "person", "structure", "unknown"][i],
                priority=["medium", "high", "low", "critical"][i],
            )
            track = ta.ingest_cue(cue)
            assert track["asset_id"] == drone

        all_tracks = ta.list_tracks()
        assert len(all_tracks) == 4
        asset_ids = {t["asset_id"] for t in all_tracks}
        assert asset_ids == {"uav-alpha", "uav-bravo", "uav-charlie", "uav-delta"}

    def test_haversine_range(self) -> None:
        dist = TrackAuthority.compute_range_m(38.89, -77.03, 38.90, -77.04)
        assert 500 < dist < 2000  # roughly a km-level distance


# ═══════════════════════════════════════════════════════════════════════════
# 5. Stale-track handling
# ═══════════════════════════════════════════════════════════════════════════


class TestStaleTrackHandling:
    """Prove stale tracks are flagged but never deleted."""

    def test_fresh_track_not_stale(self) -> None:
        policy = TrackStalenessPolicy(max_age_seconds=60.0)
        assert not policy.is_stale(_fresh_timestamp())

    def test_old_track_is_stale(self) -> None:
        policy = TrackStalenessPolicy(max_age_seconds=5.0)
        # Use an old timestamp
        assert policy.is_stale("2020-01-01T00:00:00+00:00")

    def test_stale_track_flagged_not_deleted(self) -> None:
        store = _make_store()
        policy = TrackStalenessPolicy(max_age_seconds=0.01)
        ta = TrackAuthority(store, staleness_policy=policy)

        # Cue with old timestamp → immediately stale
        cue = AssetTrackCue(
            cue_id="stale-001",
            asset_id="uav-alpha",
            classification="vehicle",
            priority="high",
            source=SourceAttribution(
                source_id="uav-alpha_eo",
                sensor_type="eo_rgb",
                timestamp="2020-01-01T00:00:00+00:00",
                confidence=0.9,
            ),
        )
        track = ta.ingest_cue(cue)
        assert track["is_stale"] is True

        # Track still exists in store
        retrieved = ta.get_track("stale-001")
        assert retrieved is not None
        assert retrieved["is_stale"] == 1

    def test_list_tracks_excludes_stale(self) -> None:
        store = _make_store()
        policy = TrackStalenessPolicy(max_age_seconds=0.01)
        ta = TrackAuthority(store, staleness_policy=policy)

        # Stale cue
        ta.ingest_cue(
            AssetTrackCue(
                cue_id="stale-002",
                asset_id="uav-alpha",
                classification="vehicle",
                priority="high",
                source=SourceAttribution(
                    source_id="uav-alpha_eo",
                    sensor_type="eo_rgb",
                    timestamp="2020-01-01T00:00:00+00:00",
                    confidence=0.9,
                ),
            )
        )
        # Fresh cue
        ta.ingest_cue(_make_cue(cue_id="fresh-001"))

        all_tracks = ta.list_tracks(include_stale=True)
        assert len(all_tracks) == 2

        fresh_only = ta.list_tracks(include_stale=False)
        assert len(fresh_only) == 1
        assert fresh_only[0]["track_id"] == "fresh-001"


# ═══════════════════════════════════════════════════════════════════════════
# 6. Sync gate
# ═══════════════════════════════════════════════════════════════════════════


class TestSyncGate:
    """Prove sync gate blocks external sync in OFFLINE/DEGRADED, allows in ONLINE."""

    def test_sync_blocked_offline(self) -> None:
        store, ctrl, authority = _make_authority(mode=ConnectivityMode.OFFLINE)
        authority.issue("patrol", asset_id="uav-alpha")

        gate = check_sync_gate_internal(store, ctrl)
        assert not gate.is_allowed
        assert gate.status == SyncGateStatus.BLOCKED_OFFLINE.value
        assert gate.pending_count >= 1

    def test_sync_blocked_degraded(self) -> None:
        store, ctrl, authority = _make_authority(mode=ConnectivityMode.DEGRADED)
        authority.issue("hold", asset_id="uav-bravo")

        gate = check_sync_gate_internal(store, ctrl)
        assert not gate.is_allowed
        assert gate.status == SyncGateStatus.BLOCKED_DEGRADED.value

    def test_sync_allowed_online(self) -> None:
        store, ctrl, authority = _make_authority(mode=ConnectivityMode.ONLINE)
        authority.issue("patrol", asset_id="uav-alpha")

        gate = check_sync_gate_internal(store, ctrl)
        assert gate.is_allowed
        assert gate.status == SyncGateStatus.OPEN.value

    def test_prepare_sync_payload_stages_items(self) -> None:
        store, _, authority = _make_authority()
        authority.issue("patrol", asset_id="uav-alpha")
        authority.issue("hold", asset_id="uav-bravo")

        payload = prepare_sync_payload(store)
        assert payload["pending_count"] >= 2
        assert len(payload["items"]) >= 2
        assert payload["operator"] == store.operator

    def test_flush_blocked_offline(self) -> None:
        store, ctrl, authority = _make_authority(mode=ConnectivityMode.OFFLINE)
        authority.issue("patrol", asset_id="uav-alpha")

        result = flush_sync_queue(store, ctrl)
        assert result["flushed"] is False
        assert "BLOCKED" in result["message"]
        # Queue untouched
        assert store.pending_sync_count() >= 1

    def test_flush_succeeds_online(self) -> None:
        store, ctrl, authority = _make_authority(mode=ConnectivityMode.ONLINE)
        authority.issue("patrol", asset_id="uav-alpha")
        authority.issue("hold", asset_id="uav-bravo")

        result = flush_sync_queue(store, ctrl)
        assert result["flushed"] is True
        assert result["items_flushed"] >= 2
        assert store.pending_sync_count() == 0

    def test_sync_gate_snapshot(self) -> None:
        store, ctrl, _ = _make_authority(mode=ConnectivityMode.OFFLINE)
        gate = check_sync_gate_internal(store, ctrl)
        d = gate.to_dict()
        assert "status" in d
        assert "connectivity_mode" in d
        assert "pending_count" in d
        assert "is_allowed" in d


def check_sync_gate_internal(store, ctrl):
    """Import-qualified wrapper to avoid circular imports in test."""
    from tac_fuse.local_c2.sync_gate import check_sync_gate

    return check_sync_gate(store, ctrl)


# ═══════════════════════════════════════════════════════════════════════════
# 7. Full denied-ops end-to-end flow
# ═══════════════════════════════════════════════════════════════════════════


class TestDeniedOpsEndToEnd:
    """Prove the full flow: commands → tracks → sync gate → export."""

    def test_full_route_guard_scenario(self) -> None:
        """Simulate a complete route-guard scenario from the task description.

        Phase 1: OFFLINE initial tasking (4 drones)
        Phase 2: OFFLINE automatic corridor warning and retasking
        Phase 3: OFFLINE emergency abort
        Phase 4: DEGRADED recovery (resume patrol)
        Phase 5: ONLINE sync and export
        """
        store = _make_store(operator="field_op_1")
        ctrl = ConnectivityController(store)
        authority = LocalC2Authority(store, ctrl)
        track_auth = TrackAuthority(store)

        # ── Phase 1: OFFLINE initial tasking ──────────────────────────
        ctrl.set_manual_override(ConnectivityMode.OFFLINE)

        drones = ["uav-alpha", "uav-bravo", "uav-charlie", "uav-delta"]
        initial_cmds = ["patrol", "hold", "scout", "overwatch"]
        # Map 'scout' and 'overwatch' to canonical commands
        cmd_map = {"scout": "patrol", "overwatch": "hold"}

        receipts = []
        for drone, cmd in zip(drones, initial_cmds, strict=True):
            canonical = cmd_map.get(cmd, cmd)
            r = authority.issue(canonical, asset_id=drone)
            receipts.append(r)
            assert r.connectivity == "offline"

        # All commands have proof chains
        report = store.verify_command_proof_chain()
        assert report["chain_complete"] is True
        assert report["total_tasks"] == 4

        # Ingest initial tracks
        for drone in drones:
            cue = _make_cue(
                asset_id=drone,
                cue_id=f"track-{drone}-001",
            )
            track_auth.ingest_cue(cue)

        all_tracks = track_auth.list_tracks()
        assert len(all_tracks) == 4

        # Sync blocked
        assert store.pending_sync_count() >= 4
        assert not ctrl.is_external_sync_allowed()

        # ── Phase 2: OFFLINE retasking ────────────────────────────────
        store.create_alert(
            "AUTOMATIC CORRIDOR GUARD: RF POCKET DETECTED NEAR ROUTE",
            severity="warning",
            payload={"source": "bvh_route_guard", "priority": "high"},
        )
        authority.issue("hold", asset_id="uav-alpha", metadata={"reason": "RF pocket detected"})
        # Bravo → resume patrol
        authority.issue("resume", asset_id="uav-bravo")
        # Charlie holds (already holding)

        # ── Phase 3: OFFLINE emergency abort ──────────────────────────
        abort_receipt = authority.issue("abort", asset_id="swarm")
        assert abort_receipt.command == "abort"
        assert abort_receipt.connectivity == "offline"

        # Alert for abort
        store.create_alert(
            "EMERGENCY ABORT: ALL DRONES HOLDING POSITION",
            severity="critical",
            payload={"operator_action": "abort_all"},
        )

        # ── Phase 4: DEGRADED recovery ───────────────────────────────
        ctrl.set_manual_override(ConnectivityMode.DEGRADED)

        for drone in drones:
            authority.issue("resume", asset_id=drone)

        # Commands accepted but sync still blocked
        assert not ctrl.is_external_sync_allowed()

        # ── Phase 5: ONLINE sync and export ───────────────────────────
        ctrl.set_manual_override(ConnectivityMode.ONLINE)

        # Flush sync queue
        flush_result = flush_sync_queue(store, ctrl)
        assert flush_result["flushed"] is True
        assert store.pending_sync_count() == 0

        # Export works
        from tac_fuse.foundry_export import build_foundry_export

        export = build_foundry_export(store)
        assert len(export["operator_tasks"]) > 0
        assert len(export["mission_events"]) > 0

        # Final proof chain is complete
        final_report = store.verify_command_proof_chain()
        assert final_report["chain_complete"] is True

    def test_command_history_filtered_by_asset(self) -> None:
        store, _, authority = _make_authority()
        authority.issue("patrol", asset_id="uav-alpha")
        authority.issue("hold", asset_id="uav-bravo")
        authority.issue("abort", asset_id="uav-alpha")

        alpha_history = authority.history(asset_id="uav-alpha")
        assert len(alpha_history) == 2
        assert all(h.asset_id == "uav-alpha" for h in alpha_history)

        bravo_history = authority.history(asset_id="uav-bravo")
        assert len(bravo_history) == 1

    def test_convenience_helper_issue_c2_command(self) -> None:
        store = _make_store()
        receipt = issue_c2_command(
            store,
            "patrol",
            asset_id="uav-delta",
            description="TEST PATROL COMMAND",
        )
        assert receipt.command == "patrol"
        assert receipt.asset_id == "uav-delta"
        assert receipt.status == C2CommandStatus.ACCEPTED.value

        # Proof chain
        proof = store.verify_state_first("operator_task", receipt.task_id)
        assert proof["proof_complete"] is True
