import sys
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.regression import benjamini_hochberg, detect_regressions


def test_bh_all_significant_when_all_pvalues_tiny():
    p = [0.001, 0.002, 0.0005, 0.003]
    adjusted, reject = benjamini_hochberg(p, alpha=0.05)
    assert all(reject)


def test_bh_controls_false_positives_with_many_nulls():
    rng = np.random.default_rng(0)
    # 100 null p-values (uniform, i.e. no real effect) should yield very few
    # rejections at 5% FDR -- this is the whole point of the correction.
    p = rng.uniform(0, 1, size=100).tolist()
    adjusted, reject = benjamini_hochberg(p, alpha=0.05)
    assert reject.sum() <= 10  # loose bound, sanity check not exact theory


def test_detect_regressions_flags_planted_shift():
    rng = np.random.default_rng(1)
    n = 200
    before = rng.lognormal(np.log(80), 0.3, n)
    after = rng.lognormal(np.log(350), 0.3, n)  # clearly shifted upward
    stable_before = rng.lognormal(np.log(20), 0.3, n)
    stable_after = rng.lognormal(np.log(21), 0.3, n)  # basically unchanged

    rows = []
    for d in before:
        rows.append({"service": "database-service", "operation": "inventory_lookup",
                      "period": "BEFORE", "duration_ns": d * 1e6, "status_code": 200})
    for d in after:
        rows.append({"service": "database-service", "operation": "inventory_lookup",
                      "period": "AFTER", "duration_ns": d * 1e6, "status_code": 200})
    for d in stable_before:
        rows.append({"service": "payment-service", "operation": "charge_payment",
                      "period": "BEFORE", "duration_ns": d * 1e6, "status_code": 200})
    for d in stable_after:
        rows.append({"service": "payment-service", "operation": "charge_payment",
                      "period": "AFTER", "duration_ns": d * 1e6, "status_code": 200})

    df = pd.DataFrame(rows)
    result = detect_regressions(df)

    db_row = result[result["service"] == "database-service"].iloc[0]
    pay_row = result[result["service"] == "payment-service"].iloc[0]

    assert db_row["regression"] == True
    assert pay_row["regression"] == False
