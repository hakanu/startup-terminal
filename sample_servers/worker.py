"""Sample Background Worker for Startup Terminal demonstration.

Simulates an asynchronous job queue worker processing items, generating logs
and datetimes at regular intervals.
"""

import datetime
import os
import random
import sys
import time

CONCURRENCY = os.environ.get("WORKER_CONCURRENCY", "1")


def main():
    pid = os.getpid()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sys.stdout.write(f"[{now}] [WORKER] Initializing worker engine (PID: {pid})...\n")
    sys.stdout.write(f"[{now}] [WORKER] Concurrency: {CONCURRENCY} threads | Queue: 'default-tasks'\n")
    sys.stdout.flush()

    time.sleep(1.5)
    sys.stdout.write(f"[{now}] [WORKER] Connected to Redis queue on 127.0.0.1:6379\n")
    sys.stdout.write(f"[{now}] [WORKER] Listening for tasks...\n")
    sys.stdout.flush()

    job_id = 1000
    task_types = [
        "emails.send_welcome_notification",
        "reports.generate_monthly_pdf",
        "sync.refresh_cache_keys",
        "images.resize_user_avatars",
        "billing.process_subscription_cycle",
    ]

    while True:
        try:
            time.sleep(random.uniform(2.5, 5.0))
            job_id += 1
            task = random.choice(task_types)
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            sys.stdout.write(f"[{now}] [JOB-{job_id}] Received task '{task}'\n")
            sys.stdout.flush()

            duration_ms = random.randint(45, 450)
            time.sleep(duration_ms / 1000.0)

            # Occasionally emit a warning or error to showcase stderr/color formatting
            if random.random() < 0.15:
                sys.stderr.write(f"[{now}] [WARN] [JOB-{job_id}] Slow response warning: took {duration_ms}ms (>150ms threshold)\n")
                sys.stderr.flush()

            sys.stdout.write(f"[{now}] [JOB-{job_id}] Task completed successfully in {duration_ms}ms\n")
            sys.stdout.flush()
        except KeyboardInterrupt:
            sys.stdout.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [WORKER] Graceful shutdown requested.\n")
            break


if __name__ == "__main__":
    main()
