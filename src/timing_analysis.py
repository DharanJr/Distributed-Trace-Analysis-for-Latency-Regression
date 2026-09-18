"""
Module 4: Self-time computation.

self_time = span duration MINUS the UNION of its children's intervals
(never the sum -- concurrent children overlap, and summing double-counts
that overlapped time). This is the primary attribution signal: if a span's
total duration grew but its self-time stayed flat, it is waiting on a
dependency rather than having gotten slower itself.
"""


def merge_intervals(intervals):
    """intervals: list of (start, end) in ns. Returns merged, sorted, non-overlapping
    list. Handles empty, nested, adjacent and overlapping intervals."""
    if not intervals:
        return []
    ivs = sorted(intervals, key=lambda x: x[0])
    merged = [list(ivs[0])]
    for start, end in ivs[1:]:
        last = merged[-1]
        if start <= last[1]:  # overlap or adjacent/nested
            last[1] = max(last[1], end)
        else:
            merged.append([start, end])
    return [tuple(m) for m in merged]


def union_duration(intervals):
    return sum(end - start for start, end in merge_intervals(intervals))


def compute_self_time_ns(span_start, span_duration, child_intervals):
    """child_intervals: list of (start_ns, end_ns) for direct children only.
    Clips child intervals to the parent span's own bounds first, since clock
    skew can occasionally make a child appear to start slightly before the
    parent -- that sliver of time is not the parent's to give away."""
    span_end = span_start + span_duration
    clipped = []
    for cs, ce in child_intervals:
        cs2, ce2 = max(cs, span_start), min(ce, span_end)
        if ce2 > cs2:
            clipped.append((cs2, ce2))
    covered = union_duration(clipped)
    return max(0, span_duration - covered)


def compute_self_times_for_trace(tree):
    """Returns dict[span_id] -> self_time_ns for every span in one trace tree."""
    spans = tree["spans"]
    children_map = tree["children"]
    result = {}
    for sid, row in spans.items():
        child_ids = children_map.get(sid, [])
        child_intervals = [
            (spans[cid]["start_ns"], spans[cid]["start_ns"] + spans[cid]["duration_ns"])
            for cid in child_ids
        ]
        result[sid] = compute_self_time_ns(row["start_ns"], row["duration_ns"], child_intervals)
    return result


def compute_self_times_all(trees):
    """Returns dict[trace_id] -> dict[span_id] -> self_time_ns."""
    return {tid: compute_self_times_for_trace(tree) for tid, tree in trees.items()}
