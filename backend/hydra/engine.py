"""The control loop: probe, fail over dead replicas, restore the replica count."""
from __future__ import annotations

import random
import threading
import time
from typing import Dict, List, Optional

from .akash import AkashError, ConsoleAkash, SimulatedAkash
from .config import Config
from .deployer import Deployer
from .dns import CloudflareDns, DnsError, SimulatedDns
from .models import DEAD, HEALTHY, Replica
from .monitor import HttpProber, SimulatedProber, apply_probe
from .scorer import score, uptime
from .store import Store

BLOCKS_PER_DAY = 14_400  # Akash produces a block roughly every 6 seconds


class Hydra:
    def __init__(self, config: Config, akash, dns, prober, store: Store):
        self.config = config
        self.akash = akash
        self.dns = dns
        self.prober = prober
        self.store = store
        self.deployer = Deployer(akash, store, config)
        self.replicas: Dict[str, Replica] = {r.id: r for r in store.load_replicas()}
        self.active_id: Optional[str] = None
        self.running = False
        self.last_recovery: Optional[float] = None
        self.lock = threading.RLock()

    @classmethod
    def from_config(cls, config: Config) -> "Hydra":
        store = Store(config.database_path)
        if config.mode == "live":
            if not (config.akash_api_key and config.cloudflare_api_token and config.cloudflare_zone_id):
                raise RuntimeError("Live mode needs AKASH_API_KEY, CLOUDFLARE_API_TOKEN and CLOUDFLARE_ZONE_ID")
            return cls(
                config,
                ConsoleAkash(config.akash_api_key),
                CloudflareDns(config.cloudflare_api_token, config.cloudflare_zone_id, config.domain),
                HttpProber(),
                store,
            )
        akash = SimulatedAkash()
        return cls(config, akash, SimulatedDns(), SimulatedProber(akash), store)

    def start(self) -> None:
        self.running = True
        self.store.add_event("deploy", f"Keeping {self.config.replicas} replicas on separate providers")

    def tick(self) -> None:
        with self.lock:
            for replica in list(self.replicas.values()):
                ok = self.prober.probe(replica)
                self.store.record_probe(replica.provider, ok)
                was_ok = replica.status == HEALTHY
                apply_probe(replica, ok, self.config.strikes, self.config.boot_grace)
                if was_ok and not ok:
                    self.store.add_event("strike", f"{replica.provider} failed a health check")
                self.store.save_replica(replica)
            self._route_traffic()
            for replica in list(self.replicas.values()):
                if replica.status == DEAD:
                    self._retire(replica)
            if self.running:
                self._restore_count()
            self._route_traffic()

    def _healthy(self) -> List[Replica]:
        return [r for r in self.replicas.values() if r.status == HEALTHY]

    def _route_traffic(self) -> None:
        active = self.replicas.get(self.active_id) if self.active_id else None
        if active and active.status != DEAD:
            return
        healthy = self._healthy()
        if not healthy:
            return
        history = self.store.providers()
        cheapest = min(r.price for r in healthy)
        best = max(healthy, key=lambda r: score(history.get(r.provider), r.price, cheapest))
        try:
            self.dns.point_to(best.uri)
        except DnsError as exc:
            self.store.add_event("error", f"DNS update failed, will retry: {exc}")
            return
        self.active_id = best.id
        if active:
            self.last_recovery = time.time() - (active.first_failed_at or time.time())
            self.store.add_event(
                "failover", f"Traffic moved to {best.provider} in {self.last_recovery:.1f}s"
            )
        else:
            self.store.add_event("traffic", f"Traffic pointed at {best.provider}")

    def _retire(self, replica: Replica) -> None:
        self.store.record_failure(replica.provider)
        self.store.add_event("dead", f"{replica.provider} reached {self.config.strikes} strikes")
        self.deployer.close_quietly(replica.dseq)
        del self.replicas[replica.id]
        self.store.delete_replica(replica.id)
        self.store.add_event("close", f"Closed the lease on deployment {replica.dseq}")

    def _restore_count(self) -> None:
        while len(self.replicas) < self.config.replicas:
            in_use = {r.provider for r in self.replicas.values()}
            try:
                replica = self.deployer.deploy(in_use)
            except AkashError as exc:
                self.store.add_event("error", f"Could not deploy a replica, will retry: {exc}")
                return
            self.replicas[replica.id] = replica
            self.store.save_replica(replica)
            self.store.add_event("replace", f"New replica on {replica.provider} (dseq {replica.dseq})")

    def chaos(self, replica_id: Optional[str] = None) -> Optional[Replica]:
        """Kill one replica. Simulated mode marks it down; live mode closes its deployment."""
        with self.lock:
            candidates = [r for r in self.replicas.values() if r.status != DEAD]
            if replica_id:
                candidates = [r for r in candidates if r.id == replica_id]
            if not candidates:
                return None
            victim = random.choice(candidates)
            if isinstance(self.akash, SimulatedAkash):
                self.akash.kill(victim.dseq)
            else:
                self.deployer.close_quietly(victim.dseq)
            self.store.add_event("chaos", f"Chaos killed the replica on {victim.provider}")
            return victim

    def state(self) -> dict:
        with self.lock:
            history = self.store.providers()
            replicas = list(self.replicas.values())
            active = self.replicas.get(self.active_id) if self.active_id else None
        prices = [p["price"] for p in history.values() if p["price"]]
        cheapest = min(prices) if prices else 0
        in_use = {r.provider for r in replicas}
        providers = [
            {
                "address": address,
                "uptime": uptime(stats),
                "score": score(stats, stats["price"], cheapest),
                "probes": stats["probes"],
                "failures": stats["failures"],
                "price": stats["price"],
                "in_use": address in in_use,
            }
            for address, stats in history.items()
        ]
        return {
            "mode": self.config.mode,
            "running": self.running,
            "desired": self.config.replicas,
            "strikes": self.config.strikes,
            "domain": self.config.domain,
            "active_id": active.id if active else None,
            "active_uri": active.uri if active else None,
            "replicas": [vars(r).copy() for r in replicas],
            "providers": sorted(providers, key=lambda p: p["score"], reverse=True),
            "events": self.store.events(),
            "cost_per_day": sum(r.price for r in replicas) * BLOCKS_PER_DAY / 1_000_000,
            "last_recovery": self.last_recovery,
        }
