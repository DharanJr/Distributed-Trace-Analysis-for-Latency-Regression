"""
data_loader.py
--------------
Loads the span dataset and runs basic sanity checks (Test Cases 1-2
in the test plan). Supports .csv and .parquet.
"""

import pandas as pd
from config import COLUMNS


def load_spans(path: str) -> pd.DataFrame:
    """Load the raw span dataset into a normalized DataFrame with
    standard column names: trace_id, span_id, parent_id, service,
    start_time, end_time, duration.
    """
    if path.endswith(".parquet"):
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path)

    c = COLUMNS
    rename_map = {
        c["trace_id"]: "trace_id",
        c["span_id"]: "span_id",
        c["parent_id"]: "parent_id",
        c["service"]: "service",
        c["start_time"]: "start_time",
    }
    if c["duration"] is not None:
        rename_map[c["duration"]] = "duration"
    else:
        rename_map[c["end_time"]] = "end_time"

    df = df.rename(columns=rename_map)

    if "end_time" not in df.columns:
        df["end_time"] = df["start_time"] + df["duration"]
    else:
        df["duration"] = df["end_time"] - df["start_time"]

    return df


def validate_spans(df: pd.DataFrame, expected_rows: int = None) -> dict:
    """Runs Test Case 1 & 2 style checks. Returns a report dict rather
    than raising, so you can print/log every issue instead of stopping
    at the first one.
    """
    report = {}

    report["row_count"] = len(df)
    if expected_rows is not None:
        report["row_count_matches_expected"] = (len(df) == expected_rows)

    report["duplicate_span_ids"] = int(df["span_id"].duplicated().sum())

    report["null_trace_id"] = int(df["trace_id"].isna().sum())
    report["null_span_id"] = int(df["span_id"].isna().sum())
    report["null_start_time"] = int(df["start_time"].isna().sum())
    report["null_end_time"] = int(df["end_time"].isna().sum())

    report["negative_duration_count"] = int((df["duration"] < 0).sum())

    # Orphaned spans: parent_id set but that parent_id doesn't exist anywhere
    known_span_ids = set(df["span_id"])
    has_parent = df["parent_id"].notna()
    orphaned = df[has_parent & ~df["parent_id"].isin(known_span_ids)]
    report["orphaned_span_count"] = len(orphaned)
    report["orphaned_span_ids_sample"] = orphaned["span_id"].head(10).tolist()

    report["unique_traces"] = df["trace_id"].nunique()
    report["unique_services"] = df["service"].nunique()
    report["services_list"] = sorted(df["service"].dropna().unique().tolist())

    return report


if __name__ == "__main__":
    import sys
    import json

    path = sys.argv[1] if len(sys.argv) > 1 else "spans.csv"
    df = load_spans(path)
    report = validate_spans(df)
    print(json.dumps(report, indent=2, default=str))
