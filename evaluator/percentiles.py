"""
percentiles.py
--------------
Independent p99/p95/p50 calculation (Test Cases 10-11), plus the
sanity check that p50 <= p95 <= p99.
"""

import numpy as np
import pandas as pd


def compute_percentiles(durations, percentiles=(50, 95, 99)) -> dict:
    arr = np.asarray(durations, dtype=float)
    arr = arr[~np.isnan(arr)]
    result = {f"p{p}": float(np.percentile(arr, p)) for p in percentiles}
    result["count"] = len(arr)
    result["mean"] = float(arr.mean()) if len(arr) else None
    return result


def percentiles_by_service(df: pd.DataFrame, service_col="service", duration_col="duration",
                            time_col=None, window=None) -> pd.DataFrame:
    """window: optional (start, end) tuple to restrict to a time range
    before computing percentiles per service."""
    data = df
    if window is not None and time_col is not None:
        start, end = window
        data = data[(data[time_col] >= start) & (data[time_col] < end)]

    rows = []
    for service, group in data.groupby(service_col):
        stats = compute_percentiles(group[duration_col])
        stats["service"] = service
        rows.append(stats)

    out = pd.DataFrame(rows).set_index("service")
    out["ordering_ok"] = (out["p50"] <= out["p95"] + 1e-9) & (out["p95"] <= out["p99"] + 1e-9)
    return out


def compare_to_reference(computed: float, reference: float, tolerance_pct: float) -> dict:
    """Compares your independently computed value against the Builder's
    reported value, within a relative tolerance percentage."""
    if reference == 0:
        diff_pct = float("inf") if computed != 0 else 0.0
    else:
        diff_pct = abs(computed - reference) / abs(reference) * 100
    return {
        "computed": computed,
        "builder_reported": reference,
        "diff_pct": diff_pct,
        "within_tolerance": diff_pct <= tolerance_pct,
    }
