"""
Module 1: Synthetic distributed trace generator.

Produces data/spans.csv and data/deploys.csv matching the required schema:
  spans: trace_id, span_id, parent_span_id, service, operation,
         start_ns, duration_ns, status_code, attributes_json
  deploys: ts, service, version

Design:
  - 12-service call graph, checkout path has real fan-out (concurrent children).
  - Lognormal service times (right-skewed, realistic).
  - Two logical periods (BEFORE / AFTER) split by a deploy event.
  - A regression is planted ONLY in database-service / inventory_lookup:
    BEFORE median ~80ms -> AFTER median ~350ms (P99 roughly 90ms -> 500ms+).
  - Other services stay stable across periods (control group for the stats).
  - A small amount of clock skew and occasional broken parent references are
    injected on purpose so the reconstruction module has to handle them.
"""
import json
import uuid
import numpy as np
import pandas as pd
from pathlib import Path

RNG_SEED = 42
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# ---- Call graph node definitions -------------------------------------------------
# leaf nodes: {'leaf': True, 'op':..., 'median':..., 'sigma':..., 'error_rate':...}
# parent nodes: {'op':..., 'self_head_ms':(lo,hi), 'self_tail_ms':(lo,hi),
#                'children':[(service, 'concurrent'|'sequential'), ...]}
NODE_DEFS = {
    "api-gateway": {
        "op": "checkout",
        "self_head_ms": (2, 4),
        "self_tail_ms": (2, 4),
        "children": [("order-service", "sequential")],
    },
    "order-service": {
        "op": "process_order",
        "self_head_ms": (4, 7),
        "self_tail_ms": (3, 5),
        "children": [
            ("payment-service", "concurrent"),
            ("inventory-service", "concurrent"),
            ("recommendation-service", "concurrent"),
        ],
    },
    "payment-service": {"op": "charge_payment", "leaf": True, "median": 45, "sigma": 0.30, "error_rate": 0.01},
    "recommendation-service": {"op": "get_recommendations", "leaf": True, "median": 25, "sigma": 0.35, "error_rate": 0.01},
    "inventory-service": {
        "op": "check_inventory",
        "self_head_ms": (2, 4),
        "self_tail_ms": (2, 3),
        "children": [
            ("product-service", "sequential"),
            ("database-service", "sequential"),
        ],
    },
    "product-service": {"op": "get_product_details", "leaf": True, "median": 20, "sigma": 0.30, "error_rate": 0.01},
    "database-service": {
        "op": "inventory_lookup", "leaf": True,
        "median_before": 80, "median_after": 350, "sigma": 0.35, "error_rate": 0.02,
    },
}

# Background traffic: independent, single-hop traces on other services, so the
# regression-detection module has a realistic population of stable endpoints
# to test against (and so per-operation percentiles mean something).
BACKGROUND_SERVICES = {
    "auth-service": {"op": "verify_token", "median": 8, "sigma": 0.25, "error_rate": 0.01},
    "user-service": {"op": "get_profile", "median": 15, "sigma": 0.30, "error_rate": 0.01},
    "cart-service": {"op": "get_cart", "median": 12, "sigma": 0.30, "error_rate": 0.01},
    "notification-service": {"op": "send_email", "median": 30, "sigma": 0.40, "error_rate": 0.02},
    "shipping-service": {"op": "estimate_shipping", "median": 18, "sigma": 0.30, "error_rate": 0.01},
}


def _lognormal_ms(rng, median_ms, sigma):
    mu = np.log(median_ms)
    return float(rng.lognormal(mu, sigma))


def _new_id(rng):
    return "".join(rng.choice(list("0123456789abcdef"), size=16))


