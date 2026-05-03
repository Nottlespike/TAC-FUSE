from tac_fuse.replay import (
    SeededReplayEngine,
    demo_conflicts,
    demo_restricted_entries,
    generate_scenario,
)


def test_generate_scenario_is_deterministic() -> None:
    first = generate_scenario(frames=8)
    second = generate_scenario(frames=8)

    assert first == second
    assert len(first[0]) >= 5
    assert any(track.is_stale for frame in first for track in frame)
    assert {track.asset_id for track in first[0]} >= {"uav-alpha", "uav-bravo", "uav-charlie"}


def test_seeded_replay_engine_matches_contract() -> None:
    engine = SeededReplayEngine(seed=7, num_assets=5, duration_sec=10.0, tick_interval_sec=2.5)
    frames = engine.generate()

    assert len(frames) == 4
    assert len(frames[0]) == 5
    assert engine.restricted_entries == demo_restricted_entries(engine._scenario)
    assert demo_conflicts(frames)[0].to_dict()["asset_ids"] == ["uav-alpha", "uav-charlie"]
