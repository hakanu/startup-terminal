"""Process Manager for Startup Terminal.

Manages running, monitoring, stopping, and logging commands/processes on Windows.
Provides real-time line-by-line log streaming with precise datetimes,
status tracking, process tree termination, and auto-restart on failure.

Each service runs under `service_runner.py` (a small log relay), which writes timestamped
output to a persistent log file. Running services are recorded in a state file, so a
restarted Startup Terminal re-attaches to them instead of killing and relaunching them.
"""

from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import psutil

from PySide6.QtCore import QObject, Signal, QTimer

from service_runner import format_log_line, open_append

RUNNER_SCRIPT = str(Path(__file__).resolve().parent / "service_runner.py")
LOG_MAX_BYTES = 10 * 1024 * 1024  # rotate <id>.log to <id>.log.1 past this size


def get_data_dir() -> Path:
    """%LOCALAPPDATA%/StartupTerminal - holds service logs and the running-state file."""
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    path = Path(base) / "StartupTerminal"
    (path / "logs").mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class LogEntry:
    timestamp: datetime.datetime
    text: str
    stream: str  # 'stdout', 'stderr', 'system'


class ServiceState:
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    FAILED = "FAILED"


class ManagedService:
    def __init__(self, config: Dict[str, Any], base_dir: str):
        self.id: str = config["id"]
        self.name: str = config["name"]
        self.command: str = config["command"]
        self.shell: str = config.get("shell", "cmd")
        self.cwd: Optional[str] = config.get("cwd")
        self.enabled: bool = config.get("enabled", True)
        self.auto_start: bool = config.get("auto_start", True)
        self.restart_on_failure: bool = config.get("restart_on_failure", False)
        self.restart_delay_sec: int = config.get("restart_delay_sec", 3)
        self.custom_env: Dict[str, str] = config.get("env") or {}

        # Resolve working directory
        if self.cwd:
            self.resolved_cwd = os.path.abspath(os.path.join(base_dir, self.cwd))
        else:
            self.resolved_cwd = base_dir

        self.state: str = ServiceState.STOPPED
        self.process: Optional[subprocess.Popen] = None
        self.pid: Optional[int] = None  # PID of the service_runner relay (root of the tree)
        self.started_at: Optional[datetime.datetime] = None
        self.stopped_at: Optional[datetime.datetime] = None
        self.exit_code: Optional[int] = None
        self.user_stopped: bool = False
        self.restart_timer: Optional[threading.Timer] = None

        # Stats
        self.cpu_percent: float = 0.0
        self.memory_mb: float = 0.0
        self.vram_mb: float = 0.0
        self.restart_count: int = 0
        self.detected_port: Optional[int] = None

        # Memory log buffer (filled by tailing the persistent log file)
        self.logs: List[LogEntry] = []
        self.max_logs: int = 5000

        # Persistent log file + tail position
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in self.id)
        self.log_path: Path = get_data_dir() / "logs" / f"{safe_id}.log"
        self.tail_pos: int = 0
        self.tail_ino: Optional[int] = None
        self.tail_partial: bytes = b""

    def add_log(self, text: str, stream: str = "stdout") -> LogEntry:
        entry = LogEntry(
            timestamp=datetime.datetime.now(),
            text=text,
            stream=stream,
        )
        self._append_entry(entry)
        return entry

    def _append_entry(self, entry: LogEntry):
        self.logs.append(entry)
        if len(self.logs) > self.max_logs:
            # Drop older entries
            self.logs = self.logs[-self.max_logs :]

    def clear_logs(self):
        self.logs.clear()


def _parse_log_line(line: str) -> Optional[LogEntry]:
    parts = line.split("\t", 2)
    if len(parts) != 3:
        return None
    try:
        ts = datetime.datetime.fromisoformat(parts[0])
    except ValueError:
        return None
    return LogEntry(timestamp=ts, text=parts[2], stream=parts[1])


