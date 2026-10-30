"""Health probes and the strikes rule."""
from __future__ import annotations

import time
from typing import Optional

import httpx

from .akash import SimulatedAkash
from .models import DEAD, HEALTHY, STARTING, SUSPECT, Replica


class HttpProber:
    def __init__(self, http: Optional[httpx.Client] = None):
        self.http = http or httpx.Client(timeout=5, follow_redirects=True)

    def probe(self, replica: Replica) -> bool:
        try:
            return self.http.get(f"http://{replica.uri}/").status_code < 500
        except httpx.HTTPError:
            return False


class SimulatedProber:
    def __init__(self, akash: SimulatedAkash):
        self.akash = akash

    def probe(self, replica: Replica) -> bool:
        return self.akash.probe(replica.dseq, replica.provider)


def apply_probe(replica: Replica, ok: bool, strikes: int, boot_grace: float = 0.0) -> None:
    """Update a replica from one probe. Strikes only count consecutive failures."""
    now = time.time()
    if ok:
        replica.status = HEALTHY
        replica.strikes = 0
        replica.first_failed_at = None
        return
    if replica.status == STARTING and now - replica.created_at < boot_grace:
        return
    replica.strikes += 1
    replica.first_failed_at = replica.first_failed_at or now
    replica.status = DEAD if replica.strikes >= strikes else SUSPECT
