"""
compare_utils.py
-----------------
Small helper for the PASS/FAIL checklist (Section 5 of the test plan):
feed it your independently computed value and the Builder's reported
value, get back PASS/FAIL plus the numbers to paste into a bug report.
"""


def grade(name: str, computed, builder_reported, tolerance, is_relative_pct=False) -> dict:
    """
    name: label for this check, e.g. "p99_checkout_service"
    computed: the value YOU calculated independently
    builder_reported: the value the Builder's tool/UI showed
    tolerance: max allowed difference (percentage if is_relative_pct=True,
               absolute otherwise)
    """
    if is_relative_pct:
        if builder_reported == 0:
            diff = float("inf") if computed != 0 else 0.0
        else:
            diff = abs(computed - builder_reported) / abs(builder_reported) * 100
    else:
        diff = abs(computed - builder_reported)

    passed = diff <= tolerance
    return {
        "check": name,
        "computed": computed,
        "builder_reported": builder_reported,
        "difference": diff,
        "tolerance": tolerance,
        "result": "PASS" if passed else "FAIL",
    }


def print_grade_table(results: list):
    print(f"{'Check':35s} {'Computed':>15s} {'Builder':>15s} {'Diff':>10s} {'Result':>8s}")
    print("-" * 90)
    for r in results:
        print(f"{r['check']:35s} {str(round(r['computed'],3)):>15s} "
              f"{str(round(r['builder_reported'],3)):>15s} "
              f"{round(r['difference'],3):>10} {r['result']:>8s}")
