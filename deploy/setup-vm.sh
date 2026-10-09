#!/usr/bin/env bash
#
# Oracle Cloud "Always Free" VM bootstrap for remote-job-agent.
#
# Tested on Ubuntu 22.04 / 24.04 (Ampere A1, arm64). Run from the repo root:
#
#   sudo bash deploy/setup-vm.sh
#
# Installs Docker Engine + Compose plugin, opens ports 80/443, and creates the
# empty runtime files that docker-compose bind-mounts (a fresh clone lacks them,
# and Docker would otherwise turn those paths into directories).

set -euo pipefail

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\n\033[1;33m!!  %s\033[0m\n' "$*"; }

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root:  sudo bash deploy/setup-vm.sh" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_USER="${SUDO_USER:-root}"

log "Repo root: ${REPO_ROOT}  (user: ${TARGET_USER})"

# --- APT prerequisites -------------------------------------------------------
log "Installing base packages"
apt-get update
apt-get install -y --no-install-recommends \
  ca-certificates curl gnupg git ufw

# --- Docker Engine (official repo) ------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  log "Installing Docker Engine + Compose plugin"
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc

  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list

  apt-get update
  apt-get install -y \
    docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
else
  log "Docker already installed — skipping"
fi

systemctl enable --now docker

if [[ "${TARGET_USER}" != "root" ]]; then
  usermod -aG docker "${TARGET_USER}"
  log "Added ${TARGET_USER} to the docker group (re-login for it to take effect)"
fi

# --- Firewall ----------------------------------------------------------------
# Docker publishes ports by inserting its own iptables rules that bypass ufw;
# the Oracle VCN Security List still has to allow 80/443 ingress regardless.
log "Configuring ufw (SSH + 80 + 443)"
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable || true

# Oracle's Ubuntu images are usually clean; some Oracle Linux-derived images ship
# an iptables REJECT at the end of INPUT. Patch it only if detected.
if command -v iptables >/dev/null 2>&1 && iptables -L INPUT -n 2>/dev/null | grep -q REJECT; then
  if iptables -C INPUT -p tcp --dport 80 -j ACCEPT 2>/dev/null; then
    log "iptables already allows 80/443"
  else
    warn "Detected Oracle iptables REJECT rule — inserting ACCEPT for 80/443"
    iptables -I INPUT 1 -p tcp --dport 80 -j ACCEPT
    iptables -I INPUT 1 -p tcp --dport 443 -j ACCEPT
    command -v netfilter-persistent >/dev/null 2>&1 && netfilter-persistent save || true
  fi
fi

# --- Runtime files that compose bind-mounts -----------------------------------
log "Ensuring runtime files/dirs exist"
cd "${REPO_ROOT}"
[[ -f seen_jobs.json   ]] || printf '{}\n'  > seen_jobs.json
[[ -f scraped_jobs.json ]] || printf '[]\n' > scraped_jobs.json
[[ -f curated_jobs.json ]] || printf '[]\n' > curated_jobs.json
mkdir -p data logs apply_packages resumes cover_letters screenshots cache

# The container image runs as an unprivileged user (Dockerfile: `USER agent`)
# whose UID/GID are build args. Those MUST match the owner of the directories
# bind-mounted above, or the app starts and then cannot write to its own
# volumes — which looks like a mysterious permission bug at the worst possible
# time. Chown by numeric ID and record the IDs where docker-compose.yml can
# interpolate them.
TARGET_UID="$(id -u "${TARGET_USER}" 2>/dev/null || echo 1000)"
TARGET_GID="$(id -g "${TARGET_USER}" 2>/dev/null || echo 1000)"
if [[ "${TARGET_USER}" == "root" ]]; then
  warn "SUDO_USER is root, so the bind-mounted volumes would be root-owned and"
  warn "the non-root container could not write them. Creating a normal user and"
  warn "re-running this script is the fix; falling back to 1000:1000 for now."
  TARGET_UID=1000; TARGET_GID=1000
fi
chown -R "${TARGET_UID}:${TARGET_GID}" data logs apply_packages resumes \
  cover_letters screenshots cache seen_jobs.json scraped_jobs.json curated_jobs.json 2>/dev/null || true

# docker compose reads ./.env for \${RJA_APP_UID} interpolation in the build args.
if [[ -f .env ]]; then
  grep -q '^RJA_APP_UID=' .env || printf '\n# Container runtime user; must own the bind-mounted dirs above.\nRJA_APP_UID=%s\nRJA_APP_GID=%s\n' "${TARGET_UID}" "${TARGET_GID}" >> .env
  log "Container will run as UID ${TARGET_UID} / GID ${TARGET_GID} (matches ${TARGET_USER})"
else
  warn ".env does not exist yet. After creating it, add these two lines so the"
  warn "image's non-root user matches the volume owner:"
  warn "    RJA_APP_UID=${TARGET_UID}"
  warn "    RJA_APP_GID=${TARGET_GID}"
fi

# --- Secrets sanity check -----------------------------------------------------
missing=()
[[ -f .env        ]] || missing+=(".env")
[[ -f keys.json   ]] || missing+=("keys.json")
[[ -f my_cv.pdf   ]] || missing+=("my_cv.pdf")

cat <<'EOF'

------------------------------------------------------------------
Next steps
------------------------------------------------------------------
1. Copy secrets into the repo (from your local machine):

   scp .env keys.json my_cv.pdf ubuntu@<VM_PUBLIC_IP>:~/remote-job-agent/

2. In .env make sure these are set:

   API_TOKEN=<long-random-secret>     # required for the public bind
   SITE_ADDRESS=:80                   # bare IP, OR jobs.example.com for HTTPS
   TZ=Asia/Kolkata

3. Build + start the API, scheduler and reverse proxy:

   docker compose up -d --build

4. Health check (server-to-server, uses the API_TOKEN directly):

   curl -H "Authorization: Bearer <API_TOKEN>" http://localhost/api/health

5. Create the dashboard login, THEN sign in from a browser:

   docker compose exec api python create_user.py <username>

   Open http://<VM_PUBLIC_IP>/ — you'll land on the login page. Sign in with
   the username/password you just created; the session is an HttpOnly cookie
   that lasts 7 days (SESSION_TTL_HOURS in .env).

   The API_TOKEN is SERVER-SIDE ONLY. Never put it in a URL: the old
   `/?token=<API_TOKEN>` flow was removed, and the dashboard now deletes any
   legacy `rja_api_token` key it finds in localStorage.
EOF

if [[ ${#missing[@]} -gt 0 ]]; then
  warn "Still missing: ${missing[*]}"
fi

log "Bootstrap complete"
