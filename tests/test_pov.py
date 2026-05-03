from tac_fuse.pov import generate_pov_sequence, project_tracks_to_pov, render_svg_pov
from tac_fuse.replay import generate_scenario


def test_project_tracks_to_pov_finds_visible_objects() -> None:
    scenario = generate_scenario(frames=8)
    frame = project_tracks_to_pov(scenario[6])

    assert frame.ownship.asset_id == "uav-alpha"
    assert frame.objects
    assert frame.field_condition in {
        "clear corridor",
        "dense multi asset formation",
        "drone near restricted area",
        "low power return corridor",
    }


def test_generate_pov_sequence_and_svg_render() -> None:
    frames = generate_pov_sequence(generate_scenario(frames=4))
    svg = render_svg_pov(frames[0])

    assert len(frames) == 4
    assert svg.startswith("<svg")
    assert "Alpha POV" in svg
