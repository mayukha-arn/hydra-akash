# Hydra

A self-healing multi-provider deployment manager for [Akash Network](https://akash.network).

Hydra deploys your app to 2-3 independent Akash providers, monitors them, and reroutes traffic automatically when one fails. Dead replicas are replaced on fresh providers so you always keep N healthy copies.

## Architecture

- **Deployer**: creates deployments and leases from SDL templates, one replica per provider
- **Health monitor**: probes replicas on an interval, with a 3-strikes rule
- **Failover engine**: updates DNS, replaces dead replicas, closes dead leases
- **Provider scorer**: tracks uptime and price per provider over time
- **Dashboard**: live replica status, cost, and failover timeline, plus a Chaos button

## Status

- [ ] Phase 1: manual multi-provider deploy via Akash Console
- [x] Phase 2: automated deploy/close via API
- [x] Phase 3: health monitor + DNS failover
- [x] Phase 4: auto-replacement + provider scoring
- [x] Phase 5: dashboard + Chaos button

Phases 2-5 run end to end against the built-in simulator. The Akash and Cloudflare clients are tested against mocked responses only and have not run against the real services yet.

## Run it

Simulator mode needs no keys and spends nothing:

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/uvicorn hydra.main:app --app-dir backend --port 8000
```

Open http://localhost:8000 and press the Chaos button.

Run the tests:

```bash
cd backend && ../.venv/bin/python -m pytest tests
```

## Live mode

Copy `.env.example` to `.env` and fill in your own values. Never commit `.env`. Set `HYDRA_MODE=live`, then start the server as above.

Live mode creates paid deployments, so nothing is deployed until you press Deploy replicas (or `POST /api/deploy`). In live mode the Chaos button closes the replica's real deployment.

Edit `sdl/web.yaml` to deploy your own image. Traffic moves by updating one CNAME record at `HYDRA_DOMAIN`, so failover also depends on that record's 60 second TTL.

## License

MIT
