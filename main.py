"""Entry point for Startup Terminal.

Launches the PySide6 application with dark mode styling, console-free Windows GUI
support, UI scale settings, shortcut/autostart CLI flags, GitHub Releases
auto-updater, and built-in `--service-runner` mode for frozen PyInstaller builds.
"""

from __future__ import annotations

import argparse
import atexit
import ctypes
import os
import sys
from pathlib import Path

# Fast-path: when running as a frozen PyInstaller executable, ProcessManager spawns
# `startup-terminal.exe --service-runner ...` as the detached log relay.
# Handle it BEFORE importing PySide6 so service relays stay tiny and fast.
if "--service-runner" in sys.argv:
    sys.argv = [sys.argv[0]] + [a for a in sys.argv[1:] if a != "--service-runner"]
    import service_runner
    sys.exit(service_runner.main())

from version import APP_NAME, APP_VERSION, WINDOWS_APP_ID


def detach_unwanted_console():
    """Prevents an empty background terminal window from staying open on Windows GUI launch.

    Preserves stdout/stderr when launched interactively from an existing shell
    (GetConsoleProcessList > 1).
    """
    if sys.platform != "win32":
        return
    try:
        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32
        console_hwnd = kernel32.GetConsoleWindow()
        if console_hwnd:
            pids = (ctypes.c_uint32 * 4)()
            count = kernel32.GetConsoleProcessList(pids, 4)
            if count <= 1:
                user32.ShowWindow(console_hwnd, 0)  # SW_HIDE
                kernel32.FreeConsole()
                devnull = open(os.devnull, "w", encoding="utf-8")
                sys.stdout = devnull
                sys.stderr = devnull
    except Exception:
        pass

    try:
        if sys.stdout is None:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
        if sys.stderr is None:
            sys.stderr = open(os.devnull, "w", encoding="utf-8")
    except Exception:
        pass


def set_windows_app_id():
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_ID)
        except Exception:
            pass


def cleanup_old_updater_binary():
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        old_exe = os.path.abspath(sys.executable) + ".old"
        if os.path.isfile(old_exe):
            try:
                os.remove(old_exe)
            except OSError:
                pass


def parse_args():
    parser = argparse.ArgumentParser(
        prog="startup-terminal",
        description=f"{APP_NAME} v{APP_VERSION} - PM2-Style Server & Job Manager with Realtime Logs",
    )
    parser.add_argument(
        "--config",
        "-c",
        type=str,
        default=None,
        help="Path to YAML configuration file",
    )
    parser.add_argument(
        "--startup",
        action="store_true",
        help="Launched by Windows startup; starts minimized to system tray",
    )
    parser.add_argument(
        "--minimized",
        action="store_true",
        help="Start minimized to system tray",
    )
    parser.add_argument(
        "--version",
        "-v",
        action="store_true",
        help="Show version information and exit",
    )
    parser.add_argument(
        "--update",
        "-u",
        action="store_true",
        help="Self-update Startup Terminal from GitHub Releases / uv",
    )
    parser.add_argument(
        "--install-shortcut",
        action="store_true",
        help="Create Windows Start Menu shortcut and exit",
    )
    parser.add_argument(
        "--desktop",
        action="store_true",
        help="Also create a Desktop shortcut (use with --install-shortcut)",
    )
    parser.add_argument(
        "--remove-shortcut",
        action="store_true",
        help="Remove Start Menu & Desktop shortcuts and exit",
    )
    parser.add_argument(
        "--autostart",
        action="store_true",
        help="Enable automatic launch on Windows login and exit",
    )
    parser.add_argument(
        "--no-autostart",
        action="store_true",
        help="Disable automatic launch on Windows login and exit",
    )
    return parser.parse_args()


def main():
    cleanup_old_updater_binary()
    args = parse_args()

    if args.version:
        from updater import get_version_string
        print(get_version_string())
        sys.exit(0)

    if args.update:
        from updater import run_self_update
        sys.exit(run_self_update())

    if args.install_shortcut:
        import autostart
        ok, msg = autostart.install_start_menu_shortcut(desktop=args.desktop)
        print(("[OK] " if ok else "[ERROR] ") + msg)
        sys.exit(0 if ok else 1)

    if args.remove_shortcut:
        import autostart
        ok = autostart.remove_start_menu_shortcut(desktop=True)
        print("[OK] Shortcuts removed." if ok else "[WARN] Some shortcuts could not be removed.")
        sys.exit(0 if ok else 1)

    if args.autostart:
        import autostart
        from settings_manager import get_settings
        ok, msg = autostart.set_autostart(True, start_minimized=get_settings().data.autostart_minimized)
        print(("[OK] " if ok else "[ERROR] ") + msg)
        sys.exit(0 if ok else 1)

    if args.no_autostart:
        import autostart
        ok, msg = autostart.set_autostart(False)
        print(("[OK] " if ok else "[ERROR] ") + msg)
        sys.exit(0 if ok else 1)

    # GUI Mode: detach unwanted console & set Windows AppUserModelID
    detach_unwanted_console()
    set_windows_app_id()

    # Load saved UI scale BEFORE creating QApplication
    from settings_manager import get_settings
    settings = get_settings()
    scale_pct = int(settings.data.ui_scale_percent or 100)
    if scale_pct != 100 and "QT_SCALE_FACTOR" not in os.environ:
        os.environ["QT_SCALE_FACTOR"] = f"{scale_pct / 100.0:.2f}"

    # Keep autostart registry pointing to current console-free binary if enabled
    import autostart
    autostart.refresh_autostart_if_enabled(start_minimized=settings.data.autostart_minimized)

    from PySide6.QtCore import Qt
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtWidgets import QApplication

    from config_manager import get_resolved_config_path
    from ui.main_window import MainWindow
    from ui.theme import DARK_THEME_QSS

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("StartupTerminal")
    app.setApplicationDisplayName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)

    # Single-instance guard: if already running (e.g. minimized in tray),
    # tell the existing instance to restore & focus its window, then exit cleanly.
    SINGLE_INSTANCE_KEY = "StartupTerminal_SingleInstance_v1"
    probe = QLocalSocket()
    probe.connectToServer(SINGLE_INSTANCE_KEY)
    if probe.waitForConnected(350):
        payload = b"PING" if (args.startup or args.minimized) else b"SHOW"
        probe.write(payload)
        probe.flush()
        probe.waitForBytesWritten(350)
        probe.disconnectFromServer()
        sys.exit(0)

    app.setStyleSheet(DARK_THEME_QSS)

    config_path = Path(args.config) if args.config else get_resolved_config_path()
    start_minimized = args.startup or args.minimized

    window = MainWindow(config_path=config_path, start_minimized=start_minimized)

    # Listen for secondary launches so Start Menu clicks restore the tray window
    QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
    instance_server = QLocalServer(window)
    if instance_server.listen(SINGLE_INSTANCE_KEY):
        window._instance_server = instance_server

        def _on_secondary_launch():
            while instance_server.hasPendingConnections():
                sock = instance_server.nextPendingConnection()
                if sock:
                    sock.waitForReadyRead(200)
                    msg = bytes(sock.readAll()).strip()
                    sock.disconnectFromServer()
                    sock.deleteLater()
                    if msg != b"PING":
                        window._restore_from_tray()

        instance_server.newConnection.connect(_on_secondary_launch)

    app.aboutToQuit.connect(window.close_instance_server)
    app.aboutToQuit.connect(lambda: window.proc_mgr.stop_all(wait=True, timeout=2.5))
    atexit.register(lambda: window.proc_mgr.stop_all(wait=True, timeout=2.5))

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
