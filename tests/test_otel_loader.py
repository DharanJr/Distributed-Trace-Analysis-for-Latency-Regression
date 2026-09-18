import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.otel_loader import parse_jaeger_file, build_dataset

FIXTURE = Path(__file__).parent / "fixtures" / "jaeger_before_sample.json"


def test_parse_jaeger_file_basic_fields():
    rows = parse_jaeger_file(FIXTURE, "BEFORE")
    assert len(rows) == 3
    root = next(r for r in rows if r["span_id"] == "s1")
    assert root["service"] == "frontend"
    assert root["parent_span_id"] is None
    assert root["status_code"] == 200
    assert root["duration_ns"] == 120000 * 1000  # us -> ns

    child = next(r for r in rows if r["span_id"] == "s2")
    assert child["parent_span_id"] == "s1"
    assert child["service"] == "checkoutservice"


def test_build_dataset_end_to_end(tmp_path):
    spans_df, deploys_df = build_dataset(
        before_files=[FIXTURE], after_files=[FIXTURE],
        deploy_service="checkoutservice", deploy_version="1.2.3",
        out_dir=tmp_path,
    )
    assert (tmp_path / "spans.csv").exists()
    assert (tmp_path / "deploys.csv").exists()
    assert len(spans_df) == 6  # 3 spans x (before + after)
    assert deploys_df.iloc[0]["service"] == "checkoutservice"
    # required schema columns present
    for col in ["trace_id", "span_id", "parent_span_id", "service", "operation",
                "start_ns", "duration_ns", "status_code", "attributes_json"]:
        assert col in spans_df.columns
