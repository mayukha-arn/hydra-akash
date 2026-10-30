"""Creates one replica on one provider: deployment, bid selection, lease."""
from __future__ import annotations

import time
from typing import Callable, List, Optional, Set

from .akash import AkashError
from .config import Config
from .models import Bid, Replica
from .scorer import rank_bids
from .store import Store


class Deployer:
    def __init__(self, akash, store: Store, config: Config, sleep: Callable[[float], None] = time.sleep):
        self.akash = akash
        self.store = store
        self.config = config
        self.sleep = sleep
        with open(config.sdl_path) as handle:
            self.sdl = handle.read().replace("${HYDRA_DOMAIN}", config.domain)

    def _wait_for_bids(self, dseq: str, exclude: Set[str]) -> List[Bid]:
        deadline = time.monotonic() + self.config.bid_timeout
        while True:
            bids = [b for b in self.akash.list_bids(dseq) if b.provider not in exclude]
            if bids or time.monotonic() >= deadline:
                return bids
            self.sleep(self.config.bid_poll)

    def _wait_for_uri(self, dseq: str, provider: str) -> Optional[str]:
        deadline = time.monotonic() + self.config.bid_timeout
        while True:
            uri = self.akash.lease_uri(dseq, provider)
            if uri or time.monotonic() >= deadline:
                return uri
            self.sleep(self.config.bid_poll)

    def deploy(self, exclude: Set[str]) -> Replica:
        """Deploy to the best-ranked provider not in exclude.

        The deployment is closed on any failure so that a half-made replica
        does not keep drawing from the deposit.
        """
        dseq = self.akash.create_deployment(self.sdl)
        try:
            bids = self._wait_for_bids(dseq, exclude)
            for bid in bids:
                self.store.record_price(bid.provider, bid.price)
            if not bids:
                raise AkashError(f"no eligible bids for deployment {dseq}")
            errors = []
            for bid in rank_bids(self.store, bids):
                try:
                    self.akash.create_lease(bid)
                except AkashError as exc:
                    errors.append(str(exc))
                    continue
                uri = self._wait_for_uri(dseq, bid.provider)
                if not uri:
                    raise AkashError(f"lease on {bid.provider} has no public URI")
                return Replica(
                    id=f"r-{dseq}",
                    dseq=dseq,
                    provider=bid.provider,
                    uri=uri,
                    price=bid.price,
                    created_at=time.time(),
                )
            raise AkashError("; ".join(errors))
        except AkashError:
            self.close_quietly(dseq)
            raise

    def close_quietly(self, dseq: str) -> None:
        try:
            self.akash.close_deployment(dseq)
        except AkashError as exc:
            self.store.add_event("error", f"Could not close deployment {dseq}: {exc}")
