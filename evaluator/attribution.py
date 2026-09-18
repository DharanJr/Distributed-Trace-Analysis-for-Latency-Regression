"""
attribution.py
---------------
Independent checks for root-cause and deployment attribution
(Test Cases 17-18).

Root cause check: for a set of services all showing elevated latency,
figure out which one is the actual SOURCE (its own self-time got
worse) versus which ones are just downstream VICTIMS (their total
duration got worse only because they call the slow service, but their
own self-time did not change).

Deployment attribution: given the detected regression start time,
find which deployment event is closest to it in time, within a
tolerance window.
"""

import pandas as pd


def rank_root_cause_candidates(self_time_before: dict, self_time_after: dict) -> pd.DataFrame:
    """self_time_before / self_time_after: {service_name: median_self_time}.
    Returns services ranked by how much their OWN self-time (not total
    duration) increased. The true root cause should show a large jump
    here; pure downstream victims should show little or no change.
    """
    rows = []
    for service in self_time_before:
        before = self_time_before[service]
        after = self_time_after.get(service, before)
        delta = after - before
        pct = (delta / before * 100) if before else float("inf")
        rows.append({
            "service": service,
            "self_time_before": before,
            "self_time_after": after,
            "self_time_delta": delta,
            "self_time_pct_change": pct,
        })
    return pd.DataFrame(rows).sort_values("self_time_delta", ascending=False).reset_index(drop=True)


def attribute_deployment(regression_start_time, deploy_events: pd.DataFrame,
                          service: str = None, window_ms=15 * 60 * 1000) -> dict:
    """deploy_events must have columns: service, deploy_time, deploy_id
    (see config.DEPLOY_COLUMNS mapping — rename before calling this).

    Returns the closest deployment within `window_ms` of the regression
    start time, optionally restricted to a specific service.
    """
    candidates = deploy_events
    if service is not None:
        candidates = candidates[candidates["service"] == service]

    candidates = candidates.copy()
    candidates["time_diff_ms"] = (candidates["deploy_time"] - regression_start_time).abs()
    candidates = candidates[candidates["time_diff_ms"] <= window_ms]
    candidates = candidates.sort_values("time_diff_ms")

    if candidates.empty:
        return {"match_found": False, "candidates": []}

    best = candidates.iloc[0]
    return {
        "match_found": True,
        "best_match": {
            "deploy_id": best["deploy_id"],
            "service": best["service"],
            "deploy_time": best["deploy_time"],
            "time_diff_ms": best["time_diff_ms"],
        },
        "all_candidates_within_window": candidates.to_dict("records"),
    }
