"""GitHub Releases Auto-Updater & CLI Self-Update utilities for Startup Terminal.

Supports:
  1. CLI commands (`--version`, `--update`) with corrupted-uv-venv recovery.
  2. Non-blocking GUI `UpdateManager` that checks GitHub Releases asynchronously,
     verifies SHA256SUMS.txt, and self-updates both standalone Windows GUI builds
     (.exe / .zip) and uv tool / pip installs.
  3. Safe PyInstaller --onefile swap: waits for both Python child (pid) and
     bootloader parent (ppid), performs atomic rename-aside (.exe -> .exe.old),
     and strips inherited _PYI_* / _MEIPASS* env vars before relaunching.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from typing import Optional, Tuple

from version import APP_NAME, APP_SLUG, APP_VERSION, GITHUB_RELEASES_API, GITHUB_RELEASES_URL, GITHUB_SLUG

try:
    from PySide6.QtCore import QObject, Signal
except ImportError:
    class QObject:  # type: ignore
        def __init__(self, parent=None):
            pass

    class _DummySignal:
        def __init__(self):
            self._cbs = []

        def connect(self, cb):
            self._cbs.append(cb)

        def emit(self, *args, **kwargs):
            for cb in list(self._cbs):
                try:
                    cb(*args, **kwargs)
                except Exception:
                    pass

    def Signal(*args, **kwargs):  # type: ignore
        return _DummySignal()


GIT_REPO_URL = f"https://github.com/{GITHUB_SLUG}.git"
UV_GIT_SPEC = f"git+{GIT_REPO_URL}"


def get_version_string() -> str:
    return f"{APP_SLUG} v{APP_VERSION} ({GIT_REPO_URL})"


def _recover_and_reinstall_uv(uv_bin: str, pkg_spec: str, creationflags: int = 0) -> subprocess.CompletedProcess:
    """Attempts clean reinstall if an existing Windows/Linux uv tool venv is corrupted."""
    subprocess.run([uv_bin, "tool", "uninstall", APP_SLUG], capture_output=True, creationflags=creationflags)
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            broken_dir = os.path.join(appdata, "uv", "tools", APP_SLUG)
            if os.path.isdir(broken_dir):
                shutil.rmtree(broken_dir, ignore_errors=True)
    return subprocess.run(
        [uv_bin, "tool", "install", "--reinstall", "--force", pkg_spec],
        capture_output=True,
        text=True,
        creationflags=creationflags,
    )


def run_self_update() -> int:
    """CLI self-update via uv (preferring latest GitHub Release wheel, falling back to git repo)."""
    uv_bin = shutil.which("uv")
    if not uv_bin:
        print("[ERROR] `uv` was not found in PATH. Install uv from https://docs.astral.sh/uv/")
        print(f"        Then run: uv tool install --reinstall --force {UV_GIT_SPEC}")
        return 1

    target_spec = UV_GIT_SPEC
    try:
        rel = fetch_latest_release(timeout=5.0)
        if rel.wheel_asset_url and is_newer_version(rel.version, APP_VERSION):
            target_spec = rel.wheel_asset_url
            print(f"[{APP_NAME}] Found GitHub Release v{rel.version} ({rel.wheel_asset_name})")
    except Exception:
        pass

    print(f"[{APP_NAME}] Updating from {target_spec} via uv...")
    cmd = [uv_bin, "tool", "install", "--upgrade", "--reinstall", "--force", target_spec]
    try:
        proc = subprocess.run(cmd)
        if proc.returncode == 0:
            print(f"[OK] {APP_NAME} successfully updated from {GIT_REPO_URL}!")
            return 0

        print(f"[{APP_NAME}] Attempting clean reinstall of uv tool environment...")
        proc2 = _recover_and_reinstall_uv(uv_bin, target_spec)
        if proc2.returncode == 0:
            print(f"[OK] {APP_NAME} cleanly reinstalled from {GIT_REPO_URL}!")
        elif proc2.stderr:
            print(proc2.stderr)
        return proc2.returncode
    except Exception as exc:
        print(f"[ERROR] Self-update failed: {exc}")
        return 1


@dataclass
class ReleaseInfo:
    version: str
    tag_name: str
    html_url: str
    notes: str = ""
    win_asset_url: str = ""
    win_asset_name: str = ""
    wheel_asset_url: str = ""
    wheel_asset_name: str = ""
    checksums_url: str = ""


def parse_version(ver: str) -> Tuple[int, ...]:
    """Parses 'v1.2.3' or '1.2.3-beta' into a comparable integer tuple."""
    clean = ver.strip().lstrip("vV")
    nums = re.findall(r"\d+", clean)
    return tuple(int(n) for n in nums[:4]) if nums else (0, 0, 0)


def is_newer_version(remote_ver: str, local_ver: str = APP_VERSION) -> bool:
    return parse_version(remote_ver) > parse_version(local_ver)


def get_install_mode() -> str:
    """Returns 'frozen_win', 'uv_tool', or 'python'."""
    if getattr(sys, "frozen", False):
        return "frozen_win" if sys.platform == "win32" else "frozen_other"
    exe_lower = os.path.abspath(sys.executable).lower()
    if "uv" in exe_lower and "tools" in exe_lower:
        return "uv_tool"
    return "python"


def fetch_latest_release(timeout: float = 8.0) -> ReleaseInfo:
    """Fetches latest GitHub Release metadata synchronously."""
    req = urllib.request.Request(
        GITHUB_RELEASES_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{APP_SLUG}/{APP_VERSION}",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    tag = str(data.get("tag_name") or "").strip()
    version = tag.lstrip("vV")
    html_url = str(data.get("html_url") or GITHUB_RELEASES_URL)
    notes = str(data.get("body") or "").strip()

    win_url = ""
    win_name = ""
    whl_url = ""
    whl_name = ""
    sums_url = ""

    for asset in data.get("assets", []):
        name = str(asset.get("name") or "")
        dl = str(asset.get("browser_download_url") or "")
        low = name.lower()
        if low.endswith(".whl"):
            whl_url = dl
            whl_name = name
        elif "sha256" in low or low == "checksums.txt":
            sums_url = dl
        elif ("windows" in low or "win" in low) and (low.endswith(".zip") or low.endswith(".exe")):
            if not win_url or low.endswith(".exe"):
                win_url = dl
                win_name = name
        elif low.endswith(".exe") and not win_url:
            win_url = dl
            win_name = name

    return ReleaseInfo(
        version=version,
        tag_name=tag,
        html_url=html_url,
        notes=notes,
        win_asset_url=win_url,
        win_asset_name=win_name,
        wheel_asset_url=whl_url,
        wheel_asset_name=whl_name,
        checksums_url=sums_url,
    )


def _download_file(url: str, dest_path: str, progress_cb=None, timeout: float = 60.0):
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP_SLUG}/{APP_VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        downloaded = 0
        with open(dest_path, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if progress_cb and total > 0:
                    progress_cb(min(100, int(downloaded * 100 / total)))
    if progress_cb:
        progress_cb(100)


def _verify_sha256(file_path: str, asset_name: str, checksums_url: str) -> bool:
    """Verifies downloaded file against SHA256SUMS.txt if present in release."""
    if not checksums_url:
        return True
    try:
        req = urllib.request.Request(checksums_url, headers={"User-Agent": f"{APP_SLUG}/{APP_VERSION}"})
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            text = resp.read().decode("utf-8", errors="ignore")
        expected = None
        for line in text.splitlines():
            parts = line.strip().split()
            if len(parts) >= 2 and parts[-1].lstrip("*") == asset_name:
                expected = parts[0].lower()
                break
        if not expected:
            return True
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest().lower() == expected
    except Exception:
        return True


class UpdateManager(QObject):
    """Non-blocking background GitHub Releases update checker and installer."""

    update_available = Signal(object)  # ReleaseInfo
    up_to_date = Signal(str)           # current version
    update_error = Signal(str)         # error message
    status_changed = Signal(str)       # human-readable status
    download_progress = Signal(int)    # 0..100
    restart_requested = Signal()       # emitted when app should detach services & exit

    def __init__(self, parent=None):
        super().__init__(parent)
        self._busy = False
        self.latest_release: Optional[ReleaseInfo] = None

    def check_for_updates(self, silent: bool = True, auto_install: bool = False):
        if self._busy:
            return
        self._busy = True
        self.status_changed.emit("Checking GitHub Releases...")

        def _worker():
            try:
                rel = fetch_latest_release()
                self.latest_release = rel
                if rel.version and is_newer_version(rel.version, APP_VERSION):
                    self.status_changed.emit(f"Update available: v{rel.version}")
                    self.update_available.emit(rel)
                    if auto_install:
                        self._busy = False
                        self.install_update(rel)
                        return
                else:
                    self.status_changed.emit(f"Up to date (v{APP_VERSION})")
                    if not silent:
                        self.up_to_date.emit(APP_VERSION)
            except Exception as exc:
                msg = str(exc)
                if "404" in msg:
                    self.status_changed.emit(f"No GitHub releases published yet (v{APP_VERSION})")
                    if not silent:
                        self.up_to_date.emit(APP_VERSION)
                else:
                    self.status_changed.emit("Update check failed")
                    if not silent:
                        self.update_error.emit(f"Could not check for updates: {msg}")
            finally:
                self._busy = False

        threading.Thread(target=_worker, daemon=True, name="UpdaterCheck").start()

    def install_update(self, release: Optional[ReleaseInfo] = None):
        rel = release or self.latest_release
        if not rel or self._busy:
            return
        self._busy = True

        def _installer():
            mode = get_install_mode()
            try:
                if mode == "frozen_win" and rel.win_asset_url:
                    self._install_frozen_windows(rel)
                else:
                    self._install_python_or_uv(rel)
            except Exception as exc:
                self.status_changed.emit("Update failed")
                self.update_error.emit(f"Update failed: {exc}")
            finally:
                self._busy = False

        threading.Thread(target=_installer, daemon=True, name="UpdaterInstall").start()

    def _install_frozen_windows(self, rel: ReleaseInfo):
        tmp_dir = tempfile.mkdtemp(prefix="startup_terminal_upd_")
        dl_path = os.path.join(tmp_dir, rel.win_asset_name)
        self.status_changed.emit(f"Downloading v{rel.version}...")
        _download_file(rel.win_asset_url, dl_path, progress_cb=self.download_progress.emit)

        if not _verify_sha256(dl_path, rel.win_asset_name, rel.checksums_url):
            raise RuntimeError("SHA256 checksum verification failed.")

        new_exe = dl_path
        if dl_path.lower().endswith(".zip"):
            extract_dir = os.path.join(tmp_dir, "extracted")
            with zipfile.ZipFile(dl_path, "r") as zf:
                zf.extractall(extract_dir)
            found_exe = None
            for root, _, files in os.walk(extract_dir):
                for fn in files:
                    if fn.lower().endswith(".exe"):
                        found_exe = os.path.join(root, fn)
                        break
                if found_exe:
                    break
            if not found_exe:
                raise RuntimeError("No executable found inside downloaded release archive.")
            new_exe = found_exe

        current_exe = os.path.abspath(sys.executable)
        current_dir = os.path.dirname(current_exe)
        old_exe = current_exe + ".old"
        pid = os.getpid()
        ppid = os.getppid()
        script_path = os.path.join(tmp_dir, "apply_update.ps1")

        ps_script = f"""
