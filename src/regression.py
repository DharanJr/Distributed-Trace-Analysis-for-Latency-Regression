"""
Module 7: Tail-latency regression detection with multiple-testing control.

For every (service, operation), compares the BEFORE vs AFTER duration
distributions:
  - log-transform durations first (latency is right-skewed; comparing raw
    P99 deltas by eye, or testing raw values, is misleading and the log
    transform is what makes the two-sample test behave).
  - Mann-Whitney U (non-parametric, doesn't assume normality, works on
    independent samples) on the log-durations.
  - Benjamini-Hochberg FDR correction across ALL endpoints tested at once,
    since testing hundreds of endpoints simultaneously inflates false
    positives if each is judged at raw p<0.05.
  - "significant" alone is not enough to call something a regression: we
    additionally require the P99 to have grown past a practical threshold,
    so a statistically-detectable-but-trivial 2% wobble doesn't get flagged.
"""
import numpy as np
import pandas as pd
from scipy import stats

FDR_ALPHA = 0.05
PRACTICAL_P99_INCREASE_PCT = 20.0  # must also grow by at least this much to count


def benjamini_hochberg(p_values, alpha=FDR_ALPHA):
    """Manual BH-FDR. Returns (adjusted_p_values, reject_bool_array), both in
    the ORIGINAL input order."""
    p = np.asarray(p_values, dtype=float)
    n = len(p)
    if n == 0:
        return np.array([]), np.array([], dtype=bool)
    order = np.argsort(p)
    ranked = p[order]
    ranks = np.arange(1, n + 1)
    adj_sorted = ranked * n / ranks
    # enforce monotonicity (step-up procedure)
    adj_sorted = np.minimum.accumulate(adj_sorted[::-1])[::-1]
    adj_sorted = np.clip(adj_sorted, 0, 1)

    adjusted = np.empty(n)
    adjusted[order] = adj_sorted
    reject = adjusted <= alpha
    return adjusted, reject


def detect_regressions(spans_df, practical_threshold_pct=PRACTICAL_P99_INCREASE_PCT,
                        fdr_alpha=FDR_ALPHA):
    """spans_df must have a 'period' column with values 'BEFORE'/'AFTER'.
    Returns a DataFrame, one row per (service, operation) tested, with before/
    after percentiles, the raw and FDR-adjusted p-values, and a boolean
    'regression' flag."""
    ok = spans_df[spans_df["status_code"] < 400].copy()
    rows = []
    p_values = []

    for (service, operation), group in ok.groupby(["service", "operation"]):
        before = group[group["period"] == "BEFORE"]["duration_ns"].to_numpy() / 1e6
        after = group[group["period"] == "AFTER"]["duration_ns"].to_numpy() / 1e6
        if len(before) < 5 or len(after) < 5:
            continue  # not enough samples in one of the periods to test meaningfully

        log_before = np.log(before)
        log_after = np.log(after)
        try:
            _, p_value = stats.mannwhitneyu(log_before, log_after, alternative="two-sided")
        except ValueError:
            p_value = 1.0

        before_p99 = float(np.percentile(before, 99))
        after_p99 = float(np.percentile(after, 99))
        change_pct = ((after_p99 - before_p99) / before_p99 * 100) if before_p99 > 0 else 0.0

        rows.append({
            "service": service, "operation": operation,
            "before_count": len(before), "after_count": len(after),
            "before_p50": round(float(np.percentile(before, 50)), 2),
            "before_p95": round(float(np.percentile(before, 95)), 2),
            "before_p99": round(before_p99, 2),
            "after_p50": round(float(np.percentile(after, 50)), 2),
            "after_p95": round(float(np.percentile(after, 95)), 2),
            "after_p99": round(after_p99, 2),
            "change_pct": round(change_pct, 1),
            "p_value": p_value,
        })
        p_values.append(p_value)

    result = pd.DataFrame(rows)
    if result.empty:
        result["adjusted_p_value"] = []
        result["statistically_significant"] = []
        result["regression"] = []
        return result

    adjusted, reject = benjamini_hochberg(result["p_value"].to_numpy(), alpha=fdr_alpha)
    result["adjusted_p_value"] = np.round(adjusted, 5)
    result["statistically_significant"] = reject
    result["regression"] = result["statistically_significant"] & (result["change_pct"] >= practical_threshold_pct)
    return result.sort_values("change_pct", ascending=False).reset_index(drop=True)
