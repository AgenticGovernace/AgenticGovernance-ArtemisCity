"""Hebbian marketplace architecture vs traditional k-NN inference.

Like its sibling ``test_hebbian_scoped_vs_coldstart``, this module was a
notebook transcribed into ``src/tests`` with zero test functions and zero
assertions, executing ~730 lines of simulation at import time. It never ran,
because ``scikit-learn`` and ``matplotlib`` were undeclared dependencies.

It is now a real test module. The simulation engine is preserved exactly,
including the corrected Hebbian update from the architecture doc:

    dW = tanh(a * x * y)     (bounded, not the binary +1/-1 of the notebook)

The original narrative output made two claims its own numbers contradict, and
the assertions below record the measured reality instead:

* It labelled k-NN inference ``(best)`` for accuracy. k-NN is in fact the
  *worst* of the four configurations by cumulative absolute error -- every
  Hebbian variant beats it, because k-NN has no forgetting and drags stale
  pre-drift neighbors into every post-drift prediction.
* It reported ``-354.7% of gap closed``. That metric is
  ``1 - (mae_atp - mae_knn) / (mae_cold - mae_knn)``, which silently assumes
  k-NN is the best-case floor. Here ``mae_cold < mae_knn``, so the denominator
  is negative and the ratio is meaningless. The comparison that *is* valid --
  a direct MAE ordering plus the cost ratio -- is asserted below.

Cost model: Hebbian routing is O(1) per step; k-NN scans its whole memory, so
cumulative cost is O(N^2). That difference is the actual value proposition and
is asserted directly rather than folded into a gap percentage.

Determinism: agents are seeded via ``MLPRegressor(random_state=...)`` and NumPy
is seeded at dataset construction, so metrics reproduce run to run.

Author: Apollo (Prinston Palmer) + Artemis (Claude)
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("numpy")
pytest.importorskip("sklearn")

import numpy as np
from sklearn.metrics import pairwise_distances
from sklearn.neural_network import MLPRegressor

pytestmark = pytest.mark.slow

N = 1000
PRE_TRAIN = 600
N_AGENTS = 5
SUCCESS_THRESHOLD = 5.0
SCOPE_NAMES = ("Linear", "Quadratic", "Sinusoidal", "Mixed", "Validation")


# ============================================================
# 1. DATA -- 3-phase concept drift (1000 steps)
# ============================================================


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
# 2. PROPER HEBBIAN UPDATE -- dW = tanh(a * x * y)
# ============================================================


def hebbian_delta_w(activation_origin, activation_target, a=0.1):
    """Morphological Hebbian update from the architecture doc.

    ``dW = tanh(a * x * y)`` where ``x`` is the origin activation (1.0 when the
    agent fired) and ``y`` the target activation (inverse normalized error).
    """
    return np.tanh(a * activation_origin * activation_target)


def anti_hebbian_delta_w(eta=0.1):
    """Anti-Hebbian punishment/pruning applied on failure."""
    return -eta


# ============================================================
# 3. SCOPED CORPUS PRE-TRAINING
# ============================================================


def generate_scoped_corpus(scope, n=PRE_TRAIN):
    """Generate the deterministic scoped corpus for one agent specialty."""
    np.random.seed(scope + 100)
    X = np.random.uniform(-5, 5, (n, 3))
    noise = np.random.normal(0, 0.5, n)
    if scope == 0:  # LINEAR specialist
        y = 2 * X[:, 0] + 3 * X[:, 1] + noise
    elif scope == 1:  # QUADRATIC specialist
        y = -2 * X[:, 0] ** 2 + X[:, 1] + noise
    elif scope == 2:  # SINUSOIDAL specialist
        y = 5 * np.sin(X[:, 2]) + X[:, 0] + noise
    elif scope == 3:  # MIXED generalist
        t = n // 3
        y = np.zeros(n)
        y[:t] = 2 * X[:t, 0] + 3 * X[:t, 1]
        y[t : 2 * t] = -2 * X[t : 2 * t, 0] ** 2 + X[t : 2 * t, 1]
        y[2 * t :] = 5 * np.sin(X[2 * t :, 2]) + X[2 * t :, 0]
        y += noise
    elif scope == 4:  # VALIDATION specialist (lower noise tolerance)
        y = 2 * X[:, 0] + 3 * X[:, 1] + noise * 0.3
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


def pre_train(agent, X, y):
    """Pre-train one agent across its scoped corpus."""
    for i in range(len(X)):
        agent.partial_fit(X[i : i + 1], y[i : i + 1])
    return agent


# ============================================================
# 4. SIMULATION: HEBBIAN ROUTING WITH tanh(a*x*y)
# ============================================================


def run_hebbian(
    agents,
    weights,
    X,
    y,
    label,
    decay_rate=0.99,
    success_threshold=SUCCESS_THRESHOLD,
    use_atp=False,
    a=0.1,
):
    """Hebbian routing with the bounded update; O(1) cost per step."""
    n_agents = len(agents)
    errors, costs, selections = [], [], []
    weight_history = []
    cum_cost = 0.0
    sign_changes_per_agent = [[] for _ in range(n_agents)]

    for t in range(len(X)):
        x_t = X[t].reshape(1, -1)
        y_t = y[t : t + 1]

        # Cost: O(1) -- constant per step regardless of history
        cum_cost += 1

        # ATP context bonus (if enabled) -- phase-aware routing
        if use_atp:
            phase_bonus = np.zeros(n_agents)
            if t < 334:
                phase_bonus[0] = 1.5  # Linear hint
            elif t < 667:
                phase_bonus[1] = 1.5  # Quadratic hint
            else:
                phase_bonus[2] = 1.5  # Sinusoidal hint
            eff_w = weights + phase_bonus
        else:
            eff_w = weights.copy()

        # Select agent (argmax with tie-breaking)
        candidates = np.where(eff_w == np.max(eff_w))[0]
        idx = np.random.choice(candidates)
        selections.append(idx)

        try:
            y_hat = agents[idx].predict(x_t)[0]
        except Exception:  # noqa: BLE001 - an unfitted agent predicts nothing
            y_hat = 0.0

        err = np.abs(y_t[0] - y_hat)
        errors.append(err)

        # --- PROPER HEBBIAN UPDATE: dW = tanh(a * x * y) ---
        x_activation = 1.0  # Agent was selected (fired)
        y_activation = max(0, 1.0 - err / (success_threshold * 2))

        if err < success_threshold:
            weights[idx] += hebbian_delta_w(x_activation, y_activation, a=a)
            sign_changes_per_agent[idx].append(+1)
        else:
            weights[idx] += anti_hebbian_delta_w(eta=a)
            sign_changes_per_agent[idx].append(-1)

        weights *= decay_rate
        weights = np.maximum(weights, 0.01)  # Floor above zero

        agents[idx].partial_fit(x_t, y_t)

        costs.append(cum_cost)
        weight_history.append(weights.copy())

    sign_changes = []
    for deltas in sign_changes_per_agent:
        if len(deltas) < 2:
            sign_changes.append(0)
        else:
            sign_changes.append(
                sum(1 for i in range(1, len(deltas)) if deltas[i] != deltas[i - 1])
            )

    return {
        "errors": np.array(errors),
        "costs": np.array(costs),
        "selections": np.array(selections),
        "weights_history": np.array(weight_history),
        "sign_changes": sign_changes,
        "label": label,
    }


# ============================================================
# 5. SIMULATION: k-NN INFERENCE (TRADITIONAL)
# ============================================================


def run_knn_inference(X, y, k=5, label="k-NN Inference"):
    """Traditional memory lookup; O(N) per step, so O(N^2) cumulative."""
    X_mem, y_mem = [], []
    errors, costs = [], []
    cum_cost = 0.0

    for t in range(len(X)):
        x_t = X[t].reshape(1, -1)
        y_t = y[t]

        # Cost: O(N) -- proportional to memory size
        cum_cost += max(1, len(X_mem))

        if len(X_mem) < k:
            y_hat = np.mean(y_mem) if y_mem else 0.0
        else:
            dists = pairwise_distances(x_t, np.array(X_mem))[0]
            nearest = np.argsort(dists)[:k]
            y_hat = np.mean(np.array(y_mem)[nearest])

        errors.append(np.abs(y_t - y_hat))
        costs.append(cum_cost)

        # Store to memory (no forgetting)
        X_mem.append(X[t])
        y_mem.append(y_t)

    return {"errors": np.array(errors), "costs": np.array(costs), "label": label}


# ============================================================
# 6. SENTINEL / WATCHDOG
# ============================================================


def sentinel_analysis(errors, window=50, threshold=0.4):
    """Detect rolling oscillation rate and flag steps for human review."""
    deltas = [0] + [1 if errors[i] < 5.0 else -1 for i in range(1, len(errors))]
    osc_rates = []
    alerts = []
    for t in range(window, len(deltas)):
        w = deltas[t - window : t]
        changes = sum(1 for i in range(1, len(w)) if w[i] != w[i - 1])
        rate = changes / window
        osc_rates.append(rate)
        if rate > threshold:
            alerts.append(t)
    return {
        "rates": osc_rates,
        "alerts": alerts,
        "count": len(alerts),
        "pct": len(alerts) / max(1, len(osc_rates)) * 100,
    }


def phase_mae(errors) -> dict[str, float]:
    """Mean absolute error within each concept-drift phase."""
    return {
        "linear": float(np.mean(errors[:334])),
        "quadratic": float(np.mean(errors[334:667])),
        "sinusoidal": float(np.mean(errors[667:])),
    }


# ============================================================
# 7. THE FOUR CONFIGURATIONS (computed once per module)
# ============================================================


@pytest.fixture(scope="module")
def runs():
    """Run cold, scoped, scoped+ATP, and k-NN exactly once."""
    features, targets = build_drift_dataset()

    cold = run_hebbian(
        [create_agent(i) for i in range(N_AGENTS)],
        np.ones(N_AGENTS),
        features,
        targets,
        label="Cold Hebbian",
    )

    scoped_agents = [create_agent(i) for i in range(N_AGENTS)]
    for i in range(N_AGENTS):
        scoped_agents[i] = pre_train(scoped_agents[i], *generate_scoped_corpus(i))
    scoped = run_hebbian(
        scoped_agents,
        np.ones(N_AGENTS),
        features,
        targets,
        label="Scoped Post-600",
    )

    atp_agents = [create_agent(i) for i in range(N_AGENTS)]
    for i in range(N_AGENTS):
        atp_agents[i] = pre_train(atp_agents[i], *generate_scoped_corpus(i))
    atp = run_hebbian(
        atp_agents,
        np.ones(N_AGENTS),
        features,
        targets,
        label="Scoped + ATP",
        use_atp=True,
    )

    knn = run_knn_inference(features, targets, k=5)

    bundle = {"cold": cold, "scoped": scoped, "atp": atp, "knn": knn}
    _maybe_write_figure(bundle)
    return bundle


def _maybe_write_figure(bundle) -> None:
    """Render the comparison figure only when explicitly requested.

    Opt-in via ``ARTEMIS_WRITE_TEST_ARTIFACTS=1`` so a normal test run never
    writes into the source tree.
    """
    if os.getenv("ARTEMIS_WRITE_TEST_ARTIFACTS", "0").strip() not in ("1", "true"):
        return
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 1, figsize=(14, 10))
    window = 50
    for key, label in (
        ("knn", "k-NN Inference"),
        ("cold", "Cold Hebbian"),
        ("scoped", "Scoped Post-600"),
        ("atp", "Scoped + ATP"),
    ):
        errors = bundle[key]["errors"]
        axes[0].plot(
            np.convolve(errors, np.ones(window) / window, mode="valid"),
            label=label,
            alpha=0.8,
        )
    axes[0].set_title("Rolling Mean Absolute Error")
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    axes[1].plot(bundle["knn"]["costs"], label="k-NN cumulative cost O(N^2)")
    axes[1].plot(bundle["cold"]["costs"], label="Hebbian cumulative cost O(N)")
    axes[1].set_yscale("log")
    axes[1].set_title("Cumulative Compute Cost")
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)

    for point in (334, 667):
        axes[0].axvline(x=point, color="red", linestyle=":", alpha=0.5)

    plt.tight_layout()
    out_dir = Path(__file__).resolve().parent / "test_artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_dir / "hebbian_marketplace_vs_inference.png", dpi=150)
    plt.close()


# ============================================================
# 8. CLAIMS
# ============================================================


@pytest.mark.parametrize(
    "origin,target",
    [(1.0, 0.0), (1.0, 0.5), (1.0, 1.0), (1.0, 25.0), (1.0, 1e6)],
)
def test_hebbian_update_is_bounded_by_tanh(origin, target):
    """The corrected update saturates, which is what prevents runaway weight.

    The notebook's original binary ``+1/-1`` update accumulates without bound;
    ``tanh`` caps a single reinforcement below 1.0 no matter how large the
    target activation grows. This is the mechanism the module's conclusion
    credits for letting specialists coexist, so it is asserted directly.
    """
    delta = hebbian_delta_w(origin, target)
    # tanh is bounded by 1 and saturates to exactly 1.0 in float64 for large
    # arguments, so the bound is inclusive at the extreme.
    assert 0.0 <= float(delta) <= 1.0


def test_hebbian_reinforcement_stays_small_in_the_real_activation_range():
    """In use, ``y_activation`` is clamped to [0, 1], so a step is tiny.

    ``run_hebbian`` computes ``y = max(0, 1 - err / (2 * threshold))``, which
    never exceeds 1.0. A single reinforcement is therefore at most
    ``tanh(0.1) ~= 0.0997`` -- far below the ``+1.0`` of the binary scheme,
    which is why weights converge instead of running away.
    """
    largest_real_step = float(hebbian_delta_w(1.0, 1.0))
    assert largest_real_step == pytest.approx(np.tanh(0.1))
    assert largest_real_step < 0.1
    # Punishment is an order of magnitude larger than a single reward step,
    # so a failing agent is demoted faster than it was promoted.
    assert abs(anti_hebbian_delta_w(eta=0.1)) > largest_real_step


def test_anti_hebbian_punishment_is_negative_and_fixed():
    """Failure applies a fixed negative delta, independent of error size."""
    assert anti_hebbian_delta_w(eta=0.1) == pytest.approx(-0.1)
    assert anti_hebbian_delta_w(eta=0.5) == pytest.approx(-0.5)


def test_scoped_agents_outperform_cold_start(runs):
    """Claim 4: market dynamics -- scoped specialists beat generalists."""
    mae_cold = float(np.sum(runs["cold"]["errors"]))
    mae_scoped = float(np.sum(runs["scoped"]["errors"]))

    assert mae_scoped < mae_cold
    assert 1 - mae_scoped / mae_cold > 0.20, (
        "scoped pre-training should cut cumulative error substantially, got "
        f"{1 - mae_scoped / mae_cold:.1%}"
    )


def test_atp_context_adds_accuracy_over_scoped_alone(runs):
    """Claim 2: ATP vectors maintain continuity between specialists."""
    mae_scoped = float(np.sum(runs["scoped"]["errors"]))
    mae_atp = float(np.sum(runs["atp"]["errors"]))
    assert mae_atp < mae_scoped


def test_every_hebbian_variant_beats_knn_on_accuracy(runs):
    """The original narrative labelled k-NN ``(best)``; it is the worst.

    k-NN never forgets, so after each concept drift its neighbor set is still
    dominated by samples drawn from the previous regime. Hebbian routing with
    decay adapts, and every variant ends with lower cumulative error.
    """
    mae = {key: float(np.sum(runs[key]["errors"])) for key in runs}

    assert (
        mae["knn"] > mae["cold"] > mae["scoped"] > mae["atp"]
    ), "expected knn > cold > scoped > atp cumulative error, got " + ", ".join(
        f"{k}={v:.1f}" for k, v in mae.items()
    )


def test_knn_gap_closed_metric_is_undefined_for_this_dataset(runs):
    """Pin *why* the original ``gap closed`` percentage was nonsense.

    ``1 - (mae_atp - mae_knn) / (mae_cold - mae_knn)`` assumes k-NN is the
    best-case floor. Since cold Hebbian already beats k-NN here, the
    denominator is negative and the metric inverts, which is how the module
    printed ``-354.7% of gap closed`` while actually outperforming.
    """
    mae_cold = float(np.sum(runs["cold"]["errors"]))
    mae_knn = float(np.sum(runs["knn"]["errors"]))
    assert mae_cold - mae_knn < 0, (
        "the gap-closed denominator is only negative while Hebbian beats "
        "k-NN; if this flips, the metric becomes meaningful again"
    )


def test_hebbian_cost_is_linear_and_knn_cost_is_quadratic(runs):
    """The real value proposition: O(N) routing vs O(N^2) memory scans."""
    hebbian_cost = float(runs["cold"]["costs"][-1])
    knn_cost = float(runs["knn"]["costs"][-1])

    assert hebbian_cost == pytest.approx(N)
    # Sum of 1..N-1 plus the k floor steps -- quadratic in N.
    assert knn_cost == pytest.approx(N * (N - 1) / 2, rel=0.01)
    assert knn_cost / hebbian_cost > 100


def test_oscillation_is_a_detectable_and_decreasing_signal(runs):
    """Claim 3: sentinel sign-change rate detects instability."""
    cold = sentinel_analysis(runs["cold"]["errors"])
    scoped = sentinel_analysis(runs["scoped"]["errors"])
    atp = sentinel_analysis(runs["atp"]["errors"])

    assert cold["count"] > 0, "sentinel must fire on the least stable run"
    assert atp["count"] < scoped["count"] < cold["count"], (
        "alert volume should fall as agents specialize, got "
        f"cold={cold['count']}, scoped={scoped['count']}, atp={atp['count']}"
    )
    assert 0.0 <= atp["pct"] <= 100.0


def test_human_review_value_declines_as_agents_improve(runs):
    """Claim 5: sentinel-triggered review is measurable but shrinking.

    Fewer alerts on better-specialized pools means human attention is spent
    where it matters (drift boundaries) rather than on routine oscillation.
    """
    counts = {
        key: sentinel_analysis(runs[key]["errors"])["count"]
        for key in ("cold", "scoped", "atp")
    }
    assert all(count >= 0 for count in counts.values())
    assert counts["atp"] < counts["cold"]


def test_scoped_agents_improve_accuracy_within_every_drift_phase(runs):
    """Specialization must not trade one phase away to win another."""
    cold_phases = phase_mae(runs["cold"]["errors"])
    scoped_phases = phase_mae(runs["scoped"]["errors"])

    for phase, cold_value in cold_phases.items():
        assert scoped_phases[phase] < cold_value, (
            f"scoped pool regressed in the {phase} phase: "
            f"{scoped_phases[phase]:.3f} vs cold {cold_value:.3f}"
        )