$ErrorActionPreference = 'SilentlyContinue'
foreach ($p in @({pid}, {ppid})) {{
    if ($p -gt 0) {{
        for ($i = 0; $i -lt 60; $i++) {{
            if (-not (Get-Process -Id $p -ErrorAction SilentlyContinue)) {{ break }}
            Start-Sleep -Milliseconds 250
        }}
    }}
}}

for ($attempt = 0; $attempt -lt 30; $attempt++) {{
    try {{
        if (Test-Path -LiteralPath '{old_exe}') {{
            Remove-Item -LiteralPath '{old_exe}' -Force -ErrorAction SilentlyContinue
        }}
        if (Test-Path -LiteralPath '{current_exe}') {{
            Move-Item -LiteralPath '{current_exe}' -Destination '{old_exe}' -Force -ErrorAction Stop
        }}
        Copy-Item -LiteralPath '{new_exe}' -Destination '{current_exe}' -Force -ErrorAction Stop
        break
    }} catch {{
        Start-Sleep -Milliseconds 300
    }}
}}

Get-ChildItem Env: | Where-Object {{ $_.Name -like '_PYI_*' -or $_.Name -like '_MEIPASS*' }} | ForEach-Object {{
    Remove-Item "Env:$($_.Name)" -ErrorAction SilentlyContinue
}}

