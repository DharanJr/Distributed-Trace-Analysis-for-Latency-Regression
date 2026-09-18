"""
Module 6: Per-service / per-operation latency statistics.

Percentiles are always computed per (service, operation) -- never per service
alone -- because mixing e.g. a 2ms cache read with a 400ms search under one
"service-level" number produces a percentile that describes nothing real.
Failed requests (status_code >= 400) are excluded from latency percentiles
since they typically fail fast and would drag the distribution down,
potentially masking a real regression; error_rate is reported separately.
"""
import numpy as np
import pandas as pd


def compute_latency_stats(spans_df, period=None):
    """period: None (all data), 'BEFORE', or 'AFTER' -- caller must have already
    filtered/tagged the dataframe with a 'period' column if using this arg."""
    df = spans_df if period is None else spans_df[spans_df["period"] == period]

    rows = []
    for (service, operation), group in df.groupby(["service", "operation"]):
        ok = group[group["status_code"] < 400]
        durations_ms = ok["duration_ns"].to_numpy() / 1e6
        n = len(durations_ms)
        error_rate = 1 - (len(ok) / len(group)) if len(group) else 0.0
        if n == 0:
            continue
        rows.append({
            "service": service, "operation": operation, "count": n,
            "error_rate": round(error_rate, 4),
            "mean_ms": round(float(np.mean(durations_ms)), 2),
            "median_ms": round(float(np.median(durations_ms)), 2),
            "p50_ms": round(float(np.percentile(durations_ms, 50)), 2),
            "p95_ms": round(float(np.percentile(durations_ms, 95)), 2),
            "p99_ms": round(float(np.percentile(durations_ms, 99)), 2),
            "low_confidence": n < 30,  # rule-of-thumb floor for a meaningful P99
        })
    return pd.DataFrame(rows).sort_values(["service", "operation"]).reset_index(drop=True)
