import pytest

from scraper.signals import _norm, motivation_score


def test_norm_basic():
    assert _norm(10, 20) == 0.5
    assert _norm(-5, 20) == 0.0   # clamped low
    assert _norm(30, 20) == 1.0   # clamped high
    assert _norm(5, 0) == 0.0     # zero cap is safe


def test_motivation_score_known_inputs():
    # price_drop_pct=14.2857, cuts=2, days=90, bumps=3
    # = 100 * (0.40*0.571428 + 0.20*0.4 + 0.20*0.5 + 0.20*0.3) = 46.857...
    score = motivation_score(
        price_drop_pct=14.285714, num_price_cuts=2, days_on_market=90, bump_count=3
    )
    assert score == pytest.approx(46.857, abs=0.01)


def test_motivation_score_zero_when_no_signal():
    assert motivation_score(0, 0, 0, 0) == 0.0
