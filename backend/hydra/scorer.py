"""Ranks providers by observed uptime and price."""
from __future__ import annotations

from typing import List, Optional

from .models import Bid
from .store import Store

UPTIME_WEIGHT = 0.7
PRICE_WEIGHT = 0.3
FAILURE_PENALTY = 0.1


def uptime(stats: Optional[dict]) -> float:
    """Smoothed so that a provider with no history starts at 0.5 rather than 0 or 1."""
    stats = stats or {}
    return (stats.get("successes", 0) + 1) / (stats.get("probes", 0) + 2)


def score(stats: Optional[dict], price: float, cheapest: float) -> float:
    failures = (stats or {}).get("failures", 0)
    value = cheapest / price if price else 0.0
    return UPTIME_WEIGHT * uptime(stats) + PRICE_WEIGHT * value - FAILURE_PENALTY * failures


def rank_bids(store: Store, bids: List[Bid]) -> List[Bid]:
    """Best bid first."""
    if not bids:
        return []
    history = store.providers()
    cheapest = min(bid.price for bid in bids)
    return sorted(bids, key=lambda b: score(history.get(b.provider), b.price, cheapest), reverse=True)
