import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.timing_analysis import merge_intervals, union_duration, compute_self_time_ns


def test_merge_no_overlap():
    assert merge_intervals([(0, 10), (20, 30)]) == [(0, 10), (20, 30)]


def test_merge_overlap():
    # 100-500 and 300-700 -> union 100-700 = 600
    merged = merge_intervals([(100, 500), (300, 700)])
    assert merged == [(100, 700)]
    assert union_duration([(100, 500), (300, 700)]) == 600


def test_merge_nested():
    merged = merge_intervals([(0, 1000), (100, 200)])
    assert merged == [(0, 1000)]


def test_merge_adjacent():
    merged = merge_intervals([(0, 100), (100, 200)])
    assert merged == [(0, 200)]


def test_self_time_no_children():
    st = compute_self_time_ns(0, 1000, [])
    assert st == 1000


def test_self_time_matches_spec_example():
    # Parent 0-1000, child A 100-500, child B 300-700 -> union=600 -> self=400
    st = compute_self_time_ns(0, 1000, [(100, 500), (300, 700)])
    assert st == 400


def test_self_time_never_negative_with_clock_skew():
    # child starts before parent (clock skew); should be clipped, not go negative
    st = compute_self_time_ns(100, 50, [(0, 200)])
    assert st == 0
