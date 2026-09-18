"""
config.py
---------
Column-name mapping so the toolkit works no matter what your dataset's
column names are. Edit the values on the right to match your CSV/parquet
file's actual column headers. Everything else in the toolkit reads
column names from here — you should not need to edit any other file
just to point it at your data.
"""

COLUMNS = {
    "trace_id": "trace_id",
    "span_id": "span_id",
    "parent_id": "parent_span_id",   # empty/NaN for root spans
    "service": "service_name",
    "start_time": "start_time_ms",   # epoch milliseconds (int)
    "end_time": "end_time_ms",       # epoch milliseconds (int)
    # duration is derived as end_time - start_time, but if your dataset
    # already has a duration column instead of end_time, set this and
    # the loader will compute end_time = start_time + duration for you.
    "duration": None,                # e.g. "duration_ms", or None if you have end_time
}

# Deployment events file column mapping (a separate small file listing
# when each service was deployed). Only needed for Section 5 (attribution).
DEPLOY_COLUMNS = {
    "service": "service_name",
    "deploy_time": "deploy_time_ms",
    "deploy_id": "deploy_id",
}

# Tolerances used when comparing your independently computed numbers
# against the Builder's tool output (Section 3 of the test plan).
TOLERANCE = {
    "p99_relative_pct": 2.0,        # p99 must match within 2%
    "self_time_abs_ms": 1.0,        # self-time must match within 1 ms
    "critical_path_abs_ms": 1.0,    # critical path must match within 1 ms
    "regression_time_window_ms": 5 * 60 * 1000,  # detected time must be within 5 min of truth
    "deploy_attribution_window_ms": 15 * 60 * 1000,  # deploy must be within 15 min of regression start
}
