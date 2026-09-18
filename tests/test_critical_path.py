import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.critical_path import compute_critical_path


def _mk_span(sid, trace_id, service, op, start, duration):
    return {
        "trace_id": trace_id, "span_id": sid, "parent_span_id": None,
        "service": service, "operation": op, "start_ns": start,
        "duration_ns": duration, "status_code": 200, "attributes_json": "{}",
    }


def test_critical_path_picks_longer_branch():
    # API(0-1000) -> Order(0-1000) -> Payment(0-100) [concurrent] & Inventory(0-900) -> Database(50-850)
    spans = {
        "api": _mk_span("api", "t1", "api-gateway", "checkout", 0, 1000),
        "order": _mk_span("order", "t1", "order-service", "process_order", 0, 1000),
        "payment": _mk_span("payment", "t1", "payment-service", "charge_payment", 0, 100),
        "inventory": _mk_span("inventory", "t1", "inventory-service", "check_inventory", 0, 900),
        "database": _mk_span("database", "t1", "database-service", "inventory_lookup", 50, 800),
    }
    tree = {
        "root": "api",
        "spans": spans,
        "children": {
            "api": ["order"],
            "order": ["payment", "inventory"],
            "inventory": ["database"],
        },
    }
    result = compute_critical_path(tree)
    assert result["critical_path"] == ["api", "order", "inventory", "database"]
    assert result["critical_path_duration_ns"] == 1000


def test_critical_path_leaf_only():
    spans = {"root": _mk_span("root", "t2", "svc", "op", 0, 42)}
    tree = {"root": "root", "spans": spans, "children": {}}
    result = compute_critical_path(tree)
    assert result["critical_path"] == ["root"]
    assert result["critical_path_duration_ns"] == 42
