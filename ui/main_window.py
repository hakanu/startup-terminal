"""Main Window for Startup Terminal.

Integrates Sidebar, Log Viewer, Process Manager, System Tray, Config Management,
Settings Dialog, Window Geometry Persistence, and GitHub Releases Auto-Updater.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

import autostart
from config_manager import (
    add_service_to_config,
    delete_service_from_config,
    get_resolved_config_path,
    load_config,
    save_config_dict,
    set_service_enabled_in_config,
    update_service_in_config,
)
from process_manager import LogEntry, ProcessManager, ServiceState
from settings_manager import get_settings
from ui.config_dialog import ConfigDialog
from ui.log_viewer import LogViewerWidget
from ui.service_dialog import ServiceDialog
from ui.settings_dialog import SettingsDialog
from ui.sidebar import SidebarWidget
from ui.wrap_button import WrapButton
from updater import ReleaseInfo, UpdateManager
from version import APP_NAME, APP_VERSION


def generate_app_icon() -> QIcon:
    """Loads bundled icon if available, otherwise dynamically renders a crisp terminal icon."""
    base_dir = getattr(sys, "_MEIPASS", str(Path(__file__).resolve().parent.parent))
    ico_path = os.path.join(base_dir, "assets", "startup_terminal.ico")
    if os.path.isfile(ico_path):
        icon = QIcon(ico_path)
        if not icon.isNull():
            return icon

    pix = QPixmap(64, 64)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)

    painter.setBrush(QColor("#1e2230"))
    painter.setPen(QColor("#4f46e5"))
    painter.drawRoundedRect(2, 2, 60, 60, 14, 14)

    font = QFont("Cascadia Code", 22, QFont.Bold)
    painter.setFont(font)
    painter.setPen(QColor("#10b981"))
    painter.drawText(10, 42, ">_")

    painter.end()
    return QIcon(pix)


class MainWindow(QMainWindow):
    """Main application window for Startup Terminal."""

    def __init__(self, config_path: Optional[Path] = None, start_minimized: bool = False):
        super().__init__()
        self.settings = get_settings()
        self.config_path = config_path or get_resolved_config_path()
        self.app_icon = generate_app_icon()
        self.setWindowIcon(self.app_icon)
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setMinimumSize(620, 440)

        # Base directory for resolving relative paths
        base_dir = str(self.config_path.parent)
        self.proc_mgr = ProcessManager(base_dir=base_dir)
        self.update_mgr = UpdateManager(self)

        # Central layout with optional update banner + splitter
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        self._build_update_banner()
        central_layout.addWidget(self.update_banner)

        # UI Components
        self.sidebar = SidebarWidget()
        self.log_viewer = LogViewerWidget()

        # Layout Splitter
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(self.log_viewer)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, False)
        self.splitter.setSizes([290, 760])
        central_layout.addWidget(self.splitter, 1)
        self.setCentralWidget(central)

        # Restore screen-aware geometry
        self._restore_window_geometry()

        # Setup Tray
        self._setup_tray_icon()

        # Connect Signals
        self._connect_signals()

        # Load initial configuration & apply UI settings
        self._load_and_apply_config(initial_boot=True)
        self._apply_ui_settings()

        # Check for GitHub Releases updates asynchronously after startup
        if self.settings.data.auto_check_updates:
            QTimer.singleShot(
                3500,
                lambda: self.update_mgr.check_for_updates(
                    silent=True,
                    auto_install=self.settings.data.auto_install_updates,
                ),
            )

        # Check startup mode
        should_minimize = start_minimized or self.settings.data.start_minimized
        if should_minimize:
            self.hide()
            self.tray_icon.showMessage(
                APP_NAME,
                "Started minimized in system tray.",
                QSystemTrayIcon.Information,
                2500,
            )
        else:
            if self.settings.data.remember_window_geometry and self.settings.data.window_maximized:
                self.showMaximized()
            else:
                self.show()

    def _build_update_banner(self):
        self.update_banner = QFrame()
        self.update_banner.setVisible(False)
        self.update_banner.setStyleSheet(
            "QFrame { background-color: #1e1b4b; border-bottom: 1px solid #4338ca; }"
        )
        row = QHBoxLayout(self.update_banner)
        row.setContentsMargins(14, 8, 14, 8)
        row.setSpacing(10)

        self.update_banner_lbl = QLabel("Update available")
        self.update_banner_lbl.setStyleSheet("color: #e0e7ff; font-weight: 600; background: transparent;")
        self.update_banner_lbl.setWordWrap(True)

        self.btn_banner_install = WrapButton("⬇ Install & Restart")
        self.btn_banner_install.setObjectName("primaryButton")
        self.btn_banner_install.clicked.connect(self._on_banner_install_clicked)

        self.btn_banner_dismiss = WrapButton("✕")
        self.btn_banner_dismiss.clicked.connect(lambda: self.update_banner.setVisible(False))

        row.addWidget(self.update_banner_lbl, 1)
        row.addWidget(self.btn_banner_install)
        row.addWidget(self.btn_banner_dismiss)

    def _restore_window_geometry(self):
        screen = QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        default_w = min(1080, int(avail.width() * 0.78)) if avail else 1080
        default_h = min(700, int(avail.height() * 0.78)) if avail else 700
        default_w = max(620, default_w)
        default_h = max(440, default_h)

        d = self.settings.data
        if d.remember_window_geometry and d.window_width and d.window_height:
            w = max(620, min(int(d.window_width), avail.width() if avail else 3840))
            h = max(440, min(int(d.window_height), avail.height() if avail else 2160))
            self.resize(w, h)
            if d.window_x is not None and d.window_y is not None:
                x, y = int(d.window_x), int(d.window_y)
                if avail:
                    x = max(avail.left(), min(x, avail.right() - 120))
                    y = max(avail.top(), min(y, avail.bottom() - 80))
                self.move(x, y)
            if isinstance(d.splitter_sizes, list) and len(d.splitter_sizes) == 2:
                self.splitter.setSizes([max(220, int(d.splitter_sizes[0])), max(320, int(d.splitter_sizes[1]))])
        else:
            self.resize(default_w, default_h)

    def _save_window_geometry(self):
        if not self.settings.data.remember_window_geometry:
            return
        is_max = self.isMaximized()
        updates = {
            "window_maximized": is_max,
            "splitter_sizes": self.splitter.sizes(),
        }
        if not is_max:
            g = self.geometry()
            updates.update({
                "window_x": g.x(),
                "window_y": g.y(),
                "window_width": g.width(),
                "window_height": g.height(),
            })
        self.settings.update(save=True, notify=False, **updates)

    def _setup_tray_icon(self):
        self.tray_icon = QSystemTrayIcon(self.app_icon, self)
        self.tray_icon.setToolTip(f"{APP_NAME} v{APP_VERSION}")

        tray_menu = QMenu()

        self.action_show = QAction("⚡ Open Startup Terminal", self)
        self.action_show.triggered.connect(self._restore_from_tray)
        tray_menu.addAction(self.action_show)

        tray_menu.addSeparator()

        self.action_tray_start_all = QAction("▶ Start All Services", self)
        self.action_tray_start_all.triggered.connect(self.proc_mgr.start_all)
        tray_menu.addAction(self.action_tray_start_all)

        self.action_tray_stop_all = QAction("⏹ Stop All Services", self)
        self.action_tray_stop_all.triggered.connect(self.proc_mgr.stop_all)
        tray_menu.addAction(self.action_tray_stop_all)

        tray_menu.addSeparator()

        self.action_tray_settings = QAction("⚙ Settings...", self)
        self.action_tray_settings.triggered.connect(self._open_settings_dialog)
        tray_menu.addAction(self.action_tray_settings)

        self.action_tray_updates = QAction("🔄 Check for Updates", self)
        self.action_tray_updates.triggered.connect(
            lambda: self.update_mgr.check_for_updates(silent=False, auto_install=False)
        )
        tray_menu.addAction(self.action_tray_updates)

        tray_menu.addSeparator()

        self.action_restart_app = QAction("♻ Restart Startup Terminal", self)
        self.action_restart_app.triggered.connect(self._restart_app)
        tray_menu.addAction(self.action_restart_app)

        self.action_quit = QAction("🚪 Exit Startup Terminal", self)
        self.action_quit.triggered.connect(self._force_quit)
        tray_menu.addAction(self.action_quit)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _connect_signals(self):
        # Sidebar to LogViewer and ProcessManager
        self.sidebar.service_selected.connect(self._on_service_selected)
        self.sidebar.start_service_requested.connect(self.proc_mgr.start_service)
        self.sidebar.stop_service_requested.connect(self.proc_mgr.stop_service)
        self.sidebar.restart_service_requested.connect(self.proc_mgr.restart_service)
        self.sidebar.start_all_requested.connect(self.proc_mgr.start_all)
        self.sidebar.stop_all_requested.connect(self.proc_mgr.stop_all)
        self.sidebar.add_service_requested.connect(self._open_add_service_dialog)
        self.sidebar.edit_service_requested.connect(self._open_edit_service_dialog)
        self.sidebar.delete_service_requested.connect(self._confirm_delete_service)
        self.sidebar.service_enable_toggled.connect(self._set_service_enabled)
        self.sidebar.open_config_requested.connect(self._open_config_external)
        self.sidebar.edit_config_requested.connect(self._open_config_dialog)
        self.sidebar.reload_config_requested.connect(lambda: self._load_and_apply_config(initial_boot=False))
        self.sidebar.autostart_toggled.connect(self._on_autostart_toggled)
        self.sidebar.restart_app_requested.connect(self._restart_app)
        self.sidebar.settings_requested.connect(self._open_settings_dialog)

        # LogViewer to ProcessManager
        self.log_viewer.start_requested.connect(self.proc_mgr.start_service)
        self.log_viewer.stop_requested.connect(self.proc_mgr.stop_service)
        self.log_viewer.restart_requested.connect(self.proc_mgr.restart_service)
        self.log_viewer.edit_requested.connect(self._open_edit_service_dialog)
        self.log_viewer.delete_requested.connect(self._confirm_delete_service)
        self.log_viewer.enable_toggled.connect(self._set_service_enabled)
        self.log_viewer.clear_logs_requested.connect(self._on_clear_logs)

        # ProcessManager to UI
        self.proc_mgr.status_changed.connect(self._on_proc_status_changed)
        self.proc_mgr.log_received.connect(self._on_proc_log_received)
        self.proc_mgr.stats_updated.connect(self._on_proc_stats_updated)

        # Updater signals
        self.update_mgr.update_available.connect(self._on_update_available)
        self.update_mgr.restart_requested.connect(self._on_updater_restart_requested)

    def _apply_ui_settings(self, sync_yaml: bool = False):
        d = self.settings.data
        self.minimize_to_tray = d.close_to_tray
        self.auto_start_all = d.auto_start_all
        self.log_viewer.apply_settings(font_size=d.log_font_size, word_wrap=d.log_word_wrap)
        self.proc_mgr.set_stats_poll_interval(d.stats_poll_interval_ms)
        self.proc_mgr.set_max_log_lines(d.max_log_lines)
        self.sidebar.set_show_metrics(d.show_sidebar_metrics, self.proc_mgr.services)
        self.sidebar.set_autostart_checked(autostart.is_autostart_registered())

        if sync_yaml and getattr(self, "config_data", None) is not None:
            yaml_settings = self.config_data.setdefault("settings", {})
            yaml_settings["start_with_windows"] = autostart.is_autostart_registered()
            yaml_settings["minimize_to_tray_on_close"] = d.close_to_tray
            yaml_settings["start_minimized"] = d.start_minimized
            yaml_settings["auto_start_all"] = d.auto_start_all
            yaml_settings["max_log_lines"] = d.max_log_lines
            save_config_dict(self.config_data, self.config_path)

    def _load_and_apply_config(self, initial_boot: bool = False):
        try:
            cfg, path = load_config(self.config_path)
            self.config_data = cfg
            self.config_path = path

            yaml_settings = cfg.get("settings", {})
            self.minimize_to_tray = self.settings.data.close_to_tray
            self.auto_start_all = self.settings.data.auto_start_all
            max_logs = max(500, int(self.settings.data.max_log_lines or yaml_settings.get("max_log_lines", 5000)))

            # Sync autostart checkbox with registry & config
            is_registered = autostart.is_autostart_registered()
            config_autostart = yaml_settings.get("start_with_windows", True)

            if initial_boot and config_autostart and not is_registered:
                autostart.enable_autostart(start_minimized=self.settings.data.autostart_minimized)
                is_registered = True

            self.sidebar.set_autostart_checked(is_registered)

            services = cfg.get("services", [])
            self.proc_mgr.update_services_from_config(services, max_logs=max_logs)
            self.sidebar.set_services(self.proc_mgr.services)

            if self.sidebar.selected_svc_id and self.sidebar.selected_svc_id in self.proc_mgr.services:
                self.log_viewer.set_service(self.proc_mgr.services[self.sidebar.selected_svc_id])
            elif self.proc_mgr.services:
                first_id = next(iter(self.proc_mgr.services.keys()))
                self.sidebar.select_service(first_id)

            if initial_boot and self.auto_start_all:
                for svc in self.proc_mgr.services.values():
                    if svc.enabled and svc.auto_start:
                        self.proc_mgr.start_service(svc.id)

        except Exception as exc:
            QMessageBox.critical(self, "Config Error", f"Error loading configuration:\n{exc}")

    def _on_update_available(self, rel: ReleaseInfo):
        self.update_banner_lbl.setText(
            f"⬆ {APP_NAME} v{rel.version} is available (running v{APP_VERSION}). Running services will stay alive during update."
        )
        self.btn_banner_install.setEnabled(True)
        self.update_banner.setVisible(True)

    def _on_banner_install_clicked(self):
        self.btn_banner_install.setEnabled(False)
        self.btn_banner_install.setText("⏳ Downloading...")
        self.update_mgr.install_update()

    def _on_updater_restart_requested(self):
        """Detaches all running services so they stay alive while the updater swaps & relaunches the app."""
        self._save_window_geometry()
        self.close_instance_server()
        self.tray_icon.hide()
        self.proc_mgr.detach_all()
        QApplication.quit()

    def _open_settings_dialog(self):
        dlg = SettingsDialog(update_mgr=self.update_mgr, config_path=self.config_path, parent=self)
        dlg.settings_applied.connect(lambda: self._apply_ui_settings(sync_yaml=True))
        dlg.exec()

    def _on_service_selected(self, svc_id: str):
        svc = self.proc_mgr.services.get(svc_id)
        self.log_viewer.set_service(svc)

    def _on_clear_logs(self, svc_id: str):
        svc = self.proc_mgr.services.get(svc_id)
        if svc:
            svc.clear_logs()

    def _on_proc_status_changed(self, svc_id: str, state: str):
        svc = self.proc_mgr.services.get(svc_id)
        pid = svc.pid if svc else None
        self.sidebar.update_service_state(svc_id, state, pid)
        self.sidebar.update_summary(self.proc_mgr.services)

        if self.sidebar.selected_svc_id == svc_id and svc:
            self.log_viewer.update_status(state, pid)

        if state == ServiceState.FAILED and svc and self.settings.data.notify_on_crash:
            code = f" (exit code {svc.exit_code})" if svc.exit_code is not None else ""
            self.tray_icon.showMessage(
                f"{APP_NAME} — Service Crashed",
                f"'{svc.name}' stopped unexpectedly{code}.",
                QSystemTrayIcon.Warning,
                3500,
            )

    def _on_proc_log_received(self, svc_id: str, timestamp, text: str, stream: str):
        if self.sidebar.selected_svc_id == svc_id:
            self.log_viewer.append_log_entry(LogEntry(timestamp=timestamp, text=text, stream=stream))

    def _on_proc_stats_updated(self, svc_id: str, cpu: float, mem: float, vram: float):
        self.sidebar.update_service_metrics(svc_id, cpu, mem, vram)
        self.sidebar.update_summary(self.proc_mgr.services)
        if self.sidebar.selected_svc_id == svc_id:
            self.log_viewer.update_metrics(cpu, mem, vram)

    def _on_autostart_toggled(self, checked: bool):
        ok, msg = autostart.set_autostart(checked, start_minimized=self.settings.data.autostart_minimized)
        if not ok:
            QMessageBox.warning(self, "Windows Startup Error", msg)
            self.sidebar.set_autostart_checked(not checked)
        else:
            status_text = "enabled" if checked else "disabled"
            self.tray_icon.showMessage(
                "Windows Startup",
                f"Startup Terminal launch on Windows boot is now {status_text}.",
                QSystemTrayIcon.Information,
                2000,
            )

    def _open_config_external(self):
        try:
            if sys.platform == "win32":
                os.startfile(str(self.config_path))
            else:
                opener = "open" if sys.platform == "darwin" else "xdg-open"
                subprocess.Popen([opener, str(self.config_path)], start_new_session=True)
        except Exception as exc:
            QMessageBox.warning(self, "Error", f"Failed to open config file: {exc}")

    def _open_config_dialog(self):
        dialog = ConfigDialog(self.config_path, self)
        dialog.config_saved.connect(lambda: self._load_and_apply_config(initial_boot=False))
        dialog.exec()

    def _open_add_service_dialog(self):
        dialog = ServiceDialog(default_shell=self.settings.data.default_shell, parent=self)
        if dialog.exec():
            svc_data = dialog.get_service_data()
            ok, err = add_service_to_config(svc_data, self.config_path)
            if not ok:
                QMessageBox.critical(self, "Error", f"Failed to add service: {err}")
                return
            self._load_and_apply_config(initial_boot=False)
            if svc_data.get("enabled", True) and svc_data.get("auto_start", True):
                self.proc_mgr.start_service(svc_data["id"])
            self.sidebar.select_service(svc_data["id"])

    def _open_edit_service_dialog(self, svc_id: str):
        svc_dict = None
        for s in self.config_data.get("services", []):
            if s.get("id") == svc_id:
                svc_dict = dict(s)
                break

        if not svc_dict:
            QMessageBox.warning(self, "Error", f"Service '{svc_id}' not found in configuration.")
            return

        dialog = ServiceDialog(service_data=svc_dict, parent=self)
        if dialog.exec():
            updated_data = dialog.get_service_data()
            ok, err = update_service_in_config(svc_id, updated_data, self.config_path)
            if not ok:
                QMessageBox.critical(self, "Error", f"Failed to update service: {err}")
                return
            self._load_and_apply_config(initial_boot=False)
            self.sidebar.select_service(svc_id)

    def _set_service_enabled(self, svc_id: str, enabled: bool):
        ok, err = set_service_enabled_in_config(svc_id, enabled, self.config_path)
        if not ok:
            QMessageBox.critical(self, "Error", f"Failed to update service: {err}")
            return
        self._load_and_apply_config(initial_boot=False)
        self.proc_mgr.log_system(svc_id, f"Service {'enabled' if enabled else 'disabled'}.")
        self.sidebar.select_service(svc_id)

    def _confirm_delete_service(self, svc_id: str):
        svc = self.proc_mgr.services.get(svc_id)
        svc_name = svc.name if svc else svc_id
        res = QMessageBox.question(
            self,
            "Delete Service",
            f"Are you sure you want to delete '{svc_name}'?\nThis will stop the process and remove it from config.yaml.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if res == QMessageBox.Yes:
            self.proc_mgr.stop_service(svc_id)
            ok, err = delete_service_from_config(svc_id, self.config_path)
            if not ok:
                QMessageBox.critical(self, "Error", f"Failed to delete service: {err}")
                return
            self._load_and_apply_config(initial_boot=False)

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._toggle_visibility()

    def _toggle_visibility(self):
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self._restore_from_tray()

    def _restore_from_tray(self):
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def close_instance_server(self):
        srv = getattr(self, "_instance_server", None)
        if srv is not None:
            try:
                srv.close()
            except Exception:
                pass
            self._instance_server = None

    def _force_quit(self):
        """Stops all processes synchronously and exits cleanly."""
        self._save_window_geometry()
        self.tray_icon.hide()
        self.proc_mgr.stop_all(wait=True, timeout=2.5)
        QApplication.quit()

    def _restart_app(self):
        """Launches a fresh app process and exits, leaving managed services running."""
        self._save_window_geometry()
        self.close_instance_server()
        self.tray_icon.hide()
        self.proc_mgr.detach_all()

        args = [a for a in sys.argv[1:] if a not in ("--startup", "--minimized")]
        flags = 0
        if sys.platform == "win32":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP

        clean_env = {
            k: v for k, v in os.environ.items()
            if not k.startswith("_PYI_") and not k.startswith("_MEIPASS")
        }

        try:
            if getattr(sys, "frozen", False):
                cmd = [sys.executable, *args]
                cwd = os.path.dirname(os.path.abspath(sys.executable))
            else:
                main_script = Path(__file__).resolve().parent.parent / "main.py"
                exe, _, _ = autostart.resolve_windows_gui_target()
                cmd = [exe, str(main_script), *args]
                cwd = str(main_script.parent)

            subprocess.Popen(
                cmd,
                cwd=cwd,
                env=clean_env,
                creationflags=flags,
                close_fds=True,
            )
        except Exception as exc:
            self.proc_mgr.reattach_all()
            self.tray_icon.show()
            QMessageBox.critical(self, "Restart Failed", f"Could not relaunch {APP_NAME}:\n{exc}")
            return

        QApplication.quit()

    def closeEvent(self, event):
        """Intercepts window close to minimize to tray if configured."""
        self._save_window_geometry()
        if getattr(self, "minimize_to_tray", True):
            event.ignore()
            self.hide()
            if self.settings.data.notify_on_minimize:
                self.tray_icon.showMessage(
                    APP_NAME,
                    "App is running in the background. Click the tray icon to restore.",
                    QSystemTrayIcon.Information,
                    2000,
                )
        else:
            self._force_quit()
            event.accept()
