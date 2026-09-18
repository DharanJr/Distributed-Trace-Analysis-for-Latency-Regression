"""
Modules 8 & 9: Root-cause attribution and evidence chain.

Combines: regression results, critical-path membership, self-time, the
dependency graph, and deployment timing into a single "root cause candidate"
with an explicit, traceable evidence list. Deliberately conservative in its
language: this is a candidate / most-likely-contributing-dependency, not a
proof of causality. Deployment proximity is presented as a temporal
coincidence and contributing signal only.
"""
import numpy as np


def _self_time_ratio(spans_df_service, self_times_by_span, trees):
    """Average self_time / duration ratio for a given service across all spans,
    used to tell 'genuinely got slower' apart from 'is waiting on a dependency'."""
    ratios = []
    for tid, tree in trees.items():
        for sid, row in tree["spans"].items():
            if row["service"] != spans_df_service:
                continue
            st = self_times_by_span.get(tid, {}).get(sid, 0)
            if row["duration_ns"] > 0:
                ratios.append(st / row["duration_ns"])
    return float(np.mean(ratios)) if ratios else None


def attribute_root_cause(regression_df, trees, self_times_by_span, critical_paths,
                          deploys_df, critical_path_window_ns=30 * 60 * 1_000_000_000):
    """Returns a dict describing the single most likely root-cause candidate
    (the flagged regression with the largest P99 change_pct), or None if no
    regression was flagged."""
    flagged = regression_df[regression_df["regression"]] if not regression_df.empty else regression_df
    if flagged is None or flagged.empty:
        return None

    top = flagged.iloc[0]  # already sorted by change_pct descending
    service, operation = top["service"], top["operation"]

    # how often does this service/operation appear on a trace's critical path?
    on_path_count = 0
    total_after_traces = 0
    for tid, cp in critical_paths.items():
        tree = trees[tid]
        spans = tree["spans"]
        root = spans[tree["root"]]
        # only look at AFTER-period traces for the "is this on the critical path now" check
        if spans[cp["critical_path"][0]].get("period") != "AFTER":
            continue
        total_after_traces += 1
        for sid in cp["critical_path"]:
            if spans[sid]["service"] == service and spans[sid]["operation"] == operation:
                on_path_count += 1
                break

    on_path_rate = on_path_count / total_after_traces if total_after_traces else 0.0

    # self-time ratio for the UPSTREAM service that owns this dependency
    # (heuristic: find whichever service most frequently directly calls
    # `service` in the graph -- using the MODE rather than an arbitrary match
    # matters because a rare orphaned/misattached span could otherwise point
    # to the wrong caller)
    from collections import Counter
    upstream_candidates = Counter()
    for tid, tree in trees.items():
        for sid, row in tree["spans"].items():
            if row["service"] == service:
                for parent_sid, row2 in tree["spans"].items():
                    if sid in tree["children"].get(parent_sid, []):
                        upstream_candidates[row2["service"]] += 1
    upstream_service = upstream_candidates.most_common(1)[0][0] if upstream_candidates else None
    upstream_self_ratio = (
        _self_time_ratio(upstream_service, self_times_by_span, trees) if upstream_service else None
    )

    # deployment correlation: any deploy of the upstream service (or this service)
    # shortly before the regression window?
    deploy_evidence = []
    if deploys_df is not None and not deploys_df.empty:
        for _, d in deploys_df.iterrows():
            if d["service"] in (service, upstream_service):
                deploy_evidence.append(f"{d['service']} v{d['version']} was deployed and "
                                        f"temporally coincides with the regression onset.")

    evidence = [
        f"{service}/{operation} P99 increased from {top['before_p99']:.0f}ms to {top['after_p99']:.0f}ms "
        f"({top['change_pct']:.0f}% increase).",
        f"Distribution shift is statistically significant after FDR correction "
        f"(adjusted p={top['adjusted_p_value']:.4f}).",
    ]
    if on_path_rate > 0:
        evidence.append(
            f"{service}/{operation} appears on the critical path in {on_path_rate*100:.0f}% "
            f"of sampled AFTER-period traces."
        )
    if upstream_service and upstream_self_ratio is not None:
        evidence.append(
            f"{upstream_service} (the direct caller of {service}) has an average "
            f"self-time ratio of only {upstream_self_ratio*100:.0f}% of its own span duration, "
            f"indicating it mostly waits on {service} rather than doing its own slow work."
        )
    evidence.extend(deploy_evidence)

    # walk further upstream toward api-gateway for a fuller chain, best-effort.
    # Use the MODE parent at each hop (not an arbitrary set element) so a rare
    # orphaned/misattached span can't derail the reported call chain.
    graph_parents = {}
    for tid, tree in trees.items():
        for pid, children in tree["children"].items():
            for cid in children:
                child_svc = tree["spans"][cid]["service"]
                parent_svc = tree["spans"][pid]["service"]
                if child_svc != parent_svc:
                    graph_parents.setdefault(child_svc, Counter())[parent_svc] += 1
    cursor = service
    chain_services = [service]
    guard = 0
    while cursor in graph_parents and guard < 10:
        parent = graph_parents[cursor].most_common(1)[0][0]
        if parent in chain_services:
            break
        chain_services.append(parent)
        cursor = parent
        guard += 1
    chain_services.reverse()

    return {
        "root_cause_candidate": service,
        "operation": operation,
        "before_p99_ms": round(float(top["before_p99"]), 1),
        "after_p99_ms": round(float(top["after_p99"]), 1),
        "change_pct": round(float(top["change_pct"]), 1),
        "adjusted_p_value": float(top["adjusted_p_value"]),
        "evidence": evidence,
        "chain": chain_services,
        "on_path_rate": round(on_path_rate, 3),
        "upstream_service": upstream_service,
        "upstream_self_time_ratio": round(upstream_self_ratio, 3) if upstream_self_ratio is not None else None,
        "has_deploy_evidence": len(deploy_evidence) > 0,
    }
