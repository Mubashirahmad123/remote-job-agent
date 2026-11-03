import subprocess
import sys
import os

os.chdir(r"C:\Users\Mubashir1\remote-job-agent")
subprocess.Popen([r".venv\Scripts\python.exe", "-m", "uvicorn", "api.app:create_app", "--host", "0.0.0.0", "--port", "8000"])
print("API started on http://localhost:8000")