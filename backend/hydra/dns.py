"""Traffic routing. The domain is one CNAME that points at the active replica."""
from __future__ import annotations

from typing import Optional

import httpx


class DnsError(Exception):
    pass


class SimulatedDns:
    def __init__(self) -> None:
        self.target: Optional[str] = None

    def point_to(self, hostname: str) -> None:
        self.target = hostname


class CloudflareDns:
    def __init__(self, token: str, zone_id: str, domain: str, http: Optional[httpx.Client] = None):
        self.domain = domain
        self.records = f"/zones/{zone_id}/dns_records"
        self.http = http or httpx.Client(
            base_url="https://api.cloudflare.com/client/v4",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )

    def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = self.http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise DnsError(f"Cloudflare request failed: {exc}") from exc
        if response.status_code >= 400:
            raise DnsError(f"Cloudflare returned {response.status_code}: {response.text[:200]}")
        return response.json()

    def point_to(self, hostname: str) -> None:
        record = {"type": "CNAME", "name": self.domain, "content": hostname, "ttl": 60, "proxied": False}
        found = self._request("GET", self.records, params={"name": self.domain, "type": "CNAME"})
        if found["result"]:
            self._request("PUT", f"{self.records}/{found['result'][0]['id']}", json=record)
        else:
            self._request("POST", self.records, json=record)