class _PdhVramSampler:
    """Fast, zero-subprocess per-PID dedicated VRAM sampler via Windows PDH.

    Works across NVIDIA, AMD, and Intel GPUs under WDDM where NVML often reports
    NVML_VALUE_NOT_AVAILABLE for per-process memory.
    """

    def __init__(self):
        self._available = False
        self._pdh = None
        self._query = None
        self._counter = None
        if sys.platform == "win32":
            self._init_pdh()

    def _init_pdh(self):
        try:
            import ctypes
            import ctypes.wintypes as wt

            pdh = ctypes.WinDLL("pdh.dll")
            q = wt.HANDLE()
            if pdh.PdhOpenQueryW(None, 0, ctypes.byref(q)) != 0:
                return
            c = wt.HANDLE()
            if pdh.PdhAddEnglishCounterW(q, r"\GPU Process Memory(*)\Dedicated Usage", 0, ctypes.byref(c)) != 0:
                pdh.PdhCloseQuery(q)
                return
            self._pdh = pdh
            self._query = q
            self._counter = c
            self._available = True
        except Exception:
            self._available = False

    def sample(self) -> Dict[int, float]:
        """Returns {pid: dedicated_vram_mb} across all GPUs."""
        if not self._available or self._pdh is None:
            return {}
        try:
            import ctypes
            import ctypes.wintypes as wt
            import re

            class PDH_FMT_COUNTERVALUE(ctypes.Structure):
                _fields_ = [("CStatus", wt.DWORD), ("largeValue", ctypes.c_longlong)]

            class PDH_FMT_COUNTERVALUE_ITEM_W(ctypes.Structure):
                _fields_ = [("szName", wt.LPWSTR), ("FmtValue", PDH_FMT_COUNTERVALUE)]

            if self._pdh.PdhCollectQueryData(self._query) != 0:
                return {}

            buf_size = wt.DWORD(0)
            item_count = wt.DWORD(0)
            PDH_FMT_LARGE = 0x00000400
            self._pdh.PdhGetFormattedCounterArrayW(
                self._counter, PDH_FMT_LARGE, ctypes.byref(buf_size), ctypes.byref(item_count), None
            )
            if buf_size.value == 0 or item_count.value == 0:
                return {}

            raw = (ctypes.c_byte * buf_size.value)()
            ret = self._pdh.PdhGetFormattedCounterArrayW(
                self._counter, PDH_FMT_LARGE, ctypes.byref(buf_size), ctypes.byref(item_count), raw
            )
            if ret != 0:
                return {}

            items = ctypes.cast(raw, ctypes.POINTER(PDH_FMT_COUNTERVALUE_ITEM_W))
            pid_bytes: Dict[int, int] = {}
            for i in range(item_count.value):
                val = items[i].FmtValue.largeValue
                if val <= 0:
                    continue
                name = items[i].szName or ""
                m = re.search(r"pid_(\d+)_", name)
                if m:
                    pid = int(m.group(1))
                    pid_bytes[pid] = pid_bytes.get(pid, 0) + val
            return {pid: b / (1024.0 * 1024.0) for pid, b in pid_bytes.items()}
        except Exception:
            return {}


class ProcessManager(QObject):
    """Coordinates lifecycle and logs of all managed services."""

    # Signals for UI updates
    status_changed = Signal(str, str)  # (service_id, new_status)
    log_received = Signal(str, object, str, str)  # (service_id, timestamp, text, stream)
    stats_updated = Signal(str, float, float, float)  # (service_id, cpu_percent, memory_mb, vram_mb)

    def __init__(self, base_dir: str):
        super().__init__()
        self.base_dir = base_dir
        self.services: Dict[str, ManagedService] = {}
        self.max_log_lines = 5000
        self._vram_sampler = _PdhVramSampler()
        self._proc_cache: Dict[int, psutil.Process] = {}

        # When True (app restarting), services are left running and exits are ignored
        self.detached = False
        self.state_path = get_data_dir() / "state.json"
        self.state_lock = threading.Lock()
        self.file_lock = threading.Lock()

        # Timer for polling CPU/RAM stats
        self.stats_timer = QTimer(self)
        self.stats_timer.setInterval(2000)
        self.stats_timer.timeout.connect(self._poll_service_stats)
        self.stats_timer.start()

        # Timer for tailing service log files
        self.log_timer = QTimer(self)
        self.log_timer.setInterval(250)
        self.log_timer.timeout.connect(self._poll_logs)
        self.log_timer.start()

    def _safe_emit_status(self, svc_id: str, state: str):
        try:
            self.status_changed.emit(svc_id, state)
        except (RuntimeError, AttributeError):
            pass

    def _safe_emit_log(self, svc_id: str, timestamp, text: str, stream: str):
        try:
            self.log_received.emit(svc_id, timestamp, text, stream)
        except (RuntimeError, AttributeError):
            pass

    def _safe_emit_stats(self, svc_id: str, cpu: float, mem: float, vram: float = 0.0):
        try:
            self.stats_updated.emit(svc_id, cpu, mem, vram)
        except (RuntimeError, AttributeError):
            pass

    # ------------------------------------------------------------------ logging

    def log_system(self, service_id: str, text: str, stream: str = "system"):
        svc = self.services.get(service_id)
        if svc:
            self._log(svc, text, stream)

    def _log(self, svc: ManagedService, text: str, stream: str):
        """Appends a line to the service's log file; the tailer picks it up for the UI."""
        try:
            with self.file_lock:
                fd = open_append(str(svc.log_path))
                try:
                    os.write(fd, format_log_line(text, stream))
                finally:
                    os.close(fd)
        except OSError:
            # Log file unavailable: show the line in memory only
            entry = svc.add_log(text, stream)
            self._safe_emit_log(svc.id, entry.timestamp, entry.text, entry.stream)

    def _load_log_history(self, svc: ManagedService):
        """Loads the last max_logs entries from the log file and starts tailing at its end."""
        try:
            st = os.stat(svc.log_path)
        except OSError:
            return
        # Read exactly up to the stat'ed size: anything appended later is picked up by the
        # tailer from tail_pos (reading further here would show those lines twice).
        try:
            with open(svc.log_path, "rb") as f:
                data = f.read(st.st_size)
        except OSError:
            return
        *complete, partial = data.split(b"\n")
        for raw in deque(complete, maxlen=svc.max_logs):
            entry = _parse_log_line(raw.decode("utf-8", errors="replace").rstrip("\r"))
            if entry:
                svc._append_entry(entry)
        svc.tail_partial = partial
        svc.tail_pos = len(data)
        svc.tail_ino = st.st_ino

    def _read_new_bytes(self, svc: ManagedService) -> bytes:
        try:
            st = os.stat(svc.log_path)
        except OSError:
            return b""

        data = b""
        rotated = svc.tail_ino is not None and (st.st_ino != svc.tail_ino or st.st_size < svc.tail_pos)
        if rotated:
            # Finish the rotated file first, then continue from the start of the new one
            try:
                old = svc.log_path.with_name(svc.log_path.name + ".1")
                if os.stat(old).st_ino == svc.tail_ino:
                    with open(old, "rb") as f:
                        f.seek(svc.tail_pos)
                        data = f.read()
            except OSError:
                pass
            svc.tail_pos = 0
        svc.tail_ino = st.st_ino

        if st.st_size > svc.tail_pos:
            try:
                with open(svc.log_path, "rb") as f:
                    f.seek(svc.tail_pos)
                    chunk = f.read(st.st_size - svc.tail_pos)
                svc.tail_pos += len(chunk)
                data += chunk
            except OSError:
                pass
        return data

    def _poll_logs(self):
        for svc in list(self.services.values()):
            data = self._read_new_bytes(svc)
            if not data:
                continue
            data = svc.tail_partial + data
            *complete, svc.tail_partial = data.split(b"\n")
            for raw in complete:
                entry = _parse_log_line(raw.decode("utf-8", errors="replace").rstrip("\r"))
                if entry:
                    svc._append_entry(entry)
                    self._safe_emit_log(svc.id, entry.timestamp, entry.text, entry.stream)

    # ------------------------------------------------------------------ state file

    def _read_state(self) -> Dict[str, Any]:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _write_state_entry(self, svc_id: str, entry: Optional[Dict[str, Any]]):
        if self.detached:
            return
        with self.state_lock:
            state = self._read_state()
            if entry is None:
                if svc_id not in state:
                    return
                state.pop(svc_id, None)
            else:
                state[svc_id] = entry
            tmp = self.state_path.with_suffix(".tmp")
            try:
                tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
                os.replace(tmp, self.state_path)
            except OSError:
                pass

    def _try_adopt(self, svc: ManagedService):
        """Re-attaches to a service process left running by a previous app instance."""
        info = self._read_state().get(svc.id)
        if not info:
            return
        try:
            proc = psutil.Process(int(info["pid"]))
            # Guard against Windows reusing the PID for an unrelated process
            if abs(proc.create_time() - float(info["create_time"])) > 1.0:
                raise psutil.NoSuchProcess(int(info["pid"]))
        except (psutil.Error, KeyError, ValueError, TypeError):
            self._write_state_entry(svc.id, None)
            return

        svc.pid = proc.pid
        svc.process = None
        svc.user_stopped = False
        svc.restart_count = int(info.get("restart_count", 0))
        try:
            svc.started_at = datetime.datetime.fromisoformat(info["started_at"])
        except (KeyError, ValueError, TypeError):
            svc.started_at = datetime.datetime.now()
        svc.state = ServiceState.RUNNING
        self._log(svc, f"Re-attached to running service (PID: {proc.pid}) after Startup Terminal restart.", "system")
        threading.Thread(
            target=self._watch_process,
            args=(svc, proc.pid, proc.wait),
            daemon=True,
            name=f"ServiceWatcher-{svc.id}",
        ).start()

    def detach_all(self):
        """Leaves all services running (for an app restart): no more kills, restarts or state writes."""
        for svc in self.services.values():
            if svc.restart_timer:
                svc.restart_timer.cancel()
                svc.restart_timer = None
        self.detached = True
        self.stats_timer.stop()
        self.log_timer.stop()

    def reattach_all(self):
        """Undoes detach_all() if the restart could not go ahead."""
        self.detached = False
        self.stats_timer.start()
        self.log_timer.start()

    # ------------------------------------------------------------------ lifecycle

    def update_services_from_config(self, config_services: List[Dict[str, Any]], max_logs: int = 5000):
        """Syncs the services dictionary with the latest configuration."""
        self.max_log_lines = max_logs
        current_ids = set(self.services.keys())
        new_ids = set()

        for svc_cfg in config_services:
            svc_id = svc_cfg["id"]
            new_ids.add(svc_id)

            if svc_id in self.services:
                # Update existing service configuration (without stopping if running)
                svc = self.services[svc_id]
                svc.name = svc_cfg["name"]
                svc.command = svc_cfg["command"]
                svc.shell = svc_cfg.get("shell", "cmd")
                svc.enabled = svc_cfg.get("enabled", True)
                svc.auto_start = svc_cfg.get("auto_start", True)
                svc.restart_on_failure = svc_cfg.get("restart_on_failure", False)
                svc.restart_delay_sec = svc_cfg.get("restart_delay_sec", 3)
                svc.custom_env = svc_cfg.get("env") or {}
                svc.max_logs = max_logs
            else:
                svc = ManagedService(svc_cfg, self.base_dir)
                svc.max_logs = max_logs
                self.services[svc_id] = svc
                self._load_log_history(svc)
                self._try_adopt(svc)

            if not svc.enabled:
                # Disabled: stop it (also cancels any pending auto-restart)
                self.stop_service(svc_id)

        # Services removed from config
        removed_ids = current_ids - new_ids
        for r_id in removed_ids:
            self.stop_service(r_id)
            del self.services[r_id]

    def start_service(self, service_id: str) -> bool:
        """Starts a service by ID in a background thread."""
        svc = self.services.get(service_id)
        if not svc or self.detached:
            return False

        if not svc.enabled:
            self._log(svc, "Service is disabled. Enable it to start.", "system")
            return False

        if svc.state in (ServiceState.RUNNING, ServiceState.STARTING):
            return True

        if svc.restart_timer:
            svc.restart_timer.cancel()
            svc.restart_timer = None

        svc.user_stopped = False
        svc.state = ServiceState.STARTING
        self._safe_emit_status(svc.id, svc.state)

        # Launch process in worker thread to prevent UI freezing
        thread = threading.Thread(
            target=self._run_process_worker,
            args=(svc,),
            daemon=True,
            name=f"ServiceRunner-{svc.id}",
        )
        thread.start()
        return True

    def stop_service(self, service_id: str) -> bool:
        """Gracefully stops a service and all its child processes."""
        svc = self.services.get(service_id)
        if not svc or self.detached:
            return False

        svc.user_stopped = True
        if svc.restart_timer:
            svc.restart_timer.cancel()
            svc.restart_timer = None

        if svc.state == ServiceState.STOPPED:
            return True

        svc.state = ServiceState.STOPPING
        self._safe_emit_status(svc.id, svc.state)

        # Stop in background
        thread = threading.Thread(
            target=self._kill_process_tree,
            args=(svc,),
            daemon=True,
            name=f"ServiceStopper-{svc.id}",
        )
        thread.start()
        return True

    def restart_service(self, service_id: str):
        """Restarts a service."""
        svc = self.services.get(service_id)
        if not svc:
            return

        def _do_restart():
            self.stop_service(service_id)
            # Wait for process to terminate
            start_wait = time.time()
            while svc.state != ServiceState.STOPPED and time.time() - start_wait < 5.0:
                time.sleep(0.1)
            time.sleep(0.2)
            self.start_service(service_id)

        threading.Thread(target=_do_restart, daemon=True).start()

    def start_all(self):
        """Starts all enabled managed services."""
        for svc_id, svc in self.services.items():
            if svc.enabled:
                self.start_service(svc_id)

    def stop_all(self, wait: bool = False, timeout: float = 2.5):
        """Stops all managed services and kills entire process trees.

        If wait=True, synchronously waits for all processes and child trees to terminate.
        Does nothing after detach_all() (the app is restarting and services stay up).
        """
        if self.detached:
            return
        threads = []
        for svc in self.services.values():
            if svc.state in (ServiceState.RUNNING, ServiceState.STARTING, ServiceState.STOPPING) or svc.pid is not None or svc.process is not None:
                svc.user_stopped = True
                if svc.restart_timer:
                    svc.restart_timer.cancel()
                    svc.restart_timer = None
                svc.state = ServiceState.STOPPING
                self._safe_emit_status(svc.id, svc.state)

                t = threading.Thread(
                    target=self._kill_process_tree,
                    args=(svc,),
                    name=f"ServiceStopper-{svc.id}",
                )
                t.start()
                threads.append((svc, t))

        if wait:
            for svc, t in threads:
                t.join(timeout=timeout)
                # Extra check: force taskkill on Windows if any remnant PID
                if svc.pid and sys.platform == "win32":
                    try:
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(svc.pid)],
                            capture_output=True,
                            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
                            timeout=1.0,
                        )
                    except Exception:
                        pass
                svc.state = ServiceState.STOPPED
                self._write_state_entry(svc.id, None)
                self._safe_emit_status(svc.id, svc.state)

    @staticmethod
    def is_port_in_use(port: int) -> bool:
        import socket
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.3)
                return s.connect_ex(("127.0.0.1", port)) == 0
        except Exception:
            return False

    @staticmethod
    def detect_service_port(svc: ManagedService) -> Optional[int]:
        import re
        if "PORT" in svc.custom_env:
            try:
                return int(svc.custom_env["PORT"])
            except ValueError:
                pass
        m = re.search(r"(?:--port|-p)\s+(\d+)", svc.command)
        if m:
            return int(m.group(1))
        m = re.search(r":(\d{2,5})\b", svc.command)
        if m:
            return int(m.group(1))
        return None

    @staticmethod
    def _build_launch_args(svc: ManagedService):
        """Returns (args, use_shell) for Popen based on the service's shell setting.

        Single-line cmd commands run directly through cmd.exe as before. PowerShell
        commands and multi-line cmd commands are written to a script file so that
        variables, pipes and line continuations behave exactly like in a terminal.
        On Linux/macOS, runs via bash/sh.
        """
        command = svc.command.strip()
        if sys.platform != "win32":
            if svc.shell == "pwsh":
                return ["pwsh", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command], False
            return ["/bin/bash", "-c", command], False

        if svc.shell == "cmd" and "\n" not in command:
            return command, True

        script_dir = os.path.join(tempfile.gettempdir(), "StartupTerminal", "scripts")
        os.makedirs(script_dir, exist_ok=True)
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in svc.id)

        if svc.shell in ("powershell", "pwsh"):
            path = os.path.join(script_dir, f"{safe_id}.ps1")
            # Propagate the last native exit code so crashes are detected as FAILED
            body = command + "\nexit $LASTEXITCODE\n"
            # BOM so Windows PowerShell 5.1 reads the file as UTF-8
            with open(path, "w", encoding="utf-8-sig", newline="\r\n") as f:
                f.write(body)
            exe = "pwsh" if svc.shell == "pwsh" else "powershell"
            return [exe, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", path], False

        path = os.path.join(script_dir, f"{safe_id}.cmd")
        with open(path, "w", encoding="utf-8", newline="\r\n") as f:
            f.write("@echo off\nchcp 65001 >nul\n" + command + "\n")
        return ["cmd.exe", "/d", "/c", path], False

    def _run_process_worker(self, svc: ManagedService):
        """Launches the command under the log relay and waits for it to exit."""
        self._log(svc, f"Starting command: {svc.command}", "system")

        # Double-run check for port
        port = self.detect_service_port(svc)
        svc.detected_port = port
        if port and self.is_port_in_use(port):
            warn_msg = f"[DOUBLE-RUN PREVENTED] Port {port} is already active/listening on this PC! Skipping duplicate start."
            self._log(svc, warn_msg, "stderr")
            svc.state = ServiceState.STOPPED
            self._safe_emit_status(svc.id, svc.state)
            return

        # Prepare environment
        env = os.environ.copy()
        # Ensure Python output is unbuffered
        env["PYTHONUNBUFFERED"] = "1"
        for k, v in svc.custom_env.items():
            env[str(k)] = str(v)

        # Windows: own process group, no console window, and not tied to this app's lifetime
        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW

        try:
            cwd = svc.resolved_cwd
            if not os.path.isdir(cwd):
                cwd = self.base_dir

            launch_args, use_shell = self._build_launch_args(svc)
            spec = json.dumps({"args": launch_args, "shell": use_shell})
            if getattr(sys, "frozen", False):
                # Strip PyInstaller env vars so the frozen relay unpacks cleanly
                runner_env = {
                    k: v for k, v in env.items()
                    if not k.startswith("_PYI_") and not k.startswith("_MEIPASS")
                }
                runner_cmd = [
                    sys.executable, "--service-runner",
                    "--log", str(svc.log_path),
                    "--max-bytes", str(LOG_MAX_BYTES),
                    "--spec", spec,
                ]
            else:
                runner_env = env
                # -I: isolated mode, so service env vars (PYTHONPATH etc.) can't break the relay
                runner_cmd = [
                    sys.executable, "-I", RUNNER_SCRIPT,
                    "--log", str(svc.log_path),
                    "--max-bytes", str(LOG_MAX_BYTES),
                    "--spec", spec,
                ]
            proc = subprocess.Popen(
                runner_cmd,
                cwd=cwd,
                env=runner_env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )
            svc.process = proc
            svc.pid = proc.pid
            svc.started_at = datetime.datetime.now()
            svc.state = ServiceState.RUNNING
            self._safe_emit_status(svc.id, svc.state)

            try:
                create_time = psutil.Process(proc.pid).create_time()
            except psutil.Error:
                create_time = time.time()
            self._write_state_entry(svc.id, {
                "pid": proc.pid,
                "create_time": create_time,
                "started_at": svc.started_at.isoformat(),
                "restart_count": svc.restart_count,
            })
        except Exception as exc:
            svc.state = ServiceState.FAILED
            svc.process = None
            svc.pid = None
            self._log(svc, f"Failed to launch command: {exc}", "stderr")
            self._safe_emit_status(svc.id, svc.state)
            return

        self._watch_process(svc, proc.pid, proc.wait)

    def _watch_process(self, svc: ManagedService, pid: int, wait: Callable[[], Optional[int]]):
        """Blocks until the service's root process exits, then records it and handles auto-restart."""
        try:
            exit_code = wait()
        except Exception:
            exit_code = None
        if exit_code is None:
            exit_code = 1  # unknown exit status: treat as a failure

        if self.detached or svc.pid not in (pid, None):
            # App is restarting (the new instance owns it now) or a newer run replaced this one
            return

        svc.exit_code = exit_code
        svc.stopped_at = datetime.datetime.now()
        svc.process = None
        svc.pid = None
        svc.cpu_percent = 0.0
        svc.memory_mb = 0.0
        svc.vram_mb = 0.0
        self._write_state_entry(svc.id, None)

        if svc.user_stopped or exit_code == 0:
            svc.state = ServiceState.STOPPED
            stop_msg = f"Process stopped cleanly (exit code {exit_code})."
            stream_type = "system"
        else:
            svc.state = ServiceState.FAILED
            stop_msg = f"Process exited unexpectedly with code {exit_code}."
            stream_type = "stderr"

        self._log(svc, stop_msg, stream_type)
        self._safe_emit_status(svc.id, svc.state)

        # Auto restart handling
        if (
            not svc.user_stopped
            and svc.enabled
            and svc.restart_on_failure
            and exit_code != 0
        ):
            svc.restart_count += 1
            restart_sec = max(1, svc.restart_delay_sec)
            msg = f"Auto-restart #{svc.restart_count} scheduled. Restarting in {restart_sec}s..."
            self._log(svc, msg, "system")

            svc.restart_timer = threading.Timer(
                restart_sec, lambda: self.start_service(svc.id)
            )
            svc.restart_timer.daemon = True
            svc.restart_timer.start()

    def _kill_process_tree(self, svc: ManagedService):
        """Terminates process tree on Windows."""
        proc = svc.process
        pid = svc.pid
        target_pid = pid or (proc.pid if proc else None)

        if not target_pid:
            svc.process = None
            svc.pid = None
            svc.state = ServiceState.STOPPED
            self._write_state_entry(svc.id, None)
            self._safe_emit_status(svc.id, svc.state)
            return

        try:
            parent = psutil.Process(target_pid)
            children = parent.children(recursive=True)

            # Terminate children first
            for child in children:
                try:
                    child.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            # Terminate parent
            try:
                parent.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

            # Wait up to 1.0 second for graceful exit
            gone, alive = psutil.wait_procs(children + [parent], timeout=1.0)
            for p in alive:
                try:
                    p.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        except Exception:
            pass

        # Windows taskkill forcefully terminates child processes (e.g. uvicorn reload workers)
        if sys.platform == "win32":
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(target_pid)],
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
                    timeout=1.5,
                )
            except Exception:
                pass

        svc.process = None
        svc.pid = None
        svc.cpu_percent = 0.0
        svc.memory_mb = 0.0
        svc.vram_mb = 0.0
        svc.state = ServiceState.STOPPED
        self._write_state_entry(svc.id, None)
        self._safe_emit_status(svc.id, svc.state)

    def _get_cached_process(self, pid: int) -> psutil.Process:
        proc = self._proc_cache.get(pid)
        if proc is None:
            proc = psutil.Process(pid)
            self._proc_cache[pid] = proc
        return proc

    def _poll_service_stats(self):
        """Periodically polls CPU, RAM, and dedicated GPU VRAM stats for active services."""
        running = [s for s in self.services.values() if s.state == ServiceState.RUNNING and s.pid]
        if not running:
            self._proc_cache.clear()
            return

        vram_by_pid = self._vram_sampler.sample()
        seen_pids = set()

        for svc in running:
            try:
                p = self._get_cached_process(svc.pid)
                seen_pids.add(svc.pid)
                cpu = p.cpu_percent(interval=None)
                mem = p.memory_info().rss / (1024 * 1024)
                vram = vram_by_pid.get(svc.pid, 0.0)

                for child in p.children(recursive=True):
                    try:
                        cp = self._get_cached_process(child.pid)
                        seen_pids.add(child.pid)
                        cpu += cp.cpu_percent(interval=None)
                        mem += cp.memory_info().rss / (1024 * 1024)
                        vram += vram_by_pid.get(child.pid, 0.0)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

                svc.cpu_percent = round(cpu, 1)
                svc.memory_mb = round(mem, 1)
                svc.vram_mb = round(vram, 1)
                self._safe_emit_stats(svc.id, svc.cpu_percent, svc.memory_mb, svc.vram_mb)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                svc.cpu_percent = 0.0
                svc.memory_mb = 0.0
                svc.vram_mb = 0.0

        # Prune exited PIDs from cache
        for dead_pid in [pid for pid in self._proc_cache if pid not in seen_pids]:
            self._proc_cache.pop(dead_pid, None)
