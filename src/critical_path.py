"""
Module 5: Critical path computation.

The critical path is the chain of spans that actually determined the trace's
end-to-end (wall-clock) latency -- NOT the sum of all span durations, which
double-counts concurrent work and will typically exceed the root span's own
duration.

Algorithm: starting at the root, repeatedly step into whichever direct child
finished LAST (max end_ns). That child is the one that gated how soon the
parent could finish; everything else running alongside it was "free" (already
hidden inside the wall-clock time). Recurse until a leaf is reached.
"""


def compute_critical_path(tree):
    """Returns {
        'critical_path': [span_id, ...]  (root -> leaf, in call order),
        'critical_path_duration_ns': int,   # = root span's own duration
        'critical_spans': [ {span_id, service, operation, duration_ns, contribution_pct}, ... ]
    }
    """
    spans = tree["spans"]
    children_map = tree["children"]
    root_id = tree["root"]
    root = spans[root_id]
    total_duration = root["duration_ns"]

    path = [root_id]
    current = root_id
    while True:
        child_ids = children_map.get(current, [])
        if not child_ids:
            break
        # pick the child that ends latest -- it's the one gating the parent
        next_span = max(child_ids, key=lambda cid: spans[cid]["start_ns"] + spans[cid]["duration_ns"])
        path.append(next_span)
        current = next_span

    critical_spans = []
    for sid in path:
        row = spans[sid]
        pct = (row["duration_ns"] / total_duration * 100) if total_duration else 0.0
        critical_spans.append({
            "span_id": sid, "service": row["service"], "operation": row["operation"],
            "start_ns": row["start_ns"], "duration_ns": row["duration_ns"],
            "contribution_pct": round(pct, 1),
        })

    return {
        "trace_id": list(spans.values())[0]["trace_id"] if spans else None,
        "critical_path": path,
        "critical_path_duration_ns": total_duration,
        "critical_spans": critical_spans,
    }


def compute_critical_paths_all(trees):
    return {tid: compute_critical_path(tree) for tid, tree in trees.items()}
