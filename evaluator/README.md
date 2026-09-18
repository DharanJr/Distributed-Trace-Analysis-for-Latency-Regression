# Evaluator Toolkit — Step-by-Step Guide

This is the code you (the Evaluator/Tester) run **independently of the Builder's code**, so
you have your own numbers to check the Builder's output against. It matches Sections 2 and 3
of the Evaluator/Tester Plan (test cases, self-time, critical path, p99, regression detection).

It has been built and tested end-to-end on a synthetic dataset with a known planted
regression — every module runs correctly as shipped.

---

## 1. Where to put this and how to set it up

1. Copy this whole `evaluator_toolkit` folder onto your own machine (or wherever you'll run
   your tests — it does not need to be anywhere near the Builder's code; keep it separate on
   purpose, so your results are truly independent).
2. Open a terminal in that folder.
3. Install the three dependencies:
   ```bash
   pip install -r requirements.txt
   ```
   (Python 3.9+ recommended.)

That's it — no database, no special environment.

---

## 2. Try it first on fake data (do this BEFORE the Builder gives you anything)

This lets you confirm the toolkit itself works, and lets you practice reading the output,
using a small dataset where you already know the "right answer."

```bash
python synthetic_data_generator.py
```

This creates two files in the same folder:
- `spans.csv` — ~32,000 fake spans across 8 services, with a regression planted in
  `payment-service` starting at t = 3,600,000 ms, caused by a deployment 2 minutes earlier.
- `deploy_events.csv` — the fake deployment log.

Now run the full pipeline against it:

```bash
python main.py spans.csv --deploy-file deploy_events.csv
```

You should see, in order:
1. A data validation report (row counts, duplicates, orphaned spans)
2. Self-time and critical path for one sample trace
3. p50/p95/p99 latency per service
4. Which services show a statistically significant regression, and when
5. A false-positive calibration check
6. A root-cause ranking (payment-service should come out clearly on top)
7. Deployment attribution (should point to `deploy-1001` on `payment-service`)

If your run matches that description, the toolkit is working correctly on your machine.

---

## 3. Point it at the REAL dataset once the Builder gives it to you

1. Open `config.py`.
2. Update the `COLUMNS` dictionary so the values on the right match the **actual column
   names** in the real dataset (trace ID, span ID, parent span ID, service name, start time,
   and either an end time or a duration column). This is the only file you should need to
   edit to point the toolkit at new data.
3. If you also have a deployment-events file, update `DEPLOY_COLUMNS` the same way.
4. Run:
   ```bash
   python main.py real_spans.csv --deploy-file real_deploy_events.csv
   ```
   (Use `--sample-trace-id <id>` to inspect a specific trace instead of the first one found —
   useful once you've picked your 5–10 "golden sample" traces by hand, per Section 1.4 of the
   test plan.)

This produces your own independently-computed answer key. Write these numbers down (or
redirect the output to a file: `python main.py real_spans.csv > my_independent_results.txt`)
**before** you look at what the Builder's tool reports, so you're not unconsciously
adjusting your expectations.

---

## 4. Comparing your numbers against the Builder's tool

Once the Builder's Streamlit app shows you a p99, a self-time, a critical path, or a
detected regression time, use `compare_utils.py` to grade it. Example, in a Python shell or
small script in the same folder:

```python
from compare_utils import grade, print_grade_table

results = [
    grade("p99_payment_service", computed=190.47, builder_reported=188.90,
          tolerance=2.0, is_relative_pct=True),
    grade("self_time_span_0-pay", computed=23.24, builder_reported=23.20,
          tolerance=1.0),
    grade("critical_path_trace_0", computed=104.42, builder_reported=104.40,
          tolerance=1.0),
]

print_grade_table(results)
```

This prints a PASS/FAIL table you can paste straight into your final evaluation report
(Section 7 of the test plan). Tolerances are pre-set in `config.py` under `TOLERANCE` —
adjust them there if you and the Builder agree on different thresholds.

---

## 5. What each file does (so you can find the right one fast)

| File | Test-plan section | What it does |
|---|---|---|
| `config.py` | — | Column-name mapping and tolerance settings. Edit this first. |
| `data_loader.py` | Test Cases 1–2 | Loads the CSV/parquet, checks for duplicates, nulls, orphaned spans. |
| `trace_builder.py` | Test Cases 3–4 | Reconstructs the parent-child span tree for one trace. |
| `self_time.py` | Test Cases 5–7 | Self-time per span, correctly merging overlapping children. |
| `critical_path.py` | Test Cases 8–9 | Longest true dependency chain through a trace. |
| `percentiles.py` | Test Cases 10–11 | p50/p95/p99 per service, with ordering sanity check. |
| `regression_detection.py` | Test Cases 12–16 | Mann-Whitney statistical test, Bonferroni correction, false-positive calibration. |
| `attribution.py` | Test Cases 17–18 | Ranks root-cause candidates by self-time change; matches regressions to deployments. |
| `compare_utils.py` | Section 5 checklist | Grades Builder-reported numbers against your computed ones. |
| `synthetic_data_generator.py` | Section 1 prep | Makes a small fake dataset with a known answer, for practice/testing. |
| `main.py` | — | Runs everything above in sequence and prints the full report. **This is the file you run.** |

---

## 6. Common gotchas

- **Self-time sum "exceeding" the root's duration is not always a bug.** If a trace has
  parallel/concurrent children (two services doing real work at the same time), the sum of
  their self-times can legitimately be larger than the wall-clock duration of the parent.
  The toolkit checks each span's self-time individually (must be between 0 and its own
  duration) rather than checking the sum — that is the correct invariant. If the Builder's
  tool asserts the sum must stay under wall-clock time, that's worth raising with them.
- **Percentile method differences cause small mismatches.** If your p99 is close to the
  Builder's but not identical, ask which percentile interpolation method they used
  (Section 4, question 3 in the test plan) before filing it as a bug.
- **The regression-detection scan in `find_regression_window` uses a sliding window and a
  fixed baseline (the very first window).** This is intentionally simple so you can trust
  it as an independent check. It will not exactly match a more sophisticated Builder
  algorithm, but it should agree on *which service* and *roughly when* — that's what you're
  really checking.