def _build_span(service, trace_id, start_ns, period, rng, spans_out, parent_id=None,
                 corrupt_parent_prob=0.0, clock_skew_prob=0.03):
    """Recursively build a span (and its subtree). Returns (span_id, end_ns)."""
    span_id = _new_id(rng)
    node = NODE_DEFS[service]

    # occasionally corrupt the parent reference to simulate a dropped context
    stored_parent = parent_id
    if parent_id is not None and rng.random() < corrupt_parent_prob:
        stored_parent = _new_id(rng)  # points at nothing -> orphan

    if node.get("leaf"):
        if service == "database-service":
            median = node["median_before"] if period == "BEFORE" else node["median_after"]
        else:
            median = node["median"]
        duration_ms = _lognormal_ms(rng, median, node["sigma"])
        is_error = rng.random() < node["error_rate"]
        status_code = 500 if is_error else 200
        if is_error:
            duration_ms *= rng.uniform(0.2, 0.5)  # fail fast
        duration_ns = max(1, int(duration_ms * 1e6))

        # occasional clock skew: child start appears slightly BEFORE parent start
        eff_start = start_ns
        if clock_skew_prob and rng.random() < clock_skew_prob:
            eff_start = start_ns - int(rng.uniform(0, 3) * 1e6)

        attrs = {"retry_count": int(rng.random() < 0.03)}
        if service == "database-service":
            attrs["db.statement_shape"] = "SELECT * FROM inventory WHERE sku = ?"
        spans_out.append({
            "trace_id": trace_id, "span_id": span_id, "parent_span_id": stored_parent,
            "service": service, "operation": node["op"],
            "start_ns": eff_start, "duration_ns": duration_ns,
            "status_code": status_code, "attributes_json": json.dumps(attrs),
        })
        return span_id, eff_start + duration_ns

    # ---- parent (fan-out) node ----
    head_ns = int(rng.uniform(*node["self_head_ms"]) * 1e6)
    tail_ns = int(rng.uniform(*node["self_tail_ms"]) * 1e6)
    children_start = start_ns + head_ns
    child_ends = []
    cursor = children_start
    for child_service, mode in node["children"]:
        child_start = children_start if mode == "concurrent" else cursor
        if mode == "concurrent":
            # small jitter so children don't start at the exact same nanosecond
            child_start += int(rng.uniform(0, 3) * 1e6)
        _, child_end = _build_span(
            child_service, trace_id, child_start, period, rng, spans_out,
            parent_id=span_id, corrupt_parent_prob=corrupt_parent_prob,
            clock_skew_prob=clock_skew_prob,
        )
        child_ends.append(child_end)
        cursor = child_end

    children_end = max(child_ends) if child_ends else children_start
    end_ns = children_end + tail_ns
    duration_ns = max(1, end_ns - start_ns)
    attrs = {"retry_count": 0}
    if service == "api-gateway":
        attrs["http.route"] = "/checkout"
    spans_out.append({
        "trace_id": trace_id, "span_id": span_id, "parent_span_id": stored_parent,
        "service": service, "operation": node["op"],
        "start_ns": start_ns, "duration_ns": duration_ns,
        "status_code": 200, "attributes_json": json.dumps(attrs),
    })
    return span_id, end_ns


def generate(n_checkout_traces=5000, n_background_traces=6000, seed=RNG_SEED,
             corrupt_parent_prob=0.001, out_dir=DATA_DIR):
    """Generate the full synthetic dataset and write CSV files to out_dir."""
    rng = np.random.default_rng(seed)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Two-hour window. First half BEFORE, second half AFTER. Deploy sits at the boundary.
    t0 = 0
    period_len_ns = int(60 * 60 * 1e9)  # 1 hour per period
    deploy_ts_ns = t0 + period_len_ns

    spans = []

    def period_and_start(rng):
        period = "BEFORE" if rng.random() < 0.5 else "AFTER"
        base = t0 if period == "BEFORE" else deploy_ts_ns
        offset = int(rng.uniform(0, period_len_ns))
        return period, base + offset

    for _ in range(n_checkout_traces):
        trace_id = _new_id(rng)
        period, start_ns = period_and_start(rng)
        _build_span("api-gateway", trace_id, start_ns, period, rng, spans,
                    corrupt_parent_prob=corrupt_parent_prob)

    bg_services = list(BACKGROUND_SERVICES.items())
    for _ in range(n_background_traces):
        trace_id = _new_id(rng)
        period, start_ns = period_and_start(rng)
        service, node = bg_services[rng.integers(0, len(bg_services))]
        duration_ms = _lognormal_ms(rng, node["median"], node["sigma"])
        is_error = rng.random() < node["error_rate"]
        status_code = 500 if is_error else 200
        if is_error:
            duration_ms *= rng.uniform(0.2, 0.5)
        duration_ns = max(1, int(duration_ms * 1e6))
        spans.append({
            "trace_id": trace_id, "span_id": _new_id(rng), "parent_span_id": None,
            "service": service, "operation": node["op"],
            "start_ns": start_ns, "duration_ns": duration_ns,
            "status_code": status_code,
            "attributes_json": json.dumps({"retry_count": 0}),
        })

    spans_df = pd.DataFrame(spans)
    spans_df["parent_span_id"] = spans_df["parent_span_id"].astype("object")
    spans_df.sort_values("start_ns", inplace=True)
    spans_df.reset_index(drop=True, inplace=True)

    spans_path = out_dir / "spans.csv"
    spans_df.to_csv(spans_path, index=False)

    deploys_df = pd.DataFrame([
        {"ts": deploy_ts_ns, "service": "inventory-service", "version": "2.4.1"},
    ])
    deploys_path = out_dir / "deploys.csv"
    deploys_df.to_csv(deploys_path, index=False)

    print(f"Wrote {len(spans_df):,} spans -> {spans_path}")
    print(f"Wrote {len(deploys_df):,} deploy events -> {deploys_path}")
    print(f"Deploy event at t_ns={deploy_ts_ns} (period boundary)")
    return spans_df, deploys_df


if __name__ == "__main__":
    generate()
