"""
synthetic_data_generator.py
----------------------------
Generates a small fake tracing dataset with a KNOWN planted regression
and a KNOWN deployment event, matching the column names in config.py.

Why this exists: you can use this BEFORE the Builder has written any
code (Section 1 of the test plan, "prepare before Builder starts") to:
  1. Test that this evaluator toolkit itself works correctly.
  2. Practice your golden-sample, hand-calculation workflow on a small,
     fully-known dataset.

This is NOT the real 200,000-span dataset — it's a stand-in you
control completely, so you always know the right answer.

Usage:
    python synthetic_data_generator.py
    -> writes spans.csv and deploy_events.csv into the current folder
"""

import numpy as np
import pandas as pd

SERVICES = [
    "api-gateway", "auth-service", "user-service", "order-service",
    "payment-service", "inventory-service", "shipping-service",
    "notification-service", "search-service", "recommendation-service",
    "cache-service", "database-service",
]

REGRESSED_SERVICE = "payment-service"
REGRESSION_START_MS = 60 * 60 * 1000  # regression starts at t = 60 min
DEPLOY_TIME_MS = REGRESSION_START_MS - 2 * 60 * 1000  # deploy 2 min before regression shows up
TOTAL_DURATION_MS = 120 * 60 * 1000  # 2 hours of data
N_TRACES = 4000


def make_trace(trace_id: int, start_time: float, rng) -> list:
    """Builds one realistic-ish trace: gateway -> auth -> user -> order ->
    payment -> (inventory, shipping in parallel) -> notification.
    Returns a list of span dicts.
    """
    spans = []
    t = start_time

    def new_span(span_id, parent_id, service, dur):
        nonlocal t
        s = t
        e = s + dur
        spans.append({
            "trace_id": trace_id, "span_id": span_id, "parent_span_id": parent_id,
            "service_name": service, "start_time_ms": s, "end_time_ms": e,
        })
        return e

    is_regressed_window = start_time >= REGRESSION_START_MS

    # IMPORTANT: every parent span's [start,end] must fully contain all of
    # its children's [start,end] ranges, exactly like real tracing data.
    # We do this by reserving a placeholder span first, running the
    # children, then patching the placeholder's end time afterward.

    def reserve_span(span_id, parent_id, service):
        spans.append({
            "trace_id": trace_id, "span_id": span_id, "parent_span_id": parent_id,
            "service_name": service, "start_time_ms": None, "end_time_ms": None,
        })
        return len(spans) - 1  # index into spans list, to patch later

    gw_id = f"{trace_id}-gw"
    gw_idx = reserve_span(gw_id, None, "api-gateway")
    gw_start = t
    t += max(rng.normal(3, 0.5), 0.5)  # gateway's own pre-work (self-time)

    auth_id = f"{trace_id}-auth"
    t = new_span(auth_id, gw_id, "auth-service", max(rng.normal(15, 2), 1))

    user_id = f"{trace_id}-user"
    t = new_span(user_id, gw_id, "user-service", max(rng.normal(10, 2), 1))

    # order-service is itself a parent (of payment/inventory/shipping),
    # so it also needs the reserve-then-patch treatment.
    order_id = f"{trace_id}-order"
    order_idx = reserve_span(order_id, gw_id, "order-service")
    order_start = t
    t += max(rng.normal(2, 0.3), 0.3)  # order's own pre-work

    # Payment service: this is where the regression is planted.
    if is_regressed_window:
        pay_dur = max(rng.normal(150, 20), 1)   # much slower after regression
    else:
        pay_dur = max(rng.normal(25, 4), 1)     # normal
    pay_id = f"{trace_id}-pay"
    t = new_span(pay_id, order_id, "payment-service", pay_dur)

    # Two parallel children under order-service: inventory + shipping
    branch_start = t
    inv_id = f"{trace_id}-inv"
    t = branch_start
    t = new_span(inv_id, order_id, "inventory-service", max(rng.normal(30, 5), 1))
    inv_end = t

    ship_id = f"{trace_id}-ship"
    t = branch_start
    t = new_span(ship_id, order_id, "shipping-service", max(rng.normal(45, 6), 1))
    ship_end = t

    t = max(inv_end, ship_end)
    t += max(rng.normal(1, 0.2), 0.2)  # order's own post-work
    order_end = t

    spans[order_idx]["start_time_ms"] = order_start
    spans[order_idx]["end_time_ms"] = order_end

    notif_id = f"{trace_id}-notif"
    t = new_span(notif_id, gw_id, "notification-service", max(rng.normal(8, 1), 1))

    gw_end = t
    spans[gw_idx]["start_time_ms"] = gw_start
    spans[gw_idx]["end_time_ms"] = gw_end

    return spans


def generate(output_dir="."):
    rng = np.random.default_rng(7)
    all_spans = []
    trace_start_times = np.sort(rng.uniform(0, TOTAL_DURATION_MS, N_TRACES))

    for i, start in enumerate(trace_start_times):
        all_spans.extend(make_trace(i, start, rng))

    spans_df = pd.DataFrame(all_spans)
    spans_df.to_csv(f"{output_dir}/spans.csv", index=False)

    deploy_df = pd.DataFrame([
        {"service_name": REGRESSED_SERVICE, "deploy_time_ms": DEPLOY_TIME_MS, "deploy_id": "deploy-1001"},
        {"service_name": "auth-service", "deploy_time_ms": 20 * 60 * 1000, "deploy_id": "deploy-1000"},  # decoy, unrelated
    ])
    deploy_df.to_csv(f"{output_dir}/deploy_events.csv", index=False)

    print(f"Wrote {len(spans_df)} spans across {spans_df['service_name'].nunique()} services to spans.csv")
    print(f"Ground truth: regression planted in '{REGRESSED_SERVICE}' starting at t={REGRESSION_START_MS} ms")
    print(f"Ground truth: deployment '{DEPLOY_TIME_MS}' ms for '{REGRESSED_SERVICE}' (deploy-1001)")
    print("Wrote deploy_events.csv")


if __name__ == "__main__":
    generate()
