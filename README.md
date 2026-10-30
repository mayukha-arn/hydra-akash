# Hydra

A self-healing multi-provider deployment manager for [Akash Network](https://akash.network).

Hydra deploys your app to 2-3 independent Akash providers, monitors them, and reroutes traffic automatically when one fails. Dead replicas are replaced on fresh providers so you always keep N healthy copies.

## Planned architecture

- **Deployer**: creates deployments and leases from SDL templates, one replica per provider
- **Health monitor**: probes replicas on an interval, with a 3-strikes rule
- **Failover engine**: updates DNS, replaces dead replicas, closes dead leases
- **Provider scorer**: tracks uptime and price per provider over time
- **Dashboard**: live replica status, cost, and failover timeline, plus a Chaos button

## Status

- [ ] Phase 1: manual multi-provider deploy via Akash Console
- [ ] Phase 2: automated deploy/close via API
- [ ] Phase 3: health monitor + DNS failover
- [ ] Phase 4: auto-replacement + provider scoring
- [ ] Phase 5: dashboard + Chaos button

## Setup

Copy `.env.example` to `.env` and fill in your own values. Never commit `.env`.

## License

MIT
