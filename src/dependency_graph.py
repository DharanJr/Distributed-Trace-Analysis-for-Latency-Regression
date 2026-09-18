"""
Module 3: Service-level dependency graph.

Builds a directed graph (service A calls service B) from the reconstructed
trace trees, and attaches per-edge and per-service statistics: call count,
mean/P95/P99 latency, error rate. Regression status is merged in later
(from regression.py) so the dashboard can highlight the offending edge.
"""
import networkx as nx
import numpy as np


def build_dependency_graph(trees):
    """Returns a networkx.DiGraph. Nodes = services. Edges = caller -> callee,
    with edge attribute 'call_count'. Also returns per-service duration samples
    (self-contained span durations, in ms) for quick stats."""
    g = nx.DiGraph()
    service_durations_ms = {}
    service_errors = {}
    service_calls = {}

    for trace_id, tree in trees.items():
        spans = tree["spans"]
        for sid, row in spans.items():
            svc = row["service"]
            g.add_node(svc)
            service_durations_ms.setdefault(svc, []).append(row["duration_ns"] / 1e6)
            service_calls[svc] = service_calls.get(svc, 0) + 1
            if row["status_code"] >= 400:
                service_errors[svc] = service_errors.get(svc, 0) + 1

            for child_id in tree["children"].get(sid, []):
                child_svc = spans[child_id]["service"]
                if child_svc == svc:
                    continue  # skip self-loops from same-service internal spans
                if g.has_edge(svc, child_svc):
                    g[svc][child_svc]["call_count"] += 1
                else:
                    g.add_edge(svc, child_svc, call_count=1)

    stats = {}
    for svc, durations in service_durations_ms.items():
        arr = np.array(durations)
        calls = service_calls.get(svc, 0)
        errors = service_errors.get(svc, 0)
        stats[svc] = {
            "call_count": calls,
            "mean_ms": float(arr.mean()),
            "p95_ms": float(np.percentile(arr, 95)),
            "p99_ms": float(np.percentile(arr, 99)),
            "error_rate": errors / max(1, calls),
        }

    for svc, s in stats.items():
        for k, v in s.items():
            g.nodes[svc][k] = v

    return g, stats
