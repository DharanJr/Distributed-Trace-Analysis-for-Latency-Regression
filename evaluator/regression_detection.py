"""
regression_detection.py
------------------------
Independent statistical check for "did latency really get worse"
(Test Cases 12-16). This is what you use to verify the Builder isn't
just eyeballing a percentage increase.

Two tools:
1. mann_whitney_regression_test — compares a "before" window vs an
   "after" window for one service using the Mann-Whitney U test
   (doesn't assume normal distribution, which latency data rarely is).
2. false_positive_rate_check — repeatedly splits a known-STABLE period
   randomly into two halves and re-runs the same test, to see how
   often it fires on nothing. Should land close to your alpha
   (e.g. ~5% of the time at p < 0.05).
"""

import numpy as np
from scipy import stats


def mann_whitney_regression_test(before: np.ndarray, after: np.ndarray, alpha=0.05) -> dict:
    before = np.asarray(before, dtype=float)
    after = np.asarray(after, dtype=float)

    stat, p_value = stats.mannwhitneyu(before, after, alternative="less")
    # alternative="less" tests: is `before` stochastically LESS than `after`,
    # i.e. did things get worse (higher latency) in the after window.

    median_before = float(np.median(before))
    median_after = float(np.median(after))
    pct_change = ((median_after - median_before) / median_before * 100) if median_before else float("inf")

    return {
        "p_value": float(p_value),
        "significant": p_value < alpha,
        "median_before": median_before,
        "median_after": median_after,
        "pct_change_median": pct_change,
        "n_before": len(before),
        "n_after": len(after),
    }


def bonferroni_correct(p_values: dict, alpha=0.05) -> dict:
    """When testing many services at once, apply a multiple-comparisons
    correction so you don't get false positives just from running many
    tests. p_values: {service_name: p_value}."""
    n = len(p_values)
    corrected_alpha = alpha / n if n else alpha
    return {
        service: {
            "p_value": p,
            "corrected_alpha": corrected_alpha,
            "significant_after_correction": p < corrected_alpha,
        }
        for service, p in p_values.items()
    }


def false_positive_rate_check(stable_period_data: np.ndarray, n_trials=200, alpha=0.05, seed=42) -> dict:
    """Randomly splits a KNOWN-STABLE (no real regression) period into
    two halves many times, and counts how often the test wrongly fires.
    This is your empirical false-positive rate — it should be close to
    `alpha` (e.g. ~5%). If it's much higher, the Builder's test/threshold
    is not well-calibrated."""
    rng = np.random.default_rng(seed)
    data = np.asarray(stable_period_data, dtype=float)
    false_positives = 0

    for _ in range(n_trials):
        shuffled = rng.permutation(data)
        half = len(shuffled) // 2
        before, after = shuffled[:half], shuffled[half:]
        _, p_value = stats.mannwhitneyu(before, after, alternative="two-sided")
        if p_value < alpha:
            false_positives += 1

    rate = false_positives / n_trials
    return {
        "trials": n_trials,
        "false_positives": false_positives,
        "empirical_false_positive_rate": rate,
        "expected_rate": alpha,
        "reasonably_calibrated": abs(rate - alpha) < 0.05,  # within 5 percentage points
    }


def find_regression_window(df, service, time_col="start_time", duration_col="duration",
                            window_size_ms=10 * 60 * 1000, step_ms=5 * 60 * 1000, alpha=0.05):
    """Scans through time in sliding windows for one service, comparing
    each window to the very first window (treated as the stable
    baseline), and returns the earliest window where a significant,
    sustained regression starts. Use this to independently locate
    *when* the regression begins, to compare against the Builder's
    reported time and against your known ground truth.
    """
    service_df = df[df["service"] == service].sort_values(time_col)
    if service_df.empty:
        return {"error": f"no data for service {service}"}

    t_min = service_df[time_col].min()
    t_max = service_df[time_col].max()

    baseline_end = t_min + window_size_ms
    baseline = service_df[(service_df[time_col] >= t_min) & (service_df[time_col] < baseline_end)][duration_col].values

    results = []
    t = baseline_end
    while t + window_size_ms <= t_max:
        window_data = service_df[(service_df[time_col] >= t) & (service_df[time_col] < t + window_size_ms)][duration_col].values
        if len(window_data) >= 5 and len(baseline) >= 5:
            test = mann_whitney_regression_test(baseline, window_data, alpha=alpha)
            test["window_start"] = t
            test["window_end"] = t + window_size_ms
            results.append(test)
        t += step_ms

    first_regression = next((r for r in results if r["significant"]), None)

    return {
        "service": service,
        "baseline_window": (t_min, baseline_end),
        "all_windows": results,
        "first_detected_regression_start": first_regression["window_start"] if first_regression else None,
    }
