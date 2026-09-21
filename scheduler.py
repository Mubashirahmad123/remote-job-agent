import schedule
import time
import subprocess
import os
import signal
import sys
from datetime import datetime

def signal_handler(sig, frame):
    print('\n👋 Scheduler stopped gracefully!')
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

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
        with open("logs/scraper.log", "a") as f:
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
        with open("logs/scraper.log", "a") as f:
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

print("🎯 Remote Job Scraper Scheduler")
print("="*40)
print("📅 Schedule: Every Monday and Thursday at 9:00 AM")
print("📁 Logs: logs/scraper.log")
print("⏹️  Press Ctrl+C to stop")
print("="*40)

# Show next scheduled run
if schedule.jobs:
    print(f"⏰ Next run in: {next_run_time()}")
print()

while True:
    schedule.run_pending()
    time.sleep(60)  # Check every minute
