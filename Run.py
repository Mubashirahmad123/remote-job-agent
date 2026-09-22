#!/usr/bin/env python3
"""
Remote Job Agent — Universal Start Script
Works on Windows, Mac, and Linux
"""

import os
import sys
import subprocess
import platform

# ── Colors ────────────────────────────────────────────────────────────────────
class C:
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    RED    = "\033[91m"
    CYAN   = "\033[96m"
    BOLD   = "\033[1m"
    RESET  = "\033[0m"

def ok(msg):   print(f"  {C.GREEN}✓{C.RESET} {msg}")
def err(msg):  print(f"  {C.RED}✗ ERROR: {msg}{C.RESET}")
def info(msg): print(f"  {C.CYAN}→{C.RESET} {msg}")
def warn(msg): print(f"  {C.YELLOW}⚠ {msg}{C.RESET}")
def header(msg):
    print(f"\n{C.BOLD}{C.CYAN}{'='*50}{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}  {msg}{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}{'='*50}{C.RESET}\n")

# ── Detect OS ──────────────────────────────────────────────────────────────────
OS = platform.system()  # 'Windows', 'Linux', 'Darwin'

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT    = os.path.dirname(os.path.abspath(__file__))
VENV    = os.path.join(ROOT, "venv")
PYTHON  = (
    os.path.join(VENV, "Scripts", "python.exe") if OS == "Windows"
    else os.path.join(VENV, "bin", "python")
)
PIP     = (
    os.path.join(VENV, "Scripts", "pip.exe") if OS == "Windows"
    else os.path.join(VENV, "bin", "pip")
)

# ──────────────────────────────────────────────────────────────────────────────
def check_python_version():
    major, minor = sys.version_info[:2]
    if major < 3 or minor < 11:
        err(f"Python 3.11+ required. You have {major}.{minor}")
        sys.exit(1)
    ok(f"Python {major}.{minor} detected ({OS})")

def is_docker():
    return os.path.exists("/.dockerenv") or os.environ.get("DOCKER_CONTAINER") == "1"

def check_venv():
    if is_docker():
        ok("Running inside Docker container (system Python)")
        return
    if not os.path.exists(PYTHON):
        err("Virtual environment not found.")
        info("Run:  python run.py --setup")
        sys.exit(1)
    ok("Virtual environment found")

def check_env_file():
    env_path = os.path.join(ROOT, ".env")
    if not os.path.exists(env_path):
        err(".env file not found.")
        info("Copy .env.example to .env and fill in your keys.")
        sys.exit(1)

    # Check required keys are not empty (need at least one LLM key)
    required = ["GOOGLE_SHEETS_ID", "GOOGLE_SERVICE_ACCOUNT"]
    llm_keys = ["GEMINI_API_KEY", "MISTRAL_API_KEY", "GROQ_API_KEY"]
    missing = []
    with open(env_path) as f:
        content = f.read()
    for key in required:
        if key + "=" not in content or key + "=\n" in content or key + "=your" in content:
            missing.append(key)
    # Need at least one LLM provider key
    if not any(k + "=" in content and k + "=\n" not in content for k in llm_keys):
        missing.append("GEMINI_API_KEY or MISTRAL_API_KEY or GROQ_API_KEY")
    if missing:
        warn(f"These .env keys look empty or unset: {', '.join(missing)}")
    else:
        ok(".env file looks good")

def check_keys_json():
    keys_path = os.path.join(ROOT, "keys.json")
    if not os.path.exists(keys_path):
        err("keys.json not found.")
        info("Download your Google Service Account key and save it as keys.json")
        sys.exit(1)
    ok("keys.json found")

def get_run_mode():
    env_path = os.path.join(ROOT, ".env")
    with open(env_path) as f:
        for line in f:
            if line.startswith("RUN_MODE="):
                return line.strip().split("=", 1)[1]
    return "crewai"

def run_agent():
    main_py = os.path.join(ROOT, "main.py")
    if not os.path.exists(main_py):
        err("main.py not found. Are you in the right folder?")
        sys.exit(1)
    py_exec = sys.executable if is_docker() else PYTHON
    subprocess.run([py_exec, main_py], cwd=ROOT)

# ── Setup Mode ─────────────────────────────────────────────────────────────────
def run_setup():
    header("REMOTE JOB AGENT — FIRST TIME SETUP")

    # 1. Check Python
    check_python_version()

    # 2. Create venv
    if os.path.exists(PYTHON):
        ok("Virtual environment already exists, skipping")
    else:
        info("Creating virtual environment...")
        subprocess.run([sys.executable, "-m", "venv", "venv"], cwd=ROOT, check=True)
        ok("Virtual environment created")

    # 3. Upgrade pip and install uv for fast, conflict-free dependency resolution
    info("Upgrading pip and installing uv...")
    subprocess.run([PIP, "install", "--upgrade", "pip", "uv"], cwd=ROOT, check=True)

    # 4. Install requirements
    req = os.path.join(ROOT, "requirements.txt")
    if os.path.exists(req):
        info("Installing dependencies from requirements.txt...")
        uv_bin = (
            os.path.join(VENV, "Scripts", "uv.exe") if OS == "Windows"
            else os.path.join(VENV, "bin", "uv")
        )
        if os.path.exists(uv_bin):
            subprocess.run([uv_bin, "pip", "install", "-r", req], cwd=ROOT, check=True)
        else:
            subprocess.run([PIP, "install", "-r", req], cwd=ROOT, check=True)
        ok("Dependencies installed")
    else:
        warn("requirements.txt not found, skipping dependency install")

    # 5. Install Playwright Chromium
    info("Installing Playwright Chromium browser...")
    playwright_bin = (
        os.path.join(VENV, "Scripts", "playwright.exe") if OS == "Windows"
        else os.path.join(VENV, "bin", "playwright")
    )
    subprocess.run([playwright_bin, "install", "chromium"], cwd=ROOT, check=True)
    ok("Playwright Chromium installed")

    # 6. Crawl4AI setup
    info("Running Crawl4AI setup...")
    subprocess.run([PYTHON, "-m", "crawl4ai.install"], cwd=ROOT)
    ok("Crawl4AI setup done")

    # 7. Copy .env
    env_path    = os.path.join(ROOT, ".env")
    env_example = os.path.join(ROOT, ".env.example")
    if not os.path.exists(env_path):
        if os.path.exists(env_example):
            import shutil
            shutil.copy(env_example, env_path)
            ok(".env created from .env.example")
            warn("Open .env and fill in your API keys before running the agent")
        else:
            warn("No .env.example found — create .env manually")
    else:
        ok(".env already exists")

    print()
    header("SETUP COMPLETE")
    print("  Next steps:")
    print("  1. Make sure keys.json is in this folder")
    print("  2. Open .env and fill in your API keys")
    print("  3. Run:  python run.py\n")

# ── Main Run Mode ──────────────────────────────────────────────────────────────
def run_main():
    header("REMOTE JOB AGENT — STARTING")

    info(f"Operating System : {OS}")
    print()

    print("Checking environment...")
    check_python_version()
    check_venv()
    check_env_file()
    check_keys_json()

    mode = get_run_mode()
    print()
    info(f"RUN_MODE = {C.BOLD}{mode}{C.RESET}")
    print()

    header("RUNNING AGENT")
    run_agent()

    print()
    header("AGENT FINISHED")

# ── Entry Point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if "--setup" in sys.argv:
        run_setup()
    else:
        run_main()