"""
Module 2: Span tree reconstruction.

Groups spans by trace_id, links children to parents via parent_span_id, and
identifies root spans. Broken parent references (pointing at a span_id that
doesn't exist anywhere) are NOT allowed to crash the pipeline -- they are
tracked as orphans and re-attached to the trace's real root as a fallback so
downstream critical-path / self-time code still has a usable tree.
"""
from collections import defaultdict


def build_trace_trees(spans_df):
    """
    Returns:
      trees: dict[trace_id] -> {
          'children': dict[span_id -> list[span_id]],
          'root': span_id or None,
          'spans': dict[span_id -> span row (dict)],
          'orphans': list[span_id],   # had a parent_span_id that doesn't exist
      }
      quality: dict with orphan_count, root_missing_count, total_spans, total_traces
    """
    trees = {}
    orphan_count = 0
    root_missing_count = 0

    grouped = spans_df.groupby("trace_id")
    for trace_id, group in grouped:
        spans_by_id = {row.span_id: row._asdict() for row in group.itertuples(index=False)}
        span_ids = set(spans_by_id.keys())
        children = defaultdict(list)
        roots = []
        orphans = []

        for sid, row in spans_by_id.items():
            parent = row.get("parent_span_id")
            if parent is None or (isinstance(parent, float)) or parent == "":
                roots.append(sid)
            elif parent not in span_ids:
                # broken reference: parent doesn't exist in this trace
                orphans.append(sid)
                orphan_count += 1
            else:
                children[parent].append(sid)

        if not roots:
            # no true root found (e.g. root itself got orphaned) -- fall back to
            # the earliest-starting span so the trace still has a usable tree
            root_missing_count += 1
            fallback_root = min(spans_by_id.values(), key=lambda r: r["start_ns"])["span_id"]
            roots = [fallback_root]

        # re-attach orphans under the (first) root so nothing is silently dropped
        primary_root = roots[0]
        for oid in orphans:
            children[primary_root].append(oid)

        trees[trace_id] = {
            "children": dict(children),
            "root": primary_root,
            "all_roots": roots,
            "spans": spans_by_id,
            "orphans": orphans,
        }

    quality = {
        "total_traces": len(trees),
        "total_spans": len(spans_df),
        "orphan_count": orphan_count,
        "root_missing_count": root_missing_count,
        "orphan_rate": orphan_count / max(1, len(spans_df)),
    }
    return trees, quality


def get_children(tree, span_id):
    return tree["children"].get(span_id, [])
