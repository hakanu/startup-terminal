"""Service runner (log relay) for Startup Terminal.

Launched by ProcessManager as the root process of every service. It starts the real
command, timestamps each stdout/stderr line into a persistent log file, rotates that file,
and exits with the command's exit code.

Because it is independent of the GUI, services keep running (and logging) while
Startup Terminal restarts; the new GUI instance re-attaches by tailing the log file.

Log line format (UTF-8, one entry per line):
    2026-10-24T19:08:40.202<TAB>stdout<TAB>text

Must only import the standard library: it runs with `python -I`.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import threading


def open_append(path: str) -> int:
    """Opens `path` for atomic appends and returns an fd for os.write().

    Several processes append to the same log (this relay and the GUI). Python's "a" mode on
    Windows only emulates appending (seek to end, then write), so concurrent writers can
    overwrite each other's lines. An append-only handle (FILE_APPEND_DATA without
    FILE_WRITE_DATA) makes the OS place every write at the current end of file atomically.
    FILE_SHARE_DELETE lets the relay rotate (rename) the file while others have it open.
    """
    if sys.platform != "win32":
        return os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)

    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    FILE_APPEND_DATA, FILE_READ_ATTRIBUTES, SYNCHRONIZE = 0x0004, 0x0080, 0x00100000
    SHARE_ALL = 0x1 | 0x2 | 0x4  # read | write | delete
    OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL = 4, 0x80
    handle = kernel32.CreateFileW(
        path, FILE_APPEND_DATA | FILE_READ_ATTRIBUTES | SYNCHRONIZE, SHARE_ALL,
        None, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, None,
    )
    if handle is None or handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    return msvcrt.open_osfhandle(handle, 0)


def format_log_line(text: str, stream: str) -> bytes:
    ts = datetime.datetime.now().isoformat(timespec="milliseconds")
    return f"{ts}\t{stream}\t{text}\n".encode("utf-8")


class RotatingLog:
    """Appends timestamped lines to a file, rotating it to `<file>.1` past max_bytes."""

    def __init__(self, path: str, max_bytes: int):
        self.path = path
        self.max_bytes = max_bytes
        self.lock = threading.Lock()
        self.fd = open_append(path)

    def write(self, text: str, stream: str):
        line = format_log_line(text, stream)
        with self.lock:
            os.write(self.fd, line)  # one write call = one atomic append
            if os.fstat(self.fd).st_size > self.max_bytes:
                self._rotate()

    def _rotate(self):
        os.close(self.fd)
        try:
            os.replace(self.path, self.path + ".1")
        except OSError:
            # The GUI may be reading the file at this instant; retry on a later line.
            pass
        self.fd = open_append(self.path)


def _pump(pipe, log: RotatingLog, stream: str):
    try:
        for raw_line in iter(pipe.readline, b""):
            text = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
            if text:
                log.write(text, stream)
    except Exception:
        pass
    finally:
        try:
            pipe.close()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", required=True)
    parser.add_argument("--max-bytes", type=int, default=10 * 1024 * 1024)
    parser.add_argument("--spec", required=True, help='JSON: {"args": str|list, "shell": bool}')
    opts = parser.parse_args()

    spec = json.loads(opts.spec)
    os.makedirs(os.path.dirname(opts.log), exist_ok=True)
    log = RotatingLog(opts.log, opts.max_bytes)

    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NO_WINDOW

    try:
        proc = subprocess.Popen(
            spec["args"],
            shell=bool(spec.get("shell")),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            creationflags=creation_flags,
        )
    except Exception as exc:
        log.write(f"Failed to launch command: {exc}", "stderr")
        return 1

    log.write(f"Process launched with PID: {proc.pid} (CWD: {os.getcwd()})", "system")

    readers = [
        threading.Thread(target=_pump, args=(proc.stdout, log, "stdout"), daemon=True),
        threading.Thread(target=_pump, args=(proc.stderr, log, "stderr"), daemon=True),
    ]
    for t in readers:
        t.start()

    exit_code = proc.wait()
    for t in readers:
        t.join(timeout=2.0)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
