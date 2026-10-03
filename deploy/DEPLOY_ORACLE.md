# Deploying for Free on Oracle Cloud Always Free

This runs the full stack — FastAPI API + Command Center dashboard, the 24/7
scheduler, and Caddy (HTTPS) — on Oracle's **Always Free** ARM VM for $0/month.
It is the only genuinely free target with a persistent disk, enough RAM for
Playwright/Chromium, and no sleep/scale-to-zero.

```
Internet ──443/80──> Caddy (TLS) ──> api:8000 ──> Google Sheets / local cache
                                     scheduler  ──> scrape every Mon & Thu
```

Target the `main` branch, not a feature branch.

---

## 1. Create the VM

Oracle Console → **Compute → Instances → Create instance**:

| Setting | Value |
|---|---|
| Image | Canonical Ubuntu 22.04 (or 24.04) |
| Shape | **VM.Standard.A1.Flex** (Ampere ARM) — Always Free |
| OCPU / RAM | **4 OCPU / 24 GB** (the full Always Free allowance) |
| Boot volume | 50 GB (up to 200 GB free) |
| SSH keys | Generate a key pair and download the private key |

> The AMD micro shape (1/8 OCPU, 1 GB) is also free but too small to build and
> run the Playwright image. Use the ARM Ampere shape.
>
> Capacity for `VM.Standard.A1.Flex` is sometimes exhausted — retry, or pick a
> different Availability Domain.

Note the **public IP address**.

## 2. Open the ports in the VCN

Instance → **Primary VNIC → Subnet → Security Lists → Default Security List**,
add **Ingress** rules:

| Source | Protocol | Destination port |
|---|---|---|
| `0.0.0.0/0` | TCP | `80` |
| `0.0.0.0/0` | TCP | `443` |

Port `22` is already open. Without these, the VM firewall is irrelevant — the
cloud network drops the traffic first.

## 3. Bootstrap the VM

```bash
ssh -i /path/to/ssh-key.key ubuntu@<VM_PUBLIC_IP>

git clone https://github.com/Mubashirahmad123/remote-job-agent.git
cd remote-job-agent
sudo bash deploy/setup-vm.sh
```

The script installs Docker Engine + the Compose plugin, opens `80/443` in ufw,
and creates the empty runtime files (`seen_jobs.json`, `scraped_jobs.json`,
`curated_jobs.json`) and output directories that compose bind-mounts.

Log out and back in (or `newgrp docker`) so group membership applies.

## 4. Copy secrets onto the VM

From your **local** machine, in the repo root:

```bash
scp -i /path/to/ssh-key.key .env keys.json my_cv.pdf \
  ubuntu@<VM_PUBLIC_IP>:~/remote-job-agent/
```

These are gitignored and deliberately absent from the repo. Never commit them.

## 5. Configure `.env`

On the VM, edit `~/remote-job-agent/.env`:

```env
# Required: the API refuses a non-local bind without it
API_TOKEN=<long-random-secret>          # e.g. openssl rand -hex 32

# Reverse proxy address
SITE_ADDRESS=:80                        # bare IP now; a hostname later for HTTPS

TZ=Asia/Kolkata
GOOGLE_SHEETS_ID=<your sheet id>
GEMINI_API_KEY=<...>                    # at least one LLM key
```

Generate the token with `openssl rand -hex 32`. Keep it secret — it is the only
thing protecting your dashboard.

## 6. Launch

```bash
cd ~/remote-job-agent
docker compose up -d --build
```

Starts three services: `api` (dashboard + endpoints), `scheduler` (Mon/Thu),
and `caddy` (reverse proxy). First build compiles the Playwright image and
takes several minutes on ARM.

## 7. Verify

```bash
docker compose ps
docker compose logs -f api
curl -H "Authorization: Bearer <API_TOKEN>" http://localhost/api/health
# -> {"status":"ok","sheets_configured":true,"data_source":"sheets"}
```

Open the dashboard **once** with the token in the URL:

```
http://<VM_PUBLIC_IP>/?token=<API_TOKEN>
```

`frontend/js/auth-bootstrap.js` stores it in `localStorage` and strips it from
the address bar, so subsequent visits to `http://<VM_PUBLIC_IP>/` just work.

## 8. A hostname + HTTPS (optional, still free)

1. Get a free hostname — e.g. [DuckDNS](https://www.duckdns.org) gives you
   `yourname.duckdns.org`; point it at the VM's public IP.
2. Set `SITE_ADDRESS=yourname.duckdns.org` in `.env`.
3. `docker compose up -d` (recreates Caddy; it fetches a Let's Encrypt cert
   automatically over port 80/443).

Then use `https://yourname.duckdns.org/?token=<API_TOKEN>`.

---

## Operations

```bash
# Logs
docker compose logs -f api
docker compose logs -f scheduler
tail -f logs/scraper.log          # scheduler writes here

# Update to latest main
git pull
docker compose up -d --build

# One-off CLI tasks (uses the same image)
docker compose run --rm runner python main.py simple
docker compose run --rm runner python track.py --stats
docker compose run --rm runner python -m pytest tests/

# Restart / stop / tear down
docker compose restart api
docker compose down
docker compose down -v            # also drops Caddy's cert volume
```

**Back up** the state that is not in Google Sheets: `seen_jobs.json`,
`curated_jobs.json`, `scraped_jobs.json`, `data/`, and generated
`resumes/` / `cover_letters/`. Everything else is reproducible.

---

## Cost & caveats

- **Truly $0** within the Always Free limits (4 OCPU / 24 GB Ampere, 200 GB
  block storage, 10 TB egress). A card is required at signup for identity
  verification only; Always Free resources are never charged.
- Oracle may **reclaim idle Always Free VMs** — the scheduler keeps the box
  active, but don't rely on this for anything critical.
- Ubuntu images on Oracle are generally clean; if `iptables` blocks traffic the
  `setup-vm.sh` script detects and patches a `REJECT` rule.
- `api/app.py` refuses a non-local bind without `API_TOKEN` — this is by design.
- Keep `--workers 1` (already set): the sheet cache is in-process per worker.
- The API and scheduler share bind-mounted JSON files. Avoid triggering a
  dashboard "Scrape Now" while the scheduler is mid-run.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Browser hangs / connection refused | VCN ingress for 80/443 not added (§2), or ufw not enabled |
| `Refusing non-local bind without API_TOKEN` | Set `API_TOKEN` in `.env`, then `docker compose up -d api` |
| `401 Unauthorized` in the UI | Reopen `/?token=<API_TOKEN>` to refresh localStorage |
| `data_source: snapshot` | Sheets unreachable — check `keys.json` and that the sheet is shared with the service account email |
| Caddy can't get a cert | `SITE_ADDRESS` must be a real hostname resolving to the VM, and 80/443 open |
| Build killed on ARM | Use the 4 OCPU / 24 GB shape; ensure swap or retry |
