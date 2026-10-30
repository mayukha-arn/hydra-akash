import json

import httpx
import pytest

from hydra.akash import AkashError, ConsoleAkash, SimulatedAkash
from hydra.config import ROOT, Config
from hydra.dns import CloudflareDns, SimulatedDns
from hydra.engine import Hydra
from hydra.models import HEALTHY, SUSPECT, Bid, Replica
from hydra.monitor import SimulatedProber, apply_probe
from hydra.scorer import rank_bids, score
from hydra.store import Store


def make_hydra(path=":memory:"):
    config = Config(sdl_path=str(ROOT / "sdl" / "web.yaml"), bid_timeout=0, database_path=path)
    akash = SimulatedAkash(seed=1, flaky=False)
    hydra = Hydra(config, akash, SimulatedDns(), SimulatedProber(akash), Store(path))
    hydra.start()
    hydra.tick()
    hydra.tick()
    return hydra


def test_deploys_one_replica_per_provider():
    hydra = make_hydra()
    providers = [r.provider for r in hydra.replicas.values()]
    assert len(providers) == 3
    assert len(set(providers)) == 3
    assert all(r.status == HEALTHY for r in hydra.replicas.values())
    assert hydra.dns.target == hydra.replicas[hydra.active_id].uri


def test_single_failed_probe_is_only_a_strike():
    replica = Replica("r", "1", "p", "u", 1.0, status=HEALTHY)
    apply_probe(replica, False, strikes=3)
    assert (replica.status, replica.strikes) == (SUSPECT, 1)
    apply_probe(replica, True, strikes=3)
    assert (replica.status, replica.strikes) == (HEALTHY, 0)


def test_new_replica_gets_boot_grace():
    replica = Replica("r", "1", "p", "u", 1.0, created_at=__import__("time").time())
    apply_probe(replica, False, strikes=3, boot_grace=60)
    assert replica.strikes == 0


def test_active_failure_moves_traffic_and_replaces_replica():
    hydra = make_hydra()
    old = hydra.replicas[hydra.active_id]
    hydra.chaos(old.id)
    hydra.tick()
    hydra.tick()
    assert hydra.active_id == old.id  # two strikes: still in place
    hydra.tick()
    hydra.tick()

    assert old.dseq in hydra.akash.closed
    assert old.id not in hydra.replicas
    assert len(hydra.replicas) == 3
    assert hydra.dns.target == hydra.replicas[hydra.active_id].uri
    assert hydra.active_id != old.id
    assert hydra.store.providers()[old.provider]["failures"] == 1
    assert hydra.last_recovery is not None


def test_replacement_avoids_providers_in_use_and_failed_provider_ranks_lower():
    hydra = make_hydra()
    old = hydra.replicas[hydra.active_id]
    hydra.chaos(old.id)
    for _ in range(4):
        hydra.tick()
    providers = [r.provider for r in hydra.replicas.values()]
    assert len(set(providers)) == 3
    assert old.provider not in providers


def test_standby_failure_leaves_dns_alone():
    hydra = make_hydra()
    target = hydra.dns.target
    standby = next(r for r in hydra.replicas.values() if r.id != hydra.active_id)
    hydra.chaos(standby.id)
    for _ in range(4):
        hydra.tick()
    assert hydra.dns.target == target
    assert len(hydra.replicas) == 3


def test_no_bids_closes_deployment_and_retries():
    hydra = make_hydra()
    hydra.akash.list_bids = lambda dseq: []
    old = hydra.replicas[hydra.active_id]
    hydra.chaos(old.id)
    for _ in range(3):
        hydra.tick()
    assert len(hydra.replicas) == 2
    assert len(hydra.akash.closed) >= 2  # dead lease plus the unfilled deployment


def test_replicas_survive_restart(tmp_path):
    path = str(tmp_path / "hydra.db")
    first = make_hydra(path)
    config = Config(sdl_path=str(ROOT / "sdl" / "web.yaml"), bid_timeout=0)
    second = Hydra(config, first.akash, SimulatedDns(), SimulatedProber(first.akash), Store(path))
    assert set(second.replicas) == set(first.replicas)


def test_scorer_prefers_reliable_over_cheap():
    store = Store()
    for _ in range(50):
        store.record_probe("steady", True)
        store.record_probe("flaky", False)
    bids = [Bid("1", "flaky", 100), Bid("1", "steady", 120)]
    assert rank_bids(store, bids)[0].provider == "steady"
    assert score(None, 100, 100) == pytest.approx(0.65)


def console(handler):
    return ConsoleAkash("k", httpx.Client(base_url="https://console.test", transport=httpx.MockTransport(handler)))


def test_console_client_requests():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path))
        if request.method == "POST" and request.url.path == "/v1/deployments":
            assert json.loads(request.content) == {"data": {"sdl": "yaml"}}
            return httpx.Response(201, json={"data": {"dseq": "77"}})
        if request.url.path == "/v1/bids":
            assert request.url.params["dseq"] == "77"
            bid = {"id": {"provider": "akash1p", "gseq": 1, "oseq": 1}, "price": {"amount": "1200"}}
            return httpx.Response(200, json={"data": [{"bid": bid}]})
        if request.url.path == "/v1/leases":
            lease = json.loads(request.content)["leases"][0]
            assert lease == {"dseq": "77", "gseq": 1, "oseq": 1, "provider": "akash1p"}
            return httpx.Response(200, json={"data": {}})
        if request.method == "GET":
            lease = {"id": {"provider": "akash1p"}, "status": {"services": {"web": {"uris": ["a.example"]}}}}
            return httpx.Response(200, json={"data": {"leases": [lease]}})
        return httpx.Response(200, json={"data": {"success": True}})

    client = console(handler)
    assert client.create_deployment("yaml") == "77"
    bid = client.list_bids("77")[0]
    assert (bid.provider, bid.price) == ("akash1p", 1200.0)
    client.create_lease(bid)
    assert client.lease_uri("77", "akash1p") == "a.example"
    client.close_deployment("77")
    assert seen[-1] == ("DELETE", "/v1/deployments/77")


def test_console_error_raises():
    client = console(lambda request: httpx.Response(401, json={"error": "Unauthorized"}))
    with pytest.raises(AkashError):
        client.create_deployment("yaml")


def test_cloudflare_updates_existing_record():
    calls = []

    def handler(request):
        calls.append(request.method)
        if request.method == "GET":
            return httpx.Response(200, json={"result": [{"id": "rec1"}]})
        assert request.url.path.endswith("/dns_records/rec1")
        assert json.loads(request.content)["content"] == "new.example"
        return httpx.Response(200, json={"result": {}})

    http = httpx.Client(base_url="https://cf.test", transport=httpx.MockTransport(handler))
    CloudflareDns("t", "zone", "app.example.com", http).point_to("new.example")
    assert calls == ["GET", "PUT"]
