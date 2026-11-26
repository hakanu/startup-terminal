"""Sample HTTP API server for Startup Terminal demonstration.

Runs a lightweight HTTP server on port 8000 that logs requests, health checks,
and heartbeats with formatted timestamps.
"""

import datetime
import os
import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

PORT = int(os.environ.get("PORT", "5055"))
ENV = os.environ.get("ENV", "development")


class DemoHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        now = datetime.datetime.now().isoformat()
        response = f'{{"status": "ok", "time": "{now}", "env": "{ENV}"}}\n'
        self.wfile.write(response.encode("utf-8"))

    def log_message(self, format, *args):
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sys.stdout.write(f"[{now}] [HTTP] {self.address_string()} - {format % args}\n")
        sys.stdout.flush()


def simulate_traffic(port: int):
    """Generates occasional mock traffic logs so user sees active streaming logs."""
    time.sleep(1.5)
    mock_paths = ["/api/v1/health", "/api/v1/users", "/api/v1/items", "/api/v1/orders"]
    counter = 1
    while True:
        time.sleep(3)
        path = mock_paths[counter % len(mock_paths)]
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status = 200 if counter % 6 != 0 else 404
        latency = (counter * 17) % 65 + 12
        sys.stdout.write(f"[{now}] [API] GET http://127.0.0.1:{port}{path} -> HTTP {status} ({latency}ms)\n")
        sys.stdout.flush()
        counter += 1


def main():
    global PORT
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sys.stdout.write(f"[{now}] [INFO] Starting FastAPI/HTTP Demo Service...\n")
    sys.stdout.write(f"[{now}] [INFO] Environment: {ENV} | Target Port: {PORT} | PID: {os.getpid()}\n")
    sys.stdout.flush()

    server = None
    for candidate_port in [PORT, 5055, 5080, 8888, 0]:
        try:
            server = HTTPServer(("127.0.0.1", candidate_port), DemoHandler)
            PORT = server.server_port
            break
        except Exception:
            continue

    if not server:
        sys.stderr.write(f"[{now}] [ERROR] Could not bind to any test port.\n")
        sys.exit(1)

    try:
        sys.stdout.write(f"[{now}] [READY] Server listening on http://127.0.0.1:{PORT}\n")
        sys.stdout.flush()

        traffic_thread = threading.Thread(target=simulate_traffic, args=(PORT,), daemon=True)
        traffic_thread.start()

        server.serve_forever()
    except KeyboardInterrupt:
        sys.stdout.write(f"\n[{now}] [SHUTDOWN] Received interrupt, stopping server...\n")
    except Exception as e:
        sys.stderr.write(f"[{now}] [ERROR] Server error: {e}\n")
        sys.stderr.flush()
        sys.exit(1)


if __name__ == "__main__":
    main()
