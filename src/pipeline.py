"""
Orchestration layer: wires all modules together into one run() call.
Used by both the test suite and the Streamlit dashboard so there is exactly
one code path producing "the analysis".
"""
import json
from pathlib import Path
import pandas as pd

from src import reconstruction, dependency_graph, timing_analysis, critical_path
from src import latency_analysis, regression, attribution, rca_agent

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"


def load_data(data_dir=DATA_DIR):
    spans_df = pd.read_csv(data_dir / "spans.csv")
    # parent_span_id is empty string / NaN for root spans after a CSV round-trip
    spans_df["parent_span_id"] = spans_df["parent_span_id"].where(spans_df["parent_span_id"].notna(), None)
    deploys_df = pd.read_csv(data_dir / "deploys.csv")
    deploy_ts = int(deploys_df["ts"].iloc[0]) if not deploys_df.empty else None
    spans_df["period"] = spans_df["start_ns"].apply(
        lambda t: "BEFORE" if deploy_ts is None or t < deploy_ts else "AFTER"
    )
    # stamp period onto each span's row copy stored inside trees later via merge
    return spans_df, deploys_df


def run_full_pipeline(data_dir=DATA_DIR, write_report=True):
    spans_df, deploys_df = load_data(data_dir)

    trees, quality = reconstruction.build_trace_trees(spans_df)

    # attach period to each span inside the trees too (needed by attribution)
    period_map = dict(zip(spans_df["span_id"], spans_df["period"]))
    for tree in trees.values():
        for sid, row in tree["spans"].items():
            row["period"] = period_map.get(sid)

    graph, service_stats = dependency_graph.build_dependency_graph(trees)
    self_times_by_span = timing_analysis.compute_self_times_all(trees)
    critical_paths = critical_path.compute_critical_paths_all(trees)
    latency_stats_df = latency_analysis.compute_latency_stats(spans_df)
    regression_df = regression.detect_regressions(spans_df)
    attribution_result = attribution.attribute_root_cause(
        regression_df, trees, self_times_by_span, critical_paths, deploys_df
    )

    # user-facing symptom is the edge endpoint, not necessarily the same row as
    # the internal root-cause candidate -- look it up separately so the note
    # doesn't misreport whichever service happens to be the top regression.
    symptom_service, symptom_operation = "api-gateway", "checkout"
    symptom_before_p99 = symptom_after_p99 = None
    if not regression_df.empty:
        edge_rows = regression_df[
            (regression_df["service"] == symptom_service) & (regression_df["operation"] == symptom_operation)
        ]
        if not edge_rows.empty:
            symptom_before_p99 = float(edge_rows.iloc[0]["before_p99"])
            symptom_after_p99 = float(edge_rows.iloc[0]["after_p99"])

    rca_note = rca_agent.generate_rca_note(
        attribution_result,
        symptom_service=symptom_service,
        symptom_operation=symptom_operation,
        symptom_before_p99=symptom_before_p99,
        symptom_after_p99=symptom_after_p99,
    )
    evidence_json = rca_agent.build_evidence_chain_json(attribution_result)

    result = {
        "quality": quality,
        "service_stats": service_stats,
        "latency_stats": latency_stats_df,
        "regression": regression_df,
        "attribution": attribution_result,
        "rca_note": rca_note,
        "evidence": evidence_json,
        "graph": graph,
        "trees": trees,
        "critical_paths": critical_paths,
        "self_times_by_span": self_times_by_span,
        "spans_df": spans_df,
        "deploys_df": deploys_df,
    }

    if write_report:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        serializable = {
            "quality": quality,
            "service_stats": service_stats,
            "regression": json.loads(regression_df.to_json(orient="records")),
            "attribution": attribution_result,
            "evidence": evidence_json,
        }
        with open(REPORTS_DIR / "generated_analysis.json", "w") as f:
            json.dump(serializable, f, indent=2, default=str)

    return result


if __name__ == "__main__":
    res = run_full_pipeline()
    print(res["rca_note"])