if (Test-Path -LiteralPath '{current_exe}') {{
    Start-Process -FilePath '{current_exe}' -WorkingDirectory '{current_dir}'
}}
Start-Sleep -Seconds 2
Remove-Item -LiteralPath '{old_exe}' -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath '{tmp_dir}' -Recurse -Force -ErrorAction SilentlyContinue
"""
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(ps_script)

        clean_env = {
            k: v for k, v in os.environ.items()
            if not k.startswith("_PYI_") and not k.startswith("_MEIPASS")
        }
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        creationflags = 0x08000000 | 0x00000008  # CREATE_NO_WINDOW | DETACHED_PROCESS
        subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", script_path],
            creationflags=creationflags,
            startupinfo=si,
            env=clean_env,
            close_fds=True,
        )
        self.status_changed.emit(f"Installing v{rel.version} and restarting...")
        time.sleep(0.3)
        self.restart_requested.emit()

    def _install_python_or_uv(self, rel: ReleaseInfo):
        creationflags = 0x08000000 if sys.platform == "win32" else 0
        target_pkg = rel.wheel_asset_url or f"git+https://github.com/{GITHUB_SLUG}.git@{rel.tag_name}"

        uv_bin = shutil.which("uv")
        mode = get_install_mode()

        self.status_changed.emit(f"Installing v{rel.version}...")
        self.download_progress.emit(25)

        if mode == "uv_tool" and uv_bin:
            cmd = [uv_bin, "tool", "install", "--upgrade", "--reinstall", "--force", target_pkg]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180, creationflags=creationflags)
            if proc.returncode != 0:
                proc = _recover_and_reinstall_uv(uv_bin, target_pkg, creationflags=creationflags)
        else:
            cmd = [sys.executable, "-m", "pip", "install", "--upgrade", target_pkg]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180, creationflags=creationflags)

        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "Installer returned non-zero exit code").strip()
            raise RuntimeError(err[-300:])

        self.download_progress.emit(100)
        self.status_changed.emit(f"Updated to v{rel.version}! Restarting...")

        if sys.platform == "win32":
            from autostart import resolve_windows_gui_target

            exe, base_args, work_dir = resolve_windows_gui_target()
            launch_cmd = [exe] + ([base_args.strip('"')] if base_args and not base_args.startswith("-") else base_args.split())
            subprocess.Popen(
                launch_cmd,
                cwd=work_dir,
                creationflags=0x08000000 | 0x00000008,
                close_fds=True,
            )
        else:
            which_bin = shutil.which(APP_SLUG)
            launch_cmd = [which_bin] if which_bin else [sys.executable, os.path.abspath(sys.argv[0])]
            subprocess.Popen(launch_cmd, start_new_session=True, close_fds=True)

        time.sleep(0.3)
        self.restart_requested.emit()
