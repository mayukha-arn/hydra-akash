"""Clients for creating and closing Akash deployments.

ConsoleAkash talks to the Akash Console managed wallet API. SimulatedAkash has
the same interface and runs in memory, so Hydra can be exercised without funds.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

import httpx

from .models import Bid


class AkashError(Exception):
    pass


class ConsoleAkash:
    def __init__(self, api_key: str, http: Optional[httpx.Client] = None):
        self.http = http or httpx.Client(
            base_url="https://console-api.akash.network",
            headers={"x-api-key": api_key},
            timeout=30,
        )

    def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = self.http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise AkashError(f"{method} {path} failed: {exc}") from exc
        if response.status_code >= 400:
            raise AkashError(f"{method} {path} returned {response.status_code}: {response.text[:200]}")
        return response.json()

    def create_deployment(self, sdl: str) -> str:
        body = self._request("POST", "/v1/deployments", json={"data": {"sdl": sdl}})
        return str(body["data"]["dseq"])

    def list_bids(self, dseq: str) -> List[Bid]:
        body = self._request("GET", "/v1/bids", params={"dseq": dseq})
        bids = []
        for item in body["data"]:
            bid_id = item["bid"]["id"]
            bids.append(
                Bid(
                    dseq=dseq,
                    provider=bid_id["provider"],
                    price=float(item["bid"]["price"]["amount"]),
                    gseq=int(bid_id["gseq"]),
                    oseq=int(bid_id["oseq"]),
                )
            )
        return bids

    def create_lease(self, bid: Bid) -> None:
        lease = {"dseq": bid.dseq, "gseq": bid.gseq, "oseq": bid.oseq, "provider": bid.provider}
        self._request("POST", "/v1/leases", json={"leases": [lease]})

    def lease_uri(self, dseq: str, provider: str) -> Optional[str]:
        body = self._request("GET", f"/v1/deployments/{dseq}")
        for lease in body["data"].get("leases", []):
            if lease["id"]["provider"] != provider:
                continue
            services = (lease.get("status") or {}).get("services") or {}
            for service in services.values():
                if service.get("uris"):
                    return service["uris"][0]
        return None

    def close_deployment(self, dseq: str) -> None:
        self._request("DELETE", f"/v1/deployments/{dseq}")


@dataclass
class SimProvider:
    address: str
    name: str
    region: str
    price: float
    flake: float  # chance that a probe fails on an otherwise healthy replica


SIM_PROVIDERS = [
    SimProvider("akash1sim0europlots", "europlots", "Frankfurt", 1180, 0.004),
    SimProvider("akash1sim1hurricane", "hurricane", "Fremont", 1240, 0.002),
    SimProvider("akash1sim2neuron", "neuron", "Ashburn", 1010, 0.03),
    SimProvider("akash1sim3tokyonode", "tokyonode", "Tokyo", 1320, 0.008),
    SimProvider("akash1sim4saopaulo", "saopaulo", "Sao Paulo", 960, 0.06),
    SimProvider("akash1sim5nordic", "nordic", "Helsinki", 1095, 0.012),
]


class SimulatedAkash:
    def __init__(self, seed: Optional[int] = None, flaky: bool = True):
        self.rng = random.Random(seed)
        self.flaky = flaky
        self.next_dseq = 24_000_000
        self.providers = {p.address: p for p in SIM_PROVIDERS}
        self.deployments: Dict[str, Optional[str]] = {}  # dseq -> leased provider
        self.killed: Set[str] = set()
        self.closed: List[str] = []

    def create_deployment(self, sdl: str) -> str:
        self.next_dseq += self.rng.randint(3, 40)
        dseq = str(self.next_dseq)
        self.deployments[dseq] = None
        return dseq

    def list_bids(self, dseq: str) -> List[Bid]:
        return [
            Bid(dseq=dseq, provider=p.address, price=round(p.price * self.rng.uniform(0.97, 1.03), 1))
            for p in self.providers.values()
        ]

    def create_lease(self, bid: Bid) -> None:
        self.deployments[bid.dseq] = bid.provider

    def lease_uri(self, dseq: str, provider: str) -> Optional[str]:
        return f"{dseq}.{self.providers[provider].name}.sim.akash"

    def close_deployment(self, dseq: str) -> None:
        if dseq not in self.deployments:
            raise AkashError(f"deployment {dseq} not found")
        del self.deployments[dseq]
        self.closed.append(dseq)

    def kill(self, dseq: str) -> None:
        self.killed.add(dseq)

    def probe(self, dseq: str, provider: str) -> bool:
        if dseq in self.killed or dseq not in self.deployments:
            return False
        return not (self.flaky and self.rng.random() < self.providers[provider].flake)
