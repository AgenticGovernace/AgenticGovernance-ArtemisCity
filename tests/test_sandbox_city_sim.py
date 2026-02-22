"""Smoke tests for the Sandbox City simulation loop."""

from app.sandbox_city.run_simulation import CitySimulation


def test_simulation_is_deterministic_with_seed():
    sim_a = CitySimulation(seed=42)
    sim_b = CitySimulation(seed=42)

    snapshot_a = sim_a.run(ticks=5, verbose=False)
    snapshot_b = sim_b.run(ticks=5, verbose=False)

    assert snapshot_a["scores"] == snapshot_b["scores"]
    assert snapshot_a["zones"] == snapshot_b["zones"]


def test_scores_remain_normalized():
    sim = CitySimulation(seed=7)
    snapshot = sim.run(ticks=8, verbose=False)
    scores = snapshot["scores"]

    for key, value in scores.items():
        assert 0.0 <= value <= 1.0, f"{key} drifted out of bounds: {value}"
