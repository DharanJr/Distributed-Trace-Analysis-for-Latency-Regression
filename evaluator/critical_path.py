"""
critical_path.py
-----------------
Computes the critical path of a trace (Test Cases 8-9): the true
longest dependency chain, not just "the single biggest span."

Definition used here (the standard one for trace critical-path
analysis): the critical-path duration of a node equals its own
self-time PLUS the critical-path duration of whichever child
contributes the most delay. This correctly picks the slower of two
parallel branches, because a branch that finished early is not what
was holding up the parent.
"""

from self_time import compute_self_time
from trace_builder import SpanNode


def critical_path_duration(node: SpanNode) -> float:
    """Recursively compute the critical-path duration rooted at `node`."""
    self_t = compute_self_time(node)
    if not node.children:
        return self_t
    max_child = max(critical_path_duration(c) for c in node.children)
    return self_t + max_child


def critical_path_chain(node: SpanNode) -> list:
    """Returns the ordered list of SpanNode objects forming the
    critical path from `node` down to a leaf."""
    chain = [node]
    current = node
    while current.children:
        # pick whichever child has the largest critical_path_duration
        best_child = max(current.children, key=critical_path_duration)
        chain.append(best_child)
        current = best_child
    return chain


def critical_path_report(root: SpanNode) -> dict:
    chain = critical_path_chain(root)
    return {
        "critical_path_duration": critical_path_duration(root),
        "root_duration": root.duration,
        "duration_exceeds_root": critical_path_duration(root) > root.duration + 1e-6,
        "chain": [
            {"span_id": n.span_id, "service": n.service, "start": n.start, "end": n.end}
            for n in chain
        ],
    }
