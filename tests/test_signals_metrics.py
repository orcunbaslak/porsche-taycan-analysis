from datetime import date

import pytest

from scraper.signals import compute_car_metrics


def _obs(run_d, list_d, price):
    return {"run_date": run_d, "listing_date": list_d, "price": price}


def test_bargain_car_metrics():
    observations = [
        _obs(date(2026, 1, 1), date(2026, 1, 1), 14_000_000),
        _obs(date(2026, 2, 1), date(2026, 1, 20), 13_000_000),  # bump + cut
        _obs(date(2026, 3, 1), date(2026, 2, 15), 13_000_000),  # bump, no cut
        _obs(date(2026, 4, 1), date(2026, 3, 10), 12_000_000),  # bump + cut
    ]
    m = compute_car_metrics(observations)

    assert m["runs_seen"] == 4
    assert m["first_seen_date"] == date(2026, 1, 1)
    assert m["last_seen_date"] == date(2026, 4, 1)
    assert m["days_on_market"] == 90
    assert m["bump_count"] == 3
    assert m["bump_cadence_days"] == pytest.approx(30.0)
    assert m["first_price"] == 14_000_000
    assert m["current_price"] == 12_000_000
    assert m["max_price"] == 14_000_000
    assert m["min_price"] == 12_000_000
    assert m["total_price_drop"] == 2_000_000
    assert m["price_drop_pct"] == pytest.approx(14.2857, abs=0.01)
    assert m["num_price_cuts"] == 2
    assert m["last_price_cut_date"] == date(2026, 4, 1)
    assert m["insufficient_history"] == 0
    assert m["motivation_score"] == pytest.approx(46.857, abs=0.01)


def test_single_observation_is_insufficient_history():
    m = compute_car_metrics([_obs(date(2026, 4, 1), date(2026, 4, 1), 12_000_000)])
    assert m["runs_seen"] == 1
    assert m["insufficient_history"] == 1
    assert m["bump_count"] == 0
    assert m["num_price_cuts"] == 0
    assert m["days_on_market"] == 0
    assert m["motivation_score"] == 0.0
    assert m["bump_cadence_days"] is None


def test_none_dates_and_prices_are_carried_over():
    # Missing date in the middle must not count as a bump; missing price ignored.
    observations = [
        _obs(date(2026, 1, 1), date(2026, 1, 1), 10_000_000),
        _obs(date(2026, 2, 1), None, None),
        _obs(date(2026, 3, 1), date(2026, 1, 1), 9_000_000),  # date unchanged -> no bump
    ]
    m = compute_car_metrics(observations)
    assert m["bump_count"] == 0
    assert m["num_price_cuts"] == 1
    assert m["first_price"] == 10_000_000
    assert m["current_price"] == 9_000_000
