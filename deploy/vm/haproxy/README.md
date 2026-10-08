# HAProxy Reverse Proxy with Staging Failover

**Purpose:** Local reverse proxy that routes traffic to prod and staging apps, with automatic failover to prod if staging becomes unavailable. Solves the single-VM deployment problem where staging initialization delays or failures can briefly affect external routing to both apps.

## How It Works

- **HAProxy** runs locally on port 8080 (HTTP) and 8443 (HTTPS, future)
- **Two backends:**
  - `prod_backend` → 127.0.0.1:8000 (production app)
  - `staging_backend` → 127.0.0.1:8010 (staging app)
  - `failover_backend` → 127.0.0.1:8000 (prod only, fallback for staging)

- **Routing logic:**
  - Requests for `racinglines.bet` → prod only
  - Requests for `staging.racinglines.bet` → staging, or prod if staging is down

- **Health checks:** Every 2 seconds, HAProxy checks if each backend is responding. If staging fails 3 checks in a row, it's marked down and staging traffic goes to prod.

## Installation

On the VM:

```bash
cd /opt/racinglines
bash scripts/deploy/vm/setup-haproxy.sh
```

This:
1. Installs HAProxy (if not already present)
2. Copies `deploy/vm/haproxy/racinglines-proxy.cfg` → `/etc/racinglines/haproxy.cfg`
3. Copies `deploy/vm/systemd/racinglines-proxy.service` → `/etc/systemd/system/`
4. Starts `racinglines-proxy` systemd service

## Next Step: Update External Routing

The external DNS/Load Balancer (GCP LB, Cloudflare, etc.) must route both URLs to `127.0.0.1:8080` instead of direct app ports. Once configured:

- `racinglines.bet` traffic → GCP LB/Cloudflare → 127.0.0.1:8080 → HAProxy → prod (8000)
- `staging.racinglines.bet` traffic → GCP LB/Cloudflare → 127.0.0.1:8080 → HAProxy → staging (8010), fallback to prod

## Monitoring

HAProxy stats page (internal only):
```bash
curl http://127.0.0.1:8404/stats
```

Service status:
```bash
sudo systemctl status racinglines-proxy
```

Logs:
```bash
sudo journalctl -u racinglines-proxy -n 50
```

## Config File

- **Location:** `/etc/racinglines/haproxy.cfg`
- **Edit directly** to adjust timeouts, thresholds, or add HTTPS
- **Reload config:** `sudo systemctl reload racinglines-proxy`

## Future Improvements

1. **HTTPS/TLS termination:** Move from external LB to local HAProxy (requires cert at `/etc/racinglines/certs/combined.pem`)
2. **Multiple prod/staging replicas:** Add more backends for load balancing
3. **Metrics export:** Add Prometheus endpoint for monitoring
4. **Separate VMs:** This is a short-term fix. Long-term: prod and staging on different VMs or containers.
