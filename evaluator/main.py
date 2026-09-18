"""
main.py
-------
Runs the full independent-verification workflow and prints a report.
This is the file you actually run.

Usage:
    python main.py spans.csv --deploy-file deploy_events.csv

What it does, step by step (mirrors the test plan sections):
  1. Loads and validates the dataset (Section 2, Test Cases 1-2)
  2. Picks a sample trace and reconstructs it, reports self-time and
     critical path (Section 2/3, Test Cases 3-9)
  3. Computes p99/p95/p50 per service (Section 2/3, Test Cases 10-11)
  4. Scans every service for a statistically significant regression,
     with false-positive calibration check (Test Cases 12-16)
  5. Ranks root-cause candidates and attributes to a deployment
     (Test Cases 17-18)

The output is your independently derived "answer key" — compare it by
eye against whatever the Builder's Streamlit app reports.
"""

import argparse
import json

import pandas as pd

from data_loader import load_spans, validate_spans
from trace_builder import build_trace_tree, get_trace
from self_time import compute_self_times_for_trace, sanity_check_self_times, compute_self_time_dataset
from critical_path import critical_path_report
from percentiles import percentiles_by_service
from regression_detection import find_regression_window, false_positive_rate_check, bonferroni_correct
from attribution import rank_root_cause_candidates, attribute_deployment


def section(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("spans_file", help="Path to spans.csv or spans.parquet")
    parser.add_argument("--deploy-file", default=None, help="Path to deploy_events.csv")
    parser.add_argument("--sample-trace-id", default=None, help="Specific trace_id to inspect; default = first trace")
    parser.add_argument("--alpha", type=float, default=0.05)
    args = parser.parse_args()

    # ---- 1. Load & validate ----
    section("1. DATA LOADING & VALIDATION")
    df = load_spans(args.spans_file)
    report = validate_spans(df)
    print(json.dumps(report, indent=2, default=str))

    # ---- 2. Trace reconstruction + self-time + critical path (golden sample) ----
    section("2. TRACE RECONSTRUCTION / SELF-TIME / CRITICAL PATH (sample trace)")
    trace_id = args.sample_trace_id or df["trace_id"].iloc[0]
    trace_df = get_trace(df, trace_id)
    roots, nodes_by_id = build_trace_tree(trace_df)
    print(f"Sample trace_id = {trace_id}, spans = {len(trace_df)}, roots = {len(roots)}")

    self_times = compute_self_times_for_trace(nodes_by_id)
    print("\nSelf-times by span:")
    for span_id, st in self_times.items():
        print(f"  {span_id}: self_time={st:.2f} ms")

    print("\nSelf-time sanity check (every span's self-time must be within [0, its own duration]):")
    print(json.dumps(sanity_check_self_times(nodes_by_id, roots), indent=2, default=str))

    print("\nCritical path for each root:")
    for root in roots:
        print(json.dumps(critical_path_report(root), indent=2, default=str))

    # ---- 3. Percentiles per service ----
    section("3. p50 / p95 / p99 PER SERVICE")
    perc = percentiles_by_service(df)
    print(perc.to_string())

    # ---- 4. Regression detection per service ----
    section("4. REGRESSION DETECTION PER SERVICE")
    p_values = {}
    detection_results = {}
    for service in sorted(df["service"].unique()):
        result = find_regression_window(df, service, alpha=args.alpha)
        detection_results[service] = result
        sig_windows = [w for w in result.get("all_windows", []) if w["significant"]]
        if sig_windows:
            p_values[service] = min(w["p_value"] for w in sig_windows)
            print(f"  {service}: REGRESSION DETECTED starting at t={result['first_detected_regression_start']} ms "
                  f"(min p-value={p_values[service]:.2e})")
        else:
            print(f"  {service}: no regression detected")

    if p_values:
        section("4b. MULTIPLE-COMPARISON CORRECTION (Bonferroni)")
        corrected = bonferroni_correct(p_values, alpha=args.alpha)
        print(json.dumps(corrected, indent=2, default=str))

    section("4c. FALSE-POSITIVE CALIBRATION CHECK")
    print("Run this against a service/time-window you KNOW is stable, e.g.:")
    print("  stable_data = df[(df.service=='auth-service')]['duration'].values")
    print("  false_positive_rate_check(stable_data)")
    # Example run against the first service's first hour as a rough stable baseline:
    first_service = sorted(df["service"].unique())[0]
    baseline_data = df[(df["service"] == first_service) & (df["start_time"] < df["start_time"].min() + 3600_000)]["duration"].values
    if len(baseline_data) >= 20:
        fp_check = false_positive_rate_check(baseline_data, alpha=args.alpha)
        print(json.dumps(fp_check, indent=2, default=str))

    # ---- 5. Root cause + deployment attribution ----
    section("5. ROOT CAUSE RANKING")
    regressed_services = [s for s, r in detection_results.items() if r.get("first_detected_regression_start")]
    if regressed_services:
        print("Computing self-time for every span in the dataset (this isolates each")
        print("service's OWN contribution from delays it merely inherited downstream)...")
        df["self_time"] = compute_self_time_dataset(df)

        self_time_before = {}
        self_time_after = {}
        # crude split: use the earliest detected regression time across
        # all services as the before/after cut point for this comparison
        cut = min(detection_results[s]["first_detected_regression_start"] for s in regressed_services)
        for service in df["service"].unique():
            service_df = df[df["service"] == service]
            before = service_df[service_df["start_time"] < cut]["self_time"]
            after = service_df[service_df["start_time"] >= cut]["self_time"]
            self_time_before[service] = before.median() if len(before) else 0
            self_time_after[service] = after.median() if len(after) else 0

        ranking = rank_root_cause_candidates(self_time_before, self_time_after)
        print(ranking.to_string())

        section("5b. DEPLOYMENT ATTRIBUTION")
        if args.deploy_file:
            deploy_df = pd.read_csv(args.deploy_file)
            deploy_df = deploy_df.rename(columns={
                "service_name": "service", "deploy_time_ms": "deploy_time",
            })
            top_service = ranking.iloc[0]["service"]
            regression_start = detection_results[top_service]["first_detected_regression_start"]
            attribution = attribute_deployment(regression_start, deploy_df)
            print(f"Top root-cause candidate: {top_service}, regression start: {regression_start}")
            print(json.dumps(attribution, indent=2, default=str))
        else:
            print("No --deploy-file given, skipping deployment attribution.")
    else:
        print("No regression detected in any service — nothing to rank or attribute.")


if __name__ == "__main__":
    main()
