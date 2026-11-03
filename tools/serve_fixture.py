#!/usr/bin/env python3
"""Serve Greenhouse fixture via HTTP for testing."""

import http.server
import socketserver
import threading
import time
import sys
from pathlib import Path

PORT = 80
FIXTURE_DIR = Path(r'C:\Users\Mubashir1\remote-job-agent\tools')

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FIXTURE_DIR), **kwargs)
    
    def end_headers(self):
        # Allow CORS for local testing
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()

def run_server():
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"Serving fixture at http://localhost:{PORT}/greenhouse_fixture.html")
        httpd.serve_forever()

if __name__ == "__main__":
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    print("Server started. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")