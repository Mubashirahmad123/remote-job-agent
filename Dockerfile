FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive \
    PLAYWRIGHT_HEADLESS=true \
    DOCKER_CONTAINER=1

WORKDIR /app

# Install OS build dependencies, fonts for Unicode PDF generation, and utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libffi-dev \
    wget \
    curl \
    git \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install -r requirements.txt

# Install Playwright browser and all system OS dependencies
# (crawl4ai has no `install` module in 0.3.x — `python -m crawl4ai.install`
# breaks the build; the library reuses this same Chromium at runtime)
RUN playwright install --with-deps chromium

# Create directories for persistent volumes
RUN mkdir -p data logs apply_packages cover_letters resumes screenshots cache

# Copy application source code (secrets, logs, and venv are excluded by .dockerignore)
COPY . .

CMD ["python", "main.py", "crewai"]
