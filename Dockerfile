FROM python:3.11-slim-bookworm

# PLAYWRIGHT_BROWSERS_PATH: Playwright's default browser location is
# /root/.cache/ms-playwright. This image installs Chromium as root (apt needs it)
# but RUNS as the unprivileged `agent` user below, which cannot read /root — so
# the install and the runtime lookup both use a world-readable path. It is an ENV
# rather than an ARG because Playwright resolves it again when the browser
# launches, not only during `playwright install`.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive \
    PLAYWRIGHT_HEADLESS=true \
    DOCKER_CONTAINER=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# The runtime user's UID/GID must match the owner of the host directories that
# docker-compose bind-mounts (./data, ./logs, ./resumes, ./screenshots, ...), or
# the app cannot write to its own volumes. deploy/setup-vm.sh derives them from
# `id -u "${SUDO_USER}"` and writes RJA_APP_UID/RJA_APP_GID into .env, which
# docker compose reads to fill these in. 1000:1000 is the conventional first
# user on Ubuntu and on the Oracle Cloud Ubuntu image, so a plain
# `docker build .` stays correct for the documented deployment.
ARG APP_UID=1000
ARG APP_GID=1000

WORKDIR /app

# Install OS build dependencies, fonts for Unicode PDF generation, and utilities
# tzdata provides /usr/share/zoneinfo so TZ=Asia/Kolkata works in scheduler
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libffi-dev \
    wget \
    curl \
    git \
    tzdata \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast, reliable dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Install Python dependencies
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

# Install Playwright browser and all system OS dependencies
# (crawl4ai has no `install` module in 0.3.x — `python -m crawl4ai.install`
# breaks the build; the library reuses this same Chromium at runtime)
# Runs as root and into PLAYWRIGHT_BROWSERS_PATH, so `agent` can read it later.
RUN playwright install --with-deps chromium

# Create the unprivileged runtime user and the persistent-volume mount points.
#
# Why not root: this container runs a headless browser that navigates to URLs
# taken from scraped job postings, and docker-compose bind-mounts ./.env and
# ./keys.json into it. `:ro` stops writes but not reads, so a browser or scraper
# compromise running as root walks away with the Google service-account private
# key and every API key in .env. Dropping to an unprivileged user does not make
# that unreadable on its own — the mount owner still matters — but it removes
# root from the container, which is what turns "read a mounted secret" into
# "also own the box, the docker socket path and the kernel surface".
RUN groupadd --gid "${APP_GID}" agent \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" \
         --create-home --home-dir /home/agent --shell /usr/sbin/nologin agent \
    && mkdir -p data logs apply_packages cover_letters resumes screenshots cache \
    && chown -R agent:agent /app /home/agent \
    && chmod -R a+rX /ms-playwright

# Copy application source code (secrets, logs, and venv are excluded by .dockerignore)
# --chown on the COPY rather than a later `chown -R`: a separate chown writes a
# second copy of every file into a new layer, roughly doubling image size.
COPY --chown=agent:agent . .

USER agent

CMD ["python", "main.py", "crewai"]
