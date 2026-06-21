"""Compute a per-car bargain / motivation signal from cross-run listing history."""

from scraper.config import (
    SCORE_WEIGHT_PRICE_DROP,
    SCORE_WEIGHT_PRICE_CUTS,
    SCORE_WEIGHT_DAYS,
    SCORE_WEIGHT_BUMPS,
    SCORE_CAP_PRICE_DROP_PCT,
    SCORE_CAP_PRICE_CUTS,
    SCORE_CAP_DAYS_ON_MARKET,
    SCORE_CAP_BUMP_COUNT,
)


def _norm(x, cap):
    """Normalize x into 0..1 against cap, clamping out-of-range values."""
    if cap <= 0:
        return 0.0
    return min(max(x, 0), cap) / cap


def motivation_score(price_drop_pct, num_price_cuts, days_on_market, bump_count):
    """Weighted 0..100 composite of the four bargain signals."""
    return 100 * (
        SCORE_WEIGHT_PRICE_DROP * _norm(price_drop_pct, SCORE_CAP_PRICE_DROP_PCT)
        + SCORE_WEIGHT_PRICE_CUTS * _norm(num_price_cuts, SCORE_CAP_PRICE_CUTS)
        + SCORE_WEIGHT_DAYS * _norm(days_on_market, SCORE_CAP_DAYS_ON_MARKET)
        + SCORE_WEIGHT_BUMPS * _norm(bump_count, SCORE_CAP_BUMP_COUNT)
    )
