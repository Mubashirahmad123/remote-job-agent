import schedule
import time
import subprocess
import os
import signal
import sys
from datetime import datetime

from tools.artifact_retention import cleanup_artifacts

# cp1252 consoles (plain Windows cmd/PowerShell) cannot encode the emoji
# banners this daemon prints; degrade to "?" instead of crashing the 24/7 loop.
try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

def signal_handler(sig, frame):
    print('\n👋 Scheduler stopped gracefully!')
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

def run_artifact_cleanup():
    """Delete generated artifacts (resumes/packages/letters/screenshots) older
    than ARTIFACT_RETENTION_DAYS (default 4). Runs at startup and daily, so a
    scrape-heavy week cannot pile the folders up again."""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"🧹 Running artifact cleanup at {timestamp}")
    try:
        result = cleanup_artifacts()
        kb = result['bytes_freed'] / 1024
        print(f"   ✅ Retention: {result['retention_days']} days — "
              f"{result['deleted_files']} files / {result['deleted_dirs']} dirs removed, {kb:.0f} KB freed")
    except Exception as e:
        # Loud but non-fatal: a broken retention window must not kill the
        # scheduler — the scrape runs regardless, cleanup retries next day.
        print(f"   ⚠️ Artifact cleanup failed: {e}")

def run_scraper():
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"🚀 Running job scraper at {timestamp}")
    
    try:
        # We're already in the right directory
        result = subprocess.run([
            sys.executable,
            "main.py"
        ], capture_output=True, text=True, timeout=3600)  # 1 hour timeout
        
        # Ensure logs directory exists
        os.makedirs("logs", exist_ok=True)
        
        # Log the output
        with open("logs/scraper.log", "a", encoding="utf-8") as f:
            f.write(f"\n{'='*50}\n")
            f.write(f"Run started: {timestamp}\n")
            f.write(f"{'='*50}\n")
            f.write(result.stdout)
            if result.stderr:
                f.write(f"\n--- ERRORS ---\n{result.stderr}")
            f.write(f"\nRun completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Exit code: {result.returncode}\n")
        
        if result.returncode == 0:
            print("✅ Job scraper completed successfully!")
        else:
            print(f"❌ Job scraper failed with exit code: {result.returncode}")
            
    except subprocess.TimeoutExpired:
        print("⏰ Job scraper timed out (1 hour limit)")
    except Exception as e:
        print(f"💥 Error running scraper: {e}")
        with open("logs/scraper.log", "a", encoding="utf-8") as f:
            f.write(f"\nERROR: {e}\n")

def next_run_time():
    """Calculate when the next scraper run will be"""
    now = datetime.now()
    next_run = schedule.next_run()
    if next_run:
        time_diff = next_run - now
        hours = int(time_diff.total_seconds() // 3600)
        minutes = int((time_diff.total_seconds() % 3600) // 60)
        return f"{hours}h {minutes}m"
    return "Unknown"

# Schedule for Monday and Thursday at 9:00 AM
schedule.every().monday.at("09:00").do(run_scraper)
schedule.every().thursday.at("09:00").do(run_scraper)

# Artifact retention: daily sweep (plus the startup run below)
schedule.every().day.at("09:30").do(run_artifact_cleanup)

print("🎯 Remote Job Scraper Scheduler")
print("="*40)
print("📅 Schedule: Every Monday and Thursday at 9:00 AM")
print("🧹 Artifacts: daily 09:30 — delete generated files older than ARTIFACT_RETENTION_DAYS")
print("📁 Logs: logs/scraper.log")
print("⏹️  Press Ctrl+C to stop")
print("="*40)

# Sweep once at startup so a long-running daemon doesn't wait a day to clean
run_artifact_cleanup()

# Show next scheduled run
if schedule.jobs:
    print(f"⏰ Next run in: {next_run_time()}")
print()

while True:
    schedule.run_pending()
    time.sleep(60)  # Check every minute
