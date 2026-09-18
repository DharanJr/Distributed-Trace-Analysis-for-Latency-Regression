"""
Real-data loader: converts Jaeger JSON trace exports (what you get from the
OpenTelemetry Demo's Jaeger UI "Download JSON" button, or from
`curl http://localhost:16686/api/traces?service=...`) into the same
spans.csv / deploys.csv schema that generator.py produces.

Nothing downstream of this file changes -- reconstruction.py, timing_analysis.py,
critical_path.py, regression.py, attribution.py and rca_agent.py all consume
data/spans.csv exactly as before, whether it came from the synthetic
generator or from a real running system.

Usage:
    python src/otel_loader.py \
        --before before.json [before2.json ...] \
        --after  after.json  [after2.json ...] \
        --deploy-service inventory-service --deploy-version 2.4.1 \
        --out-dir data/

Jaeger JSON shape (top level): {"data": [ {traceID, spans: [...], processes: {...}}, ... ]}
Each span: {
  "traceID", "spanID", "operationName", "startTime" (epoch microseconds),
  "duration" (microseconds), "processID", "references": [{"refType":"CHILD_OF","spanID":...}],
  "tags": [{"key":..., "value":...}, ...]
}
processes: {"p1": {"serviceName": "...", "tags": [...]}}
"""
import argparse
import json
from pathlib import Path
import pandas as pd


def _tag_value(tags, key):
    for t in tags or []:
        if t.get("key") == key:
            return t.get("value")
    return None


def _status_code(tags):
    # OTel semantic conventions: "otel.status_code" == "ERROR", or plain "error": true,
    # or an http.status_code / rpc numeric code already present.
    http_code = _tag_value(tags, "http.status_code")
    if http_code is not None:
        try:
            return int(http_code)
        except (TypeError, ValueError):
            pass
    if _tag_value(tags, "otel.status_code") == "ERROR":
        return 500
    if _tag_value(tags, "error") is True:
        return 500
    return 200


def parse_jaeger_file(path, period_label):
    """Returns a list of span dicts in our internal schema for one Jaeger export file."""
    with open(path) as f:
        payload = json.load(f)

    traces = payload.get("data", payload if isinstance(payload, list) else [])
    rows = []
    for trace in traces:
        processes = trace.get("processes", {})
        for span in trace.get("spans", []):
            proc = processes.get(span.get("processID"), {})
            service = proc.get("serviceName", "unknown-service")
            tags = span.get("tags", [])

            parent_span_id = None
            for ref in span.get("references", []):
                if ref.get("refType") == "CHILD_OF":
                    parent_span_id = ref.get("spanID")
                    break

            start_us = span.get("startTime", 0)
            duration_us = span.get("duration", 0)
            attrs = {t["key"]: t.get("value") for t in tags if "key" in t}

            rows.append({
                "trace_id": span.get("traceID"),
                "span_id": span.get("spanID"),
                "parent_span_id": parent_span_id,
                "service": service,
                "operation": span.get("operationName", "unknown_op"),
                "start_ns": int(start_us) * 1000,
                "duration_ns": max(1, int(duration_us) * 1000),
                "status_code": _status_code(tags),
                "attributes_json": json.dumps(attrs, default=str),
                "period": period_label,
            })
    return rows


def build_dataset(before_files, after_files, deploy_service, deploy_version,
                   deploy_ts_ns=None, out_dir=Path("data")):
    rows = []
    for f in before_files:
        rows.extend(parse_jaeger_file(f, "BEFORE"))
    for f in after_files:
        rows.extend(parse_jaeger_file(f, "AFTER"))

    if not rows:
        raise ValueError("No spans parsed -- check the input files are Jaeger JSON exports.")

    spans_df = pd.DataFrame(rows)
    spans_df.sort_values("start_ns", inplace=True)
    spans_df.reset_index(drop=True, inplace=True)

    # deploy_ts_ns: if not given, use the midpoint between the last BEFORE span
    # and the first AFTER span as the boundary marker.
    if deploy_ts_ns is None:
        before_max = spans_df[spans_df.period == "BEFORE"]["start_ns"].max()
        after_min = spans_df[spans_df.period == "AFTER"]["start_ns"].min()
        deploy_ts_ns = int((before_max + after_min) / 2) if pd.notna(before_max) and pd.notna(after_min) else int(spans_df["start_ns"].median())

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 'period' column is kept -- pipeline.load_data() will overwrite it based on
    # deploy_ts_ns anyway, so this is just for inspection/debugging.
    spans_out = spans_df.drop(columns=["period"])
    spans_out.to_csv(out_dir / "spans.csv", index=False)

    deploys_df = pd.DataFrame([{"ts": deploy_ts_ns, "service": deploy_service, "version": deploy_version}])
    deploys_df.to_csv(out_dir / "deploys.csv", index=False)

    print(f"Wrote {len(spans_out):,} real spans -> {out_dir / 'spans.csv'}")
    print(f"Wrote deploy event -> {out_dir / 'deploys.csv'} (ts_ns={deploy_ts_ns})")
    print(f"Services seen: {sorted(spans_out['service'].unique())}")
    return spans_out, deploys_df


def main():
    ap = argparse.ArgumentParser(description="Convert Jaeger JSON exports into spans.csv/deploys.csv")
    ap.add_argument("--before", nargs="+", required=True, help="Jaeger JSON file(s) from the BEFORE window")
    ap.add_argument("--after", nargs="+", required=True, help="Jaeger JSON file(s) from the AFTER window")
    ap.add_argument("--deploy-service", default="unknown-service")
    ap.add_argument("--deploy-version", default="unknown")
    ap.add_argument("--deploy-ts-ns", type=int, default=None,
                     help="Epoch nanoseconds for the deploy marker; default = midpoint of before/after")
    ap.add_argument("--out-dir", default="data")
    args = ap.parse_args()

    build_dataset(args.before, args.after, args.deploy_service, args.deploy_version,
                  deploy_ts_ns=args.deploy_ts_ns, out_dir=Path(args.out_dir))


if __name__ == "__main__":
    main()
