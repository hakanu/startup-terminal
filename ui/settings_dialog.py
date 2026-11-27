"""Tabbed Settings Dialog for Startup Terminal.

Provides organized tabs for General, Services & Logs, Notifications, and Updates,
with live OS startup/shortcut integration, folder shortcuts, and GitHub Releases auto-updater.
"""

from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import autostart
from process_manager import get_data_dir
from settings_manager import get_settings
from ui.wrap_button import WrapButton
from updater import UpdateManager, get_install_mode
from version import APP_NAME, APP_VERSION, GITHUB_RELEASES_URL


def _open_folder(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(str(path))
    else:
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen([opener, str(path)], start_new_session=True)


class SettingsDialog(QDialog):
    """Application Settings dialog with General, Services & Logs, Notifications, and Updates tabs."""

    settings_applied = Signal()

    def __init__(
        self,
        update_mgr: Optional[UpdateManager] = None,
        config_path: Optional[Path] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.settings = get_settings()
        self.update_mgr = update_mgr
        self.config_path = config_path
        self._initial_scale = self.settings.data.ui_scale_percent

        self.setWindowTitle(f"{APP_NAME} — Settings")
        self.setMinimumSize(540, 470)
        self.resize(600, 520)
        self._build_ui()
        self._load_values()
        self._wire_updater()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #252b3d; border-radius: 8px; background: #13161f; padding: 6px; }"
            "QTabBar::tab { background: #191c26; color: #94a3b8; border: 1px solid #252b3d; border-bottom: none; "
            "padding: 8px 14px; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 4px; font-weight: 600; }"
            "QTabBar::tab:selected { background: #232a3d; color: #f8fafc; border-color: #4f46e5; }"
        )
        root.addWidget(self.tabs, 1)

        self.tabs.addTab(self._build_general_tab(), "General")
        self.tabs.addTab(self._build_services_logs_tab(), "Services & Logs")
        self.tabs.addTab(self._build_notifications_tab(), "Notifications")
        self.tabs.addTab(self._build_updates_tab(), "Updates")

        # Footer buttons
        footer = QHBoxLayout()
        footer.setSpacing(8)

        self.btn_reset = WrapButton("↺ Reset Defaults")
        self.btn_reset.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_reset.clicked.connect(self._on_reset_defaults)
        footer.addWidget(self.btn_reset)
        footer.addStretch()

        self.btn_cancel = WrapButton("Cancel")
        self.btn_cancel.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_cancel.clicked.connect(self.reject)
        footer.addWidget(self.btn_cancel)

        self.btn_save = WrapButton("💾 Save & Apply")
        self.btn_save.setObjectName("primaryButton")
        self.btn_save.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_save.clicked.connect(self._on_save)
        footer.addWidget(self.btn_save)

        root.addLayout(footer)

    def _build_general_tab(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        form = QFormLayout(w)
        form.setContentsMargins(14, 14, 14, 14)
        form.setSpacing(10)

        self.chk_autostart = QCheckBox("Launch Startup Terminal automatically on system login")
        form.addRow("Startup:", self.chk_autostart)

        self.chk_autostart_min = QCheckBox("Start minimized to system tray on login")
        form.addRow("", self.chk_autostart_min)

        self.chk_start_min = QCheckBox("Always start minimized to system tray")
        form.addRow("", self.chk_start_min)

        self.chk_start_menu = QCheckBox("Install Start Menu / Applications shortcut")
        form.addRow("Shortcut:", self.chk_start_menu)

        shortcut_btns = QHBoxLayout()
        self.btn_desktop_shortcut = WrapButton("🖥 Create Desktop Shortcut")
        self.btn_desktop_shortcut.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_desktop_shortcut.clicked.connect(self._on_install_desktop_shortcut)
        shortcut_btns.addWidget(self.btn_desktop_shortcut)
        shortcut_btns.addStretch()
        form.addRow("", shortcut_btns)

        self.chk_close_tray = QCheckBox("Minimize to system tray when clicking window close (X)")
        form.addRow("Close Button:", self.chk_close_tray)

        self.chk_remember_geom = QCheckBox("Remember window size, position, and sidebar width")
        form.addRow("Window:", self.chk_remember_geom)

        geo_row = QHBoxLayout()
        self.btn_reset_geo = WrapButton("↺ Reset Window Size & Position")
        self.btn_reset_geo.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_reset_geo.clicked.connect(self._on_reset_geometry)
        geo_row.addWidget(self.btn_reset_geo)
        geo_row.addStretch()
        form.addRow("", geo_row)

        self.combo_scale = QComboBox()
        for pct in (75, 85, 90, 100, 110, 125, 150, 175, 200):
            label = f"{pct}% (Default)" if pct == 100 else f"{pct}%"
            self.combo_scale.addItem(label, pct)
        form.addRow("UI Scale:", self.combo_scale)

        scale_hint = QLabel("UI scale changes take effect after restarting Startup Terminal (♻).")
        scale_hint.setStyleSheet("color: #94a3b8; font-size: 11px;")
        form.addRow("", scale_hint)

        return w

    def _build_services_logs_tab(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        form = QFormLayout(w)
        form.setContentsMargins(14, 14, 14, 14)
        form.setSpacing(10)

        self.chk_auto_start_all = QCheckBox("Auto-start all enabled auto-start services on launch")
        form.addRow("Services:", self.chk_auto_start_all)

        self.combo_shell = QComboBox()
        self.combo_shell.addItem("PowerShell (Windows PowerShell)", "powershell")
        self.combo_shell.addItem("CMD (Command Prompt / Bash on Linux)", "cmd")
        self.combo_shell.addItem("PowerShell 7+ (pwsh)", "pwsh")
        form.addRow("Default Shell:", self.combo_shell)

        self.combo_poll = QComboBox()
        for label, ms in (
            ("1.0 s (Fast)", 1000),
            ("2.0 s (Default)", 2000),
            ("3.0 s", 3000),
            ("5.0 s (Low CPU)", 5000),
        ):
            self.combo_poll.addItem(label, ms)
        form.addRow("Metrics Poll:", self.combo_poll)

        self.chk_sidebar_metrics = QCheckBox("Show live RAM, VRAM & CPU usage on sidebar cards")
        form.addRow("Sidebar Stats:", self.chk_sidebar_metrics)

        self.spin_max_logs = QSpinBox()
        self.spin_max_logs.setRange(500, 100000)
        self.spin_max_logs.setSingleStep(1000)
        self.spin_max_logs.setSuffix(" lines")
        form.addRow("Max Log Buffer:", self.spin_max_logs)

        self.spin_log_font = QSpinBox()
        self.spin_log_font.setRange(8, 22)
        self.spin_log_font.setSuffix(" pt")
        form.addRow("Log Font Size:", self.spin_log_font)

        self.chk_log_wrap = QCheckBox("Wrap long lines in terminal log viewer")
        form.addRow("Word Wrap:", self.chk_log_wrap)

        folder_row = QHBoxLayout()
        self.btn_open_logs = WrapButton("📂 Open Logs Folder")
        self.btn_open_logs.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_open_logs.clicked.connect(lambda: _open_folder(get_data_dir() / "logs"))
        folder_row.addWidget(self.btn_open_logs)

        self.btn_open_cfg_dir = WrapButton("📁 Open Config Folder")
        self.btn_open_cfg_dir.setCursor(QCursor(Qt.PointingHandCursor))
        cfg_dir = self.config_path.parent if self.config_path else self.settings.path.parent
        self.btn_open_cfg_dir.clicked.connect(lambda: _open_folder(cfg_dir))
        folder_row.addWidget(self.btn_open_cfg_dir)
        folder_row.addStretch()
        form.addRow("Data Folders:", folder_row)

        return w

    def _build_notifications_tab(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        form = QFormLayout(w)
        form.setContentsMargins(14, 14, 14, 14)
        form.setSpacing(10)

        self.chk_notify_crash = QCheckBox("Show desktop notification when a service exits unexpectedly")
        form.addRow("Crash Alerts:", self.chk_notify_crash)

        self.chk_notify_minimize = QCheckBox("Show tray notification when minimizing to system tray")
        form.addRow("Tray Alerts:", self.chk_notify_minimize)

        hint = QLabel("Crash alerts trigger whenever a running service stops with a non-zero exit code.")
        hint.setStyleSheet("color: #94a3b8; font-size: 11px;")
        hint.setWordWrap(True)
        form.addRow("", hint)

        return w

    def _build_updates_tab(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        mode_label = {
            "frozen_win": "Standalone Windows GUI (.exe)",
            "frozen_linux": "Standalone Linux x64 Binary",
            "uv_tool": "uv tool install",
            "python": "Python source / pip",
        }.get(get_install_mode(), get_install_mode())

        info_box = QFrame()
        info_box.setStyleSheet(
            "QFrame { background: #191c26; border: 1px solid #252b3d; border-radius: 8px; padding: 8px; }"
        )
        il = QVBoxLayout(info_box)
        il.setSpacing(4)
        lbl_ver = QLabel(f"Installed Version: <b>v{APP_VERSION}</b>")
        lbl_ver.setStyleSheet("font-size: 13px; border: none; background: transparent;")
        lbl_mode = QLabel(f"Install Type: {mode_label}")
        lbl_mode.setStyleSheet("color: #94a3b8; font-size: 11px; border: none; background: transparent;")
        il.addWidget(lbl_ver)
        il.addWidget(lbl_mode)
        layout.addWidget(info_box)

        self.chk_auto_check = QCheckBox("Automatically check GitHub Releases on startup")
        self.chk_auto_install = QCheckBox("Automatically download and install updates (services stay running)")
        layout.addWidget(self.chk_auto_check)
        layout.addWidget(self.chk_auto_install)

        self.upd_status_lbl = QLabel("Ready to check for updates.")
        self.upd_status_lbl.setStyleSheet("color: #94a3b8; font-size: 12px;")
        self.upd_status_lbl.setWordWrap(True)
        layout.addWidget(self.upd_status_lbl)

        self.upd_progress = QProgressBar()
        self.upd_progress.setRange(0, 100)
        self.upd_progress.setFixedHeight(8)
        self.upd_progress.setTextVisible(False)
        self.upd_progress.setVisible(False)
        layout.addWidget(self.upd_progress)

        upd_btn_row = QHBoxLayout()
        self.btn_check_now = WrapButton("🔄 Check for Updates Now")
        self.btn_check_now.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_check_now.clicked.connect(self._on_check_now)
        upd_btn_row.addWidget(self.btn_check_now)

        self.btn_install_now = WrapButton("⬇ Install Update")
        self.btn_install_now.setObjectName("primaryButton")
        self.btn_install_now.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_install_now.setVisible(False)
        self.btn_install_now.clicked.connect(self._on_install_now)
        upd_btn_row.addWidget(self.btn_install_now)

        self.btn_open_releases = WrapButton("🌐 GitHub Releases")
        self.btn_open_releases.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_open_releases.clicked.connect(lambda: webbrowser.open(GITHUB_RELEASES_URL))
        upd_btn_row.addWidget(self.btn_open_releases)

        upd_btn_row.addStretch()
        layout.addLayout(upd_btn_row)
        layout.addStretch()

        return w

    def _load_values(self):
        d = self.settings.data
        self.chk_autostart.setChecked(autostart.is_autostart_registered())
        self.chk_autostart_min.setChecked(d.autostart_minimized)
        self.chk_start_min.setChecked(d.start_minimized)
        self.chk_start_menu.setChecked(autostart.is_start_menu_shortcut_installed())
        self.chk_close_tray.setChecked(d.close_to_tray)
        self.chk_remember_geom.setChecked(d.remember_window_geometry)

        idx = self.combo_scale.findData(d.ui_scale_percent)
        self.combo_scale.setCurrentIndex(idx if idx >= 0 else self.combo_scale.findData(100))

        self.chk_auto_start_all.setChecked(d.auto_start_all)
        sh_idx = self.combo_shell.findData(d.default_shell)
        self.combo_shell.setCurrentIndex(sh_idx if sh_idx >= 0 else 0)
        p_idx = self.combo_poll.findData(d.stats_poll_interval_ms)
        self.combo_poll.setCurrentIndex(p_idx if p_idx >= 0 else 1)
        self.chk_sidebar_metrics.setChecked(d.show_sidebar_metrics)
        self.spin_max_logs.setValue(max(500, int(d.max_log_lines)))
        self.spin_log_font.setValue(max(8, min(22, int(d.log_font_size))))
        self.chk_log_wrap.setChecked(d.log_word_wrap)

        self.chk_notify_crash.setChecked(d.notify_on_crash)
        self.chk_notify_minimize.setChecked(d.notify_on_minimize)

        self.chk_auto_check.setChecked(d.auto_check_updates)
        self.chk_auto_install.setChecked(d.auto_install_updates)

    def _wire_updater(self):
        if not self.update_mgr:
            self.btn_check_now.setEnabled(False)
            return
        self.update_mgr.status_changed.connect(self.upd_status_lbl.setText)
        self.update_mgr.download_progress.connect(self._on_download_progress)
        self.update_mgr.update_available.connect(self._on_update_available)
        self.update_mgr.up_to_date.connect(
            lambda v: self.upd_status_lbl.setText(f"✅ You are running the latest version (v{v}).")
        )
        self.update_mgr.update_error.connect(
            lambda err: (self.upd_status_lbl.setText(f"⚠️ {err}"), self.upd_progress.setVisible(False))
        )
        if self.update_mgr.latest_release and self.update_mgr.latest_release.version != APP_VERSION:
            self._on_update_available(self.update_mgr.latest_release)

    def _on_download_progress(self, pct: int):
        self.upd_progress.setVisible(True)
        self.upd_progress.setValue(pct)

    def _on_update_available(self, rel):
        self.btn_install_now.setText(f"⬇ Install v{rel.version}")
        self.btn_install_now.setVisible(True)

    def _on_check_now(self):
        if self.update_mgr:
            self.upd_progress.setVisible(False)
            self.update_mgr.check_for_updates(silent=False, auto_install=False)

    def _on_install_now(self):
        if self.update_mgr:
            self.btn_install_now.setEnabled(False)
            self.upd_progress.setVisible(True)
            self.upd_progress.setValue(5)
            self.update_mgr.install_update()

    def _on_install_desktop_shortcut(self):
        ok, msg = autostart.install_start_menu_shortcut(desktop=True)
        if ok:
            self.chk_start_menu.setChecked(True)
            QMessageBox.information(self, "Shortcuts Created", "Start Menu & Desktop shortcuts created.")
        else:
            QMessageBox.warning(self, "Shortcut Error", msg)

    def _on_reset_geometry(self):
        self.settings.update(
            save=True,
            notify=False,
            window_x=None,
            window_y=None,
            window_width=None,
            window_height=None,
            window_maximized=False,
            splitter_sizes=None,
        )
        QMessageBox.information(self, "Window Geometry Reset", "Saved window size and position have been reset.")

    def _on_reset_defaults(self):
        res = QMessageBox.question(
            self,
            "Reset Settings",
            "Reset all Startup Terminal settings back to their defaults?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if res == QMessageBox.Yes:
            self.settings.reset_defaults(save=True, notify=True)
            self._load_values()

    def _on_save(self):
        scale_val = int(self.combo_scale.currentData() or 100)
        autostart_min = self.chk_autostart_min.isChecked()

        # Sync OS-level login autostart
        ok, msg = autostart.set_autostart(self.chk_autostart.isChecked(), start_minimized=autostart_min)
        if not ok:
            QMessageBox.warning(self, "Startup Error", msg)

        # Sync Start Menu / Applications shortcut
        want_sc = self.chk_start_menu.isChecked()
        has_sc = autostart.is_start_menu_shortcut_installed()
        if want_sc and not has_sc:
            autostart.install_start_menu_shortcut(desktop=False)
        elif not want_sc and has_sc:
            autostart.remove_start_menu_shortcut(desktop=False)

        self.settings.update(
            save=True,
            notify=True,
            autostart_minimized=autostart_min,
            start_minimized=self.chk_start_min.isChecked(),
            close_to_tray=self.chk_close_tray.isChecked(),
            remember_window_geometry=self.chk_remember_geom.isChecked(),
            ui_scale_percent=scale_val,
            auto_start_all=self.chk_auto_start_all.isChecked(),
            default_shell=str(self.combo_shell.currentData() or "powershell"),
            stats_poll_interval_ms=int(self.combo_poll.currentData() or 2000),
            show_sidebar_metrics=self.chk_sidebar_metrics.isChecked(),
            max_log_lines=self.spin_max_logs.value(),
            log_font_size=self.spin_log_font.value(),
            log_word_wrap=self.chk_log_wrap.isChecked(),
            notify_on_crash=self.chk_notify_crash.isChecked(),
            notify_on_minimize=self.chk_notify_minimize.isChecked(),
            auto_check_updates=self.chk_auto_check.isChecked(),
            auto_install_updates=self.chk_auto_install.isChecked(),
        )
        self.settings_applied.emit()

        if scale_val != self._initial_scale:
            QMessageBox.information(
                self,
                "UI Scale Changed",
                f"UI scale set to {scale_val}%. Restart Startup Terminal (♻) to apply the new scale.",
            )
        self.accept()
