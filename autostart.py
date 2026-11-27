"""Windows Startup / Autorun and Shortcut Manager for Startup Terminal.

Manages:
- Registering and unregistering Startup Terminal in Windows Startup Registry
  (HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run).
- Creating/removing Start Menu & Desktop shortcuts via native COM IShellLinkW.

Always prefers a true console-free GUI launcher on Windows:
- Frozen PyInstaller GUI exe (when running packaged release), or
- pythonw.exe + main.py (never a CUI console shim).
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Optional, Tuple

if sys.platform == "win32":
    import winreg
else:
    winreg = None  # type: ignore

REG_RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
REG_VALUE_NAME = "StartupTerminal"


def get_pythonw_executable() -> Path:
    """Finds pythonw.exe corresponding to current or installed Python."""
    current_exe = Path(sys.executable)
    pythonw = current_exe.with_name("pythonw.exe")
    if pythonw.is_file():
        return pythonw

    found = shutil.which("pythonw")
    if found:
        return Path(found)

    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        for py_ver in ["Python313", "Python312", "Python311", "Python310"]:
            candidate = Path(local_app_data) / "Programs" / "Python" / py_ver / "pythonw.exe"
            if candidate.is_file():
                return candidate

    return current_exe


def get_app_entrypoint() -> Path:
    """Returns absolute path to main.py."""
    return Path(__file__).resolve().parent / "main.py"


def resolve_windows_gui_target() -> Tuple[str, str, str]:
    """Returns (exe_path, base_args, work_dir) for console-free GUI launch on Windows."""
    if getattr(sys, "frozen", False):
        exe = os.path.abspath(sys.executable)
        return exe, "", os.path.dirname(exe)

    main_py = get_app_entrypoint()
    pythonw = str(get_pythonw_executable())
    if main_py.is_file():
        return pythonw, f'"{main_py}"', str(main_py.parent)
    return pythonw, "-m main", str(main_py.parent)


def _resolve_icon_path() -> str:
    base_dir = getattr(sys, "_MEIPASS", str(Path(__file__).resolve().parent))
    ico = os.path.join(base_dir, "assets", "startup_terminal.ico")
    if os.path.isfile(ico):
        return ico
    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable)
    return ico


def get_target_command_string(start_minimized: bool = True) -> str:
    """Constructs the command line string to register in Windows Run key."""
    exe, base_args, _ = resolve_windows_gui_target()
    parts = [f'"{exe}"']
    if base_args:
        parts.append(base_args)
    if start_minimized:
        parts.append("--startup")
    return " ".join(parts)


def is_autostart_registered() -> bool:
    """Checks if Startup Terminal is registered for automatic login startup."""
    if sys.platform != "win32" or winreg is None:
        return os.path.isfile(os.path.expanduser("~/.config/autostart/startup-terminal.desktop"))
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, REG_VALUE_NAME)
            val_low = str(val).lower()
            if getattr(sys, "frozen", False):
                return os.path.abspath(sys.executable).lower() in val_low or "startup-terminal" in val_low or "startupterminal" in val_low
            main_py = str(get_app_entrypoint()).lower()
            return main_py in val_low or bool(val_low.strip())
    except (FileNotFoundError, OSError):
        return False


def get_current_registered_command() -> Optional[str]:
    """Returns current registered command string, or None."""
    if sys.platform != "win32" or winreg is None:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, REG_VALUE_NAME)
            return str(val)
    except (FileNotFoundError, OSError):
        return None


def _resolve_linux_exec(extra_args: str = "") -> str:
    if getattr(sys, "frozen", False):
        cmd = f'"{os.path.abspath(sys.executable)}"'
    else:
        which_bin = shutil.which("startup-terminal")
        cmd = which_bin if which_bin else f'"{sys.executable}" "{get_app_entrypoint()}"'
    return f"{cmd} {extra_args}".strip()


def _linux_desktop_entry(extra_args: str = "", autostart_entry: bool = False) -> str:
    base_dir = getattr(sys, "_MEIPASS", str(Path(__file__).resolve().parent))
    icon = os.path.join(base_dir, "assets", "startup_terminal.png")
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        "Name=Startup Terminal",
        "Comment=PM2-Style Server & Background Job Manager",
        f"Exec={_resolve_linux_exec(extra_args)}",
        f"Icon={icon}",
        "Terminal=false",
        "Categories=Development;System;Utility;",
    ]
    if autostart_entry:
        lines.append("X-GNOME-Autostart-enabled=true")
    return "\n".join(lines) + "\n"


def enable_autostart(start_minimized: bool = True) -> Tuple[bool, str]:
    """Registers Startup Terminal to launch automatically on system login."""
    if sys.platform != "win32" or winreg is None:
        try:
            autostart_dir = os.path.expanduser("~/.config/autostart")
            os.makedirs(autostart_dir, exist_ok=True)
            path = os.path.join(autostart_dir, "startup-terminal.desktop")
            with open(path, "w", encoding="utf-8") as f:
                f.write(_linux_desktop_entry("--startup" if start_minimized else "", autostart_entry=True))
            os.chmod(path, 0o755)
            return True, "Autostart enabled on Linux login."
        except Exception as exc:
            return False, f"Failed to create Linux autostart entry: {exc}"
    cmd = get_target_command_string(start_minimized=start_minimized)
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, REG_RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, REG_VALUE_NAME, 0, winreg.REG_SZ, cmd)
        return True, "Startup Terminal successfully registered in Windows Startup."
    except Exception as exc:
        return False, f"Failed to register in Windows Startup: {exc}"


def disable_autostart() -> Tuple[bool, str]:
    """Removes Startup Terminal from system login startup."""
    if sys.platform != "win32" or winreg is None:
        path = os.path.expanduser("~/.config/autostart/startup-terminal.desktop")
        if os.path.isfile(path):
            try:
                os.remove(path)
            except OSError as exc:
                return False, f"Failed to remove Linux autostart entry: {exc}"
        return True, "Autostart disabled."
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, REG_RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE
        ) as key:
            try:
                winreg.DeleteValue(key, REG_VALUE_NAME)
                return True, "Removed Startup Terminal from Windows Startup."
            except FileNotFoundError:
                return True, "Startup Terminal was not registered in Windows Startup."
    except Exception as exc:
        return False, f"Failed to modify Windows Startup registry: {exc}"


def set_autostart(enable: bool, start_minimized: bool = True) -> Tuple[bool, str]:
    """Convenience helper to set desired autostart state."""
    if enable:
        return enable_autostart(start_minimized=start_minimized)
    return disable_autostart()


def refresh_autostart_if_enabled(start_minimized: bool = True):
    """Re-writes the Run entry if enabled so it always points to the current console-free binary."""
    if is_autostart_registered():
        enable_autostart(start_minimized=start_minimized)


# ------------------------------------------------------------------ Start Menu / Desktop Shortcuts

def get_start_menu_shortcut_path() -> str:
    if sys.platform == "win32":
        programs = os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs")
        return os.path.join(programs, "Startup Terminal.lnk")
    return os.path.expanduser("~/.local/share/applications/startup-terminal.desktop")


def get_desktop_shortcut_path() -> str:
    if sys.platform == "win32":
        desktop = os.path.expandvars(r"%USERPROFILE%\Desktop")
        return os.path.join(desktop, "Startup Terminal.lnk")
    return os.path.expanduser("~/Desktop/startup-terminal.desktop")


def is_start_menu_shortcut_installed() -> bool:
    return os.path.isfile(get_start_menu_shortcut_path())


def remove_start_menu_shortcut(desktop: bool = False) -> bool:
    ok = True
    for p in ([get_start_menu_shortcut_path()] + ([get_desktop_shortcut_path()] if desktop else [])):
        if os.path.isfile(p):
            try:
                os.remove(p)
            except Exception:
                ok = False
    return ok


def install_start_menu_shortcut(desktop: bool = False) -> Tuple[bool, str]:
    """Creates a Start Menu / XDG Applications (and optionally Desktop) shortcut."""
    if sys.platform != "win32":
        try:
            menu_path = get_start_menu_shortcut_path()
            os.makedirs(os.path.dirname(menu_path), exist_ok=True)
            entry = _linux_desktop_entry()
            with open(menu_path, "w", encoding="utf-8") as f:
                f.write(entry)
            os.chmod(menu_path, 0o755)
            if desktop:
                dt_path = get_desktop_shortcut_path()
                if os.path.isdir(os.path.dirname(dt_path)):
                    with open(dt_path, "w", encoding="utf-8") as f:
                        f.write(entry)
                    os.chmod(dt_path, 0o755)
            return True, "Linux application desktop entry created successfully."
        except Exception as exc:
            return False, str(exc)

    import ctypes
    from ctypes import wintypes
    import uuid

    try:
        ole32 = ctypes.windll.ole32
        ole32.CoInitialize(None)

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", ctypes.c_ulong),
                ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        def to_guid(s: str) -> GUID:
            u = uuid.UUID(s)
            g = GUID()
            ctypes.memmove(ctypes.byref(g), u.bytes_le, 16)
            return g

        CLSID_ShellLink = to_guid("{00021401-0000-0000-C000-000000000046}")
        IID_IShellLinkW = to_guid("{000214F9-0000-0000-C000-000000000046}")
        IID_IPersistFile = to_guid("{0000010b-0000-0000-C000-000000000046}")

        pLink = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(
            ctypes.byref(CLSID_ShellLink), None, 1, ctypes.byref(IID_IShellLinkW), ctypes.byref(pLink)
        )
        if hr != 0 or not pLink.value:
            return False, f"CoCreateInstance failed (hr={hex(hr)})"

        vt = ctypes.cast(
            ctypes.cast(pLink, ctypes.POINTER(ctypes.c_void_p)).contents,
            ctypes.POINTER(ctypes.c_void_p),
        )

        QI_proto = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)
        )
        SetPath_proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.LPCWSTR)
        SetArgs_proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.LPCWSTR)
        SetDesc_proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.LPCWSTR)
        SetWorkDir_proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.LPCWSTR)
        SetIcon_proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.LPCWSTR, ctypes.c_int)

        QI = QI_proto(vt[0])
        SetDesc = SetDesc_proto(vt[7])
        SetWorkDir = SetWorkDir_proto(vt[9])
        SetArgs = SetArgs_proto(vt[11])
        SetIcon = SetIcon_proto(vt[17])
        SetPath = SetPath_proto(vt[20])

        target_exe, base_args, work_dir = resolve_windows_gui_target()
        ico_path = _resolve_icon_path()

        SetPath(pLink, target_exe)
        if base_args:
            SetArgs(pLink, base_args)
        SetWorkDir(pLink, work_dir)
        SetDesc(pLink, "Startup Terminal - PM2-Style Server & Job Manager")
        if os.path.isfile(ico_path):
            SetIcon(pLink, ico_path, 0)

        pFile = ctypes.c_void_p()
        hr_qi = QI(pLink, ctypes.byref(IID_IPersistFile), ctypes.byref(pFile))
        if hr_qi != 0 or not pFile.value:
            return False, "QueryInterface IPersistFile failed"

        vt_file = ctypes.cast(
            ctypes.cast(pFile, ctypes.POINTER(ctypes.c_void_p)).contents,
            ctypes.POINTER(ctypes.c_void_p),
        )
        Save_proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.LPCWSTR, wintypes.BOOL)
        Save = Save_proto(vt_file[6])

        targets = [get_start_menu_shortcut_path()]
        if desktop:
            targets.append(get_desktop_shortcut_path())

        for target in targets:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            hr_save = Save(pFile, target, True)
            if hr_save != 0:
                return False, f"Save failed on {target} (hr={hex(hr_save)})"

        return True, "Start Menu shortcut created successfully."
    except Exception as exc:
        return False, str(exc)
