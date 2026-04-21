from src.learn.bounded_tuning import tune_threshold


def test_thresholds_stay_within_bounds():
    assert tune_threshold(0.72, 0.02, 0.60, 0.72) == 0.72
    assert tune_threshold(0.60, -0.02, 0.60, 0.72) == 0.60
    assert tune_threshold(0.70, 0.02, 0.60, 0.72) == 0.72
