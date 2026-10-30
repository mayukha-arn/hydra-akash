from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

STARTING = "starting"
HEALTHY = "healthy"
SUSPECT = "suspect"
DEAD = "dead"


@dataclass
class Bid:
    dseq: str
    provider: str
    price: float  # uact per block
    gseq: int = 1
    oseq: int = 1


@dataclass
class Replica:
    id: str
    dseq: str
    provider: str
    uri: str
    price: float
    status: str = STARTING
    strikes: int = 0
    created_at: float = 0.0
    first_failed_at: Optional[float] = field(default=None)
