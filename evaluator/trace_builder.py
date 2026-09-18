"""
trace_builder.py
----------------
Reconstructs the parent-child span tree for a single trace
(Test Cases 3-4 in the test plan).
"""

import pandas as pd


class SpanNode:
    __slots__ = ("span_id", "service", "start", "end", "parent_id", "children")

    def __init__(self, span_id, service, start, end, parent_id):
        self.span_id = span_id
        self.service = service
        self.start = start
        self.end = end
        self.parent_id = parent_id
        self.children = []

    @property
    def duration(self):
        return self.end - self.start

    def __repr__(self):
        return f"SpanNode({self.span_id}, {self.service}, {self.start}-{self.end})"


def build_trace_tree(trace_df: pd.DataFrame):
    """Given all spans for ONE trace_id, returns (roots, nodes_by_id).

    roots: list of SpanNode with no known parent in this trace
           (normally there should be exactly one root; more than one
           usually means either a genuinely fanned-out trace or a data
           problem worth flagging)
    nodes_by_id: dict span_id -> SpanNode, with .children populated
    """
    nodes_by_id = {}
    for _, row in trace_df.iterrows():
        nodes_by_id[row["span_id"]] = SpanNode(
            span_id=row["span_id"],
            service=row["service"],
            start=row["start_time"],
            end=row["end_time"],
            parent_id=row["parent_id"],
        )

    roots = []
    for node in nodes_by_id.values():
        parent_id = node.parent_id
        if pd.isna(parent_id) or parent_id not in nodes_by_id:
            # No parent, or parent points outside this trace (orphan) ->
            # treat as a root so nothing silently disappears.
            roots.append(node)
        else:
            nodes_by_id[parent_id].children.append(node)

    # Sort children by start time for deterministic, readable traversal
    for node in nodes_by_id.values():
        node.children.sort(key=lambda n: n.start)

    return roots, nodes_by_id


def get_trace(df: pd.DataFrame, trace_id) -> pd.DataFrame:
    """Convenience: pull all spans belonging to one trace_id."""
    return df[df["trace_id"] == trace_id].copy()
