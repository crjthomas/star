#!/usr/bin/env python3
"""
Single-command launcher for the full alert system.

Starts the webhook server (dashboard + API) and the market scanner (main.py)
so you get hands-free alerts: the scanner finds qualifying stocks and pushes
them to the dashboard automatically. No manual ticker search needed.

Usage:
    python run_alert_system.py

Then open http://localhost:8000/alerts/dashboard/index.html
Press Ctrl+C to stop both.
"""
import atexit
import os
import signal
import subprocess
import sys
import time

def main():
    # Ensure we're in project root so imports and .env work
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    # Start webhook server in subprocess (dashboard + API; receives pushed alerts)
    webhook_cmd = [
        sys.executable, "-m", "uvicorn",
        "alerts.webhook_server:app",
        "--host", "0.0.0.0",
        "--port", "8000",
    ]
    env = os.environ.copy()
    env.setdefault("WEBHOOK_SERVER_URL", "http://localhost:8000")

    print("Starting webhook server (dashboard + API) on http://localhost:8000 ...")
    proc = subprocess.Popen(
        webhook_cmd,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )

    def kill_webhook():
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
    atexit.register(kill_webhook)
    signal.signal(signal.SIGINT, lambda s, f: (kill_webhook(), sys.exit(0)))
    signal.signal(signal.SIGTERM, lambda s, f: (kill_webhook(), sys.exit(0)))

    # Give webhook time to bind
    time.sleep(4)
    if proc.poll() is not None:
        err = proc.stderr.read().decode() if proc.stderr else ""
        print("Webhook server failed to start:", err or "see logs")
        sys.exit(1)

    print("Webhook server ready. Starting market scanner (all stocks)...")
    print("Dashboard: http://localhost:8000/alerts/dashboard/index.html")
    print("Press Ctrl+C to stop both.\n")

    try:
        import asyncio
        from main import main as main_async
        asyncio.run(main_async())
    finally:
        kill_webhook()

if __name__ == "__main__":
    main()
