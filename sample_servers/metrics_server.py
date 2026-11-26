"""Sample Metrics Collector for Startup Terminal demonstration.

Emits periodic system telemetry, CPU, Memory, and Disk stats with timestamps.
"""

import datetime
import os
import random
import sys
import time


def main():
    pid = os.getpid()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sys.stdout.write(f"[{now}] [METRICS] Collector daemon started (PID: {pid})\n")
    sys.stdout.write(f"[{now}] [METRICS] Polling system stats every 3 seconds...\n")
    sys.stdout.flush()

    cycle = 0
    while True:
        try:
            time.sleep(3.0)
            cycle += 1
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cpu = round(random.uniform(4.5, 38.0), 1)
            mem = round(random.uniform(45.0, 72.0), 1)
            net_in = round(random.uniform(1.2, 18.5), 2)
            net_out = round(random.uniform(0.5, 9.8), 2)

            sys.stdout.write(
                f"[{now}] [METRICS] Cycle #{cycle} | CPU: {cpu}% | RAM: {mem}% | In: {net_in}MB/s | Out: {net_out}MB/s\n"
            )
            sys.stdout.flush()
        except KeyboardInterrupt:
            sys.stdout.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [METRICS] Collector stopped.\n")
            break


if __name__ == "__main__":
    main()
