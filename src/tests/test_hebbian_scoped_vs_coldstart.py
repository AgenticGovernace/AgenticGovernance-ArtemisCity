"""Hebbian scoped-corpus learning dynamics: post-600 cycles vs cold start.

This module was originally a notebook transcribed into ``src/tests`` with no
test functions and no assertions: ~680 lines of simulation executed as an import
side effect. Because ``scikit-learn`` and ``matplotlib`` were never declared as
dependencies, it silently ``importorskip``-ed out of every run, so nothing here
was ever checked.

It is now a real test module. The simulation engine is preserved exactly; the
narrative ``print`` blocks are replaced by assertions on the claims the original
docstring made:

1. Scoped corpus pre-training breaks winner-take-all.
2. Post-600-cycle agents outperform cold start.
3. Oscillation (sawtooth) is reduced by scope differentiation.
4. A watchdog/sentinel can detect instability via sign-change frequency.
5. ATP context vectors improve routing coherence across specialists.

**Claim 1 does not hold as originally stated**, and the assertions below record
what the simulation actually shows: scoped pre-training *alone* concentrates
selection further than cold start (specialization index 0.07 vs 0.22, where
higher means more evenly distributed). Only scoped corpus *plus* ATP context
routing breaks the monopoly (0.43). The original file printed "Scoped corpus
BREAKS monopoly" unconditionally while computing numbers that contradict it --
which is precisely the failure mode an assertion-free "test" cannot catch.

Determinism: every agent is seeded via ``MLPRegressor(random_state=...)`` and
the module seeds NumPy directly, so the metrics are reproducible run to run.
Thresholds below are set with slack around observed values so ordinary
floating-point and library-version drift does not cause flakes, while a genuine
reversal of a claim still fails.

Author: Apollo (Prinston Palmer) + Artemis (Claude)
Data Source: Synthetic 3-phase concept drift (Linear -> Quadratic -> Sine)
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("numpy")
pytest.importorskip("sklearn")

import numpy as np  # noqa: E402
from sklearn.neural_network import MLPRegressor  # noqa: E402

pytestmark = pytest.mark.slow

# ============================================================
# 1. DATA GENERATION -- 3-phase concept drift
# ============================================================

N = 1000
PRE_TRAIN_CYCLES = 600  # The 600-cycle threshold
N_AGENTS = 5
SCOPE_NAMES = ("Linear", "Quadratic", "Sinusoidal", "Mixed", "Noise-Robust")
DRIFT_POINTS = (334, 667)


def build_drift_dataset() -> tuple[np.ndarray, np.ndarray]:
    """Return the deterministic 3-phase concept-drift dataset."""
    np.random.seed(42)
    features = np.random.uniform(-5, 5, (N, 3))
    targets = np.zeros(N)

    # Phase 1: Linear (0-333)
    targets[:334] = 2 * features[:334, 0] + 3 * features[:334, 1]
    # Phase 2: Quadratic (334-666)
    targets[334:667] = -2 * features[334:667, 0] ** 2 + features[334:667, 1]
    # Phase 3: Sinusoidal (667-999)
    targets[667:] = 5 * np.sin(features[667:, 2]) + features[667:, 0]

    targets += np.random.normal(0, 1.0, N)
    return features, targets


# ============================================================
# 2. SCOPED CORPUS PRE-TRAINING DATA
# ============================================================
# Each agent gets a DIFFERENT training corpus reflecting embodied cognition.
# Agent 0: Linear specialist (research agent)
# Agent 1: Quadratic specialist (analysis agent)
# Agent 2: Sinusoidal/periodic specialist (pattern agent)
# Agent 3: Mixed/generalist (summarization agent)
# Agent 4: Noise-robust agent (validation agent)


def generate_scoped_corpus(scope, n_samples=PRE_TRAIN_CYCLES):
    """Generate scoped training data for each agent specialty."""
    np.random.seed(scope)  # Deterministic per scope
    X = np.random.uniform(-5, 5, (n_samples, 3))
    noise = np.random.normal(0, 0.5, n_samples)

    if scope == 0:  # LINEAR specialist
        y = 2 * X[:, 0] + 3 * X[:, 1] + noise
    elif scope == 1:  # QUADRATIC specialist
        y = -2 * X[:, 0] ** 2 + X[:, 1] + noise
    elif scope == 2:  # SINUSOIDAL specialist
        y = 5 * np.sin(X[:, 2]) + X[:, 0] + noise
    elif scope == 3:  # MIXED/GENERALIST -- a mixture of all three
        third = n_samples // 3
        y = np.zeros(n_samples)
        y[:third] = 2 * X[:third, 0] + 3 * X[:third, 1]
        y[third : 2 * third] = (
            -2 * X[third : 2 * third, 0] ** 2 + X[third : 2 * third, 1]
        )
        y[2 * third :] = 5 * np.sin(X[2 * third :, 2]) + X[2 * third :, 0]
        y += noise
    elif scope == 4:  # NOISE-ROBUST (trained with heavy noise)
        y = 2 * X[:, 0] + 3 * X[:, 1] + np.random.normal(0, 3.0, n_samples)
    else:
        raise ValueError(f"unknown corpus scope: {scope}")

    return X, y


def create_agent(seed):
    """Standard high-capacity agent, seeded for reproducibility."""
    return MLPRegressor(
        hidden_layer_sizes=(100, 50),
        activation="relu",
        solver="adam",
        learning_rate_init=0.005,
        random_state=seed,
    )


def pre_train_agent(agent, X_corpus, y_corpus):
    """Pre-train an agent on its scoped corpus for 600 cycles."""
    for i in range(len(X_corpus)):
        agent.partial_fit(X_corpus[i].reshape(1, -1), y_corpus[i : i + 1])
    return agent


# ============================================================
# 3. SIMULATION ENGINE
# ============================================================


def run_simulation(
    agents,
    weights,
    X,
    y,
    decay_rate=0.99,
    success_threshold=5.0,
    label="Simulation",
    use_atp_context=False,
):
    """Run a Hebbian-routing simulation and collect telemetry for analysis.

    Args:
        agents: Sequence of agents selectable for each prediction step.
        weights: Current Hebbian routing weights for the candidate agents.
        X: Feature matrix replayed through the simulation loop.
        y: Target values paired with ``X`` for online evaluation and fitting.
        decay_rate: Multiplicative decay applied to each weight after a step.
        success_threshold: Absolute-error cutoff counting a prediction good.
        label: Human-readable label attached to the telemetry bundle.
        use_atp_context: Apply phase-aware ATP routing bonuses during selection.

    Returns:
        dict[str, object]: Telemetry containing per-step errors, weight history,
        agent selections, sign-change counts, phase-dominance counts, and label.
    """
    n_agents = len(agents)
    errors = []
    weights_history = []
    selections = []
    weight_deltas = [[] for _ in range(n_agents)]  # Track +/- per agent

    for t in range(len(X)):
        x_t = X[t].reshape(1, -1)
        y_t = y[t : t + 1]

        # --- ATP Context Vector (if enabled) ---
        # Phase detection based on step -- simulates an ATP #Context tag.
        if use_atp_context:
            phase_hint = np.zeros(3)
            if t < 334:
                phase_hint[0] = 1.0  # Linear signal
            elif t < 667:
                phase_hint[1] = 1.0  # Quadratic signal
            else:
                phase_hint[2] = 1.0  # Sinusoidal signal
            context_bonus = np.zeros(n_agents)
            for a in range(min(3, n_agents)):
                context_bonus[a] = phase_hint[a] * 2.0  # Boost matching scope
            effective_weights = weights + context_bonus
        else:
            effective_weights = weights.copy()

        # --- Agent Selection (Hebbian Routing) ---
        candidates = np.where(effective_weights == np.max(effective_weights))[0]
        idx = np.random.choice(candidates)
        selections.append(idx)

        agent = agents[idx]

        # --- Prediction ---
        try:
            y_hat = agent.predict(x_t)[0]
        except Exception:  # noqa: BLE001 - an unfitted agent predicts nothing
            y_hat = 0.0

        # --- Error & Hebbian Update ---
        err = np.abs(y_t[0] - y_hat)
        errors.append(err)

        if err < success_threshold:
            weights[idx] += 1.0
            delta = 1.0
        else:
            weights[idx] = max(0.0, weights[idx] - 1.0)
            delta = -1.0

        # Track delta sign changes (sawtooth detection)
        weight_deltas[idx].append(delta)

        # --- Decay ---
        weights *= decay_rate
        weights = np.maximum(weights, 0.1)  # Floor

        # --- Train ---
        agent.partial_fit(x_t, y_t)

        weights_history.append(weights.copy())

    # --- Post-processing: Sawtooth Analysis ---
    sign_changes = []
    for a in range(n_agents):
        deltas = weight_deltas[a]
        if len(deltas) < 2:
            sign_changes.append(0)
        else:
            sign_changes.append(
                sum(1 for i in range(1, len(deltas)) if deltas[i] != deltas[i - 1])
            )

    # --- Phase Dominance ---
    selections = np.array(selections)
    phase_dom = {
        "Linear (0-333)": np.bincount(selections[:334], minlength=n_agents),
        "Quadratic (334-666)": np.bincount(selections[334:667], minlength=n_agents),
        "Sinusoidal (667-999)": np.bincount(selections[667:], minlength=n_agents),
    }

    return {
        "errors": np.array(errors),
        "weights_history": np.array(weights_history),
        "selections": selections,
        "sign_changes": sign_changes,
        "phase_dominance": phase_dom,
        "label": label,
    }


# ============================================================
# 4. ANALYSIS HELPERS
# ============================================================


def watchdog_analysis(result, window=50, oscillation_threshold=0.4):
    """Sentinel logic: flag steps whose rolling sign-change rate is unstable.

    Mirrors the production Hebbian Sentinel, which alerts when the rolling
    sign-change rate exceeds ``ARTEMIS_HEBBIAN_SENTINEL_THRESHOLD``.
    """
    errors = result["errors"]

    deltas = [0]
    for t in range(1, len(errors)):
        deltas.append(1 if errors[t] < 5.0 else -1)

    alert_steps = []
    oscillation_rates = []
    for t in range(window, len(deltas)):
        window_deltas = deltas[t - window : t]
        changes = sum(
            1
            for i in range(1, len(window_deltas))
            if window_deltas[i] != window_deltas[i - 1]
        )
        rate = changes / window
        oscillation_rates.append(rate)
        if rate > oscillation_threshold:
            alert_steps.append(t)

    return {
        "alert_steps": alert_steps,
        "oscillation_rates": oscillation_rates,
        "alert_count": len(alert_steps),
        "alert_rate": len(alert_steps) / max(1, len(oscillation_rates)),
    }


def specialization_index(selections, n_agents=N_AGENTS):
    """Return normalized selection entropy: 0.0 is a monopoly, 1.0 is uniform.

    A *higher* index means selection is spread across more agents, i.e. less
    winner-take-all.
    """
    counts = np.bincount(selections, minlength=n_agents)
    shares = counts[counts > 0] / len(selections)
    return float(-np.sum(shares * np.log2(shares)) / np.log2(n_agents))


# ============================================================
# 5. THE THREE CONDITIONS (computed once per module)
# ============================================================


@pytest.fixture(scope="module")
def conditions():
    """Run cold-start, scoped, and scoped+ATP simulations exactly once."""
    features, targets = build_drift_dataset()

    cold = run_simulation(
        [create_agent(i) for i in range(N_AGENTS)],
        np.ones(N_AGENTS),
        features,
        targets,
        label="Cold Start (Homogeneous)",
    )

    scoped_agents = [create_agent(i) for i in range(N_AGENTS)]
    for i in range(N_AGENTS):
        scoped_agents[i] = pre_train_agent(scoped_agents[i], *generate_scoped_corpus(i))
    scoped = run_simulation(
        scoped_agents,
        np.ones(N_AGENTS),
        features,
        targets,
        label="Scoped Post-600 (Specialized)",
    )

    atp_agents = [create_agent(i) for i in range(N_AGENTS)]
    for i in range(N_AGENTS):
        atp_agents[i] = pre_train_agent(atp_agents[i], *generate_scoped_corpus(i))
    scoped_atp = run_simulation(
        atp_agents,
        np.ones(N_AGENTS),
        features,
        targets,
        use_atp_context=True,
        label="Scoped Post-600 + ATP Context",
    )

    bundle = {"cold": cold, "scoped": scoped, "atp": scoped_atp}
    _maybe_write_figure(bundle)
    return bundle


def _maybe_write_figure(bundle) -> None:
    """Render the comparison figure only when explicitly requested.

    A test run must not write artifacts into the source tree as a side effect,
    so plotting is opt-in via ``ARTEMIS_WRITE_TEST_ARTIFACTS=1``.
    """
    if os.getenv("ARTEMIS_WRITE_TEST_ARTIFACTS", "0").strip() not in ("1", "true"):
        return
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 1, figsize=(14, 10))
    window = 50
    for key, label in (
        ("cold", "Cold Start"),
        ("scoped", "Scoped Post-600"),
        ("atp", "Scoped + ATP"),
    ):
        errors = bundle[key]["errors"]
        smoothed = np.convolve(errors, np.ones(window) / window, mode="valid")
        axes[0].plot(smoothed, label=label, alpha=0.8)
    axes[0].set_title("Rolling Mean Absolute Error")
    axes[0].set_xlabel("Step")
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    for agent_index in range(N_AGENTS):
        axes[1].plot(
            bundle["scoped"]["weights_history"][:, agent_index],
            alpha=0.7,
            label=f"Agent {agent_index} ({SCOPE_NAMES[agent_index]})",
        )
    axes[1].set_title("Scoped Post-600: Weight Evolution (Specialization)")
    axes[1].set_xlabel("Step")
    axes[1].set_ylabel("Hebbian Weight")
    for point in DRIFT_POINTS:
        axes[0].axvline(x=point, color="red", linestyle=":", alpha=0.5)
        axes[1].axvline(x=point, color="red", linestyle=":", alpha=0.5)
    axes[1].legend(fontsize=8)
    axes[1].grid(True, alpha=0.3)

    plt.tight_layout()
    out_dir = Path(__file__).resolve().parent / "test_artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_dir / "hebbian_scoped_vs_coldstart.png", dpi=150)
    plt.close()


# ============================================================
# 6. CLAIMS
# ============================================================


def test_scoped_pretraining_outperforms_cold_start(conditions):
    """Claim 2: 600 cycles of scoped pre-training reduce cumulative error."""
    mae_cold = float(np.sum(conditions["cold"]["errors"]))
    mae_scoped = float(np.sum(conditions["scoped"]["errors"]))

    assert mae_scoped < mae_cold, (
        f"scoped pre-training must beat cold start "
        f"(scoped={mae_scoped:.1f}, cold={mae_cold:.1f})"
    )
    improvement = 1 - mae_scoped / mae_cold
    assert improvement > 0.05, (
        f"scoped improvement collapsed to {improvement:.1%}; "
        "the 600-cycle corpus is no longer buying accuracy"
    )


def test_atp_context_improves_on_scoped_alone(conditions):
    """Claim 5: ATP phase context adds accuracy on top of a scoped corpus."""
    mae_cold = float(np.sum(conditions["cold"]["errors"]))
    mae_scoped = float(np.sum(conditions["scoped"]["errors"]))
    mae_atp = float(np.sum(conditions["atp"]["errors"]))

    assert mae_atp < mae_scoped < mae_cold, (
        "expected cold > scoped > scoped+ATP cumulative error, got "
        f"cold={mae_cold:.1f}, scoped={mae_scoped:.1f}, atp={mae_atp:.1f}"
    )
    assert 1 - mae_atp / mae_cold > 0.10


def test_scope_differentiation_reduces_oscillation(conditions):
    """Claim 3: sawtooth weight oscillation falls as scope differentiates."""
    peak_cold = max(conditions["cold"]["sign_changes"])
    peak_scoped = max(conditions["scoped"]["sign_changes"])
    peak_atp = max(conditions["atp"]["sign_changes"])

    assert peak_atp < peak_scoped < peak_cold, (
        "expected peak sign-change count to fall from cold to scoped to ATP, "
        f"got cold={peak_cold}, scoped={peak_scoped}, atp={peak_atp}"
    )


def test_sentinel_detects_instability_and_quiets_as_agents_improve(conditions):
    """Claim 4: rolling sign-change rate is a usable instability signal."""
    cold = watchdog_analysis(conditions["cold"])
    scoped = watchdog_analysis(conditions["scoped"])
    atp = watchdog_analysis(conditions["atp"])

    # The signal must actually fire on the least stable condition, or it is
    # not a detector at all.
    assert cold["alert_count"] > 0
    # ...and must quiet down as the agent pool stabilizes, or it is just noise.
    assert atp["alert_count"] < scoped["alert_count"] < cold["alert_count"], (
        "sentinel alert volume should fall as agents specialize, got "
        f"cold={cold['alert_count']}, scoped={scoped['alert_count']}, "
        f"atp={atp['alert_count']}"
    )
    assert 0.0 <= atp["alert_rate"] <= 1.0


def test_scoped_corpus_alone_does_not_break_winner_take_all(conditions):
    """Claim 1, corrected: only ATP routing breaks the selection monopoly.

    The original module asserted in prose that a scoped corpus breaks
    winner-take-all. Its own numbers disagree: scoped pre-training *without*
    context routing concentrates selection more tightly than cold start. The
    monopoly is broken only once ATP context vectors steer each phase toward
    its matching specialist.
    """
    cold_index = specialization_index(conditions["cold"]["selections"])
    scoped_index = specialization_index(conditions["scoped"]["selections"])
    atp_index = specialization_index(conditions["atp"]["selections"])

    assert scoped_index < cold_index, (
        "scoped-only pre-training was expected to concentrate selection "
        f"(scoped={scoped_index:.4f}, cold={cold_index:.4f})"
    )
    assert atp_index > cold_index and atp_index > scoped_index, (
        "ATP context routing must spread selection across specialists, got "
        f"atp={atp_index:.4f}, cold={cold_index:.4f}, scoped={scoped_index:.4f}"
    )


def test_atp_context_bonus_is_decisive_only_near_weight_parity(conditions):
    """The ATP context bonus steers early routing but is later outweighed.

    This pins a real limitation of the mechanism as implemented. The context
    bonus is a flat ``+2.0`` added to a candidate's Hebbian weight, while a
    repeatedly-successful agent accumulates weight toward the fixed point of
    ``w -> (w + 1) * decay_rate`` -- roughly ``99`` at ``decay_rate=0.99``.

    So the bonus decides the first phase, where every weight still sits at its
    initial ``1.0``, and is negligible afterwards: by the sinusoidal phase the
    quadratic specialist holds a weight near ``59`` and keeps winning even
    though agent 2 is the matching specialist and is being boosted.

    Raising the bonus (or capping accumulation) would change this; the test
    exists so that change is a deliberate, visible one.
    """
    phase_dominance = conditions["atp"]["phase_dominance"]

    linear_counts = phase_dominance["Linear (0-333)"]
    assert int(np.argmax(linear_counts)) == 0, (
        "at weight parity the context bonus must select the linear "
        f"specialist, got {list(linear_counts)}"
    )

    # Late-phase routing is governed by accumulated weight, not by scope match.
    sinusoidal_counts = phase_dominance["Sinusoidal (667-999)"]
    sinusoidal_specialist = 2
    assert int(np.argmax(sinusoidal_counts)) != sinusoidal_specialist, (
        "this test documents that the +2.0 context bonus loses to accumulated "
        "weight; if routing now matches the specialist, the bonus or the "
        f"accumulation dynamics changed. counts={list(sinusoidal_counts)}"
    )

    final_weights = conditions["atp"]["weights_history"][-1]
    assert float(np.max(final_weights)) > 2.0 * 10, (
        "accumulated weight should dwarf the flat context bonus; got "
        f"max weight {float(np.max(final_weights)):.2f}"
    )
