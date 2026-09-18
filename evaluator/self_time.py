"""
self_time.py
------------
Computes self-time correctly: a span's own duration minus the
NON-OVERLAPPING time covered by its children (Test Cases 5-7).

The key trick, and the most common bug in Builder implementations:
if a span has two children that overlap each other, you must MERGE
their intervals before subtracting — otherwise you double-subtract
the overlapping region and can end up with a negative self-time.
"""

import pandas as pd

from trace_builder import SpanNode, build_trace_tree


def merge_intervals(intervals):
    """intervals: list of (start, end) tuples. Returns merged,
    non-overlapping, sorted intervals."""
    if not intervals:
        return []
    intervals = sorted(intervals, key=lambda iv: iv[0])
    merged = [list(intervals[0])]
    for start, end in intervals[1:]:
        last = merged[-1]
        if start <= last[1]:  # overlaps or touches -> merge
            last[1] = max(last[1], end)
        else:
            merged.append([start, end])
    return [(s, e) for s, e in merged]


def total_covered(intervals) -> float:
    """Sum of merged interval lengths."""
    return sum(e - s for s, e in merge_intervals(intervals))


def compute_self_time(node: SpanNode) -> float:
    """Self-time for a single node, given its children are already
    populated (see trace_builder.build_trace_tree)."""
    if not node.children:
        return node.duration

    child_intervals = [(c.start, c.end) for c in node.children]
    covered = total_covered(child_intervals)

    # Clip covered time to the parent's own window, in case a child's
    # timestamps run slightly outside the parent's (clock skew) —
    # otherwise self-time could go negative from a data artifact
    # rather than a real calculation bug.
    clipped = min(covered, node.duration)

    return node.duration - clipped


def compute_self_times_for_trace(nodes_by_id: dict) -> dict:
    """Returns {span_id: self_time} for every span in the trace."""
    return {span_id: compute_self_time(node) for span_id, node in nodes_by_id.items()}


def compute_self_time_dataset(df: pd.DataFrame) -> pd.Series:
    """Computes self-time for EVERY span across the whole dataset (all
    traces), not just one sample trace. This is what root-cause
    attribution should actually rank on — total span *duration* mixes
    in downstream slowness, but self-time isolates each service's own
    contribution. Returns a pandas Series aligned to df's index.

    Note: this loops once per trace (grouping by trace_id), which for
    ~200,000 spans across a few thousand traces typically finishes in
    well under a minute. If your dataset has many more traces, consider
    running this on a sampled subset of traces per service/time-window
    instead of the full dataset.
    """
    self_time_by_span_id = {}
    for _, group in df.groupby("trace_id"):
        _, nodes_by_id = build_trace_tree(group)
        self_time_by_span_id.update(compute_self_times_for_trace(nodes_by_id))

    return df["span_id"].map(self_time_by_span_id)


def sanity_check_self_times(nodes_by_id: dict, roots) -> dict:
    """Test Case 7 (corrected): the ONLY invariant that must always hold
    is per-node: 0 <= self_time(node) <= duration(node). That check is
    reported for every span here.

    IMPORTANT NOTE ON A COMMON MISCONCEPTION: it is tempting to also
    assert that the SUM of self-times across an entire trace can never
    exceed the root span's wall-clock duration. That is only true if
    the trace has no concurrency. If two children of the same parent
    run in PARALLEL (e.g. two services called concurrently, each doing
    real work on its own thread), their self-times each count real work
    time, and the sum of all self-times in the trace can legitimately
    EXCEED the root's wall-clock duration. That is correct behavior,
    not a bug — it reflects "total work done" rather than "wall-clock
    time elapsed." We still report the sum for visibility, but we do
    NOT fail the check purely because sum > root_duration; we only fail
    if an individual span's self-time falls outside [0, duration].
    """
    self_times = compute_self_times_for_trace(nodes_by_id)
    report = {}
    for root in roots:
        stack = [root]
        total = 0.0
        out_of_bounds_spans = []
        while stack:
            n = stack.pop()
            st = self_times[n.span_id]
            if st < -1e-6 or st > n.duration + 1e-6:
                out_of_bounds_spans.append(
                    {"span_id": n.span_id, "self_time": st, "duration": n.duration}
                )
            total += st
            stack.extend(n.children)
        report[root.span_id] = {
            "sum_self_time_across_trace": total,
            "root_duration": root.duration,
            "note": "sum_self_time may legitimately exceed root_duration if the trace has concurrent/parallel spans",
            "all_spans_within_individual_bounds": len(out_of_bounds_spans) == 0,
            "out_of_bounds_spans": out_of_bounds_spans,
        }
    return report
