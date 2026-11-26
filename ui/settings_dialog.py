"""Tabbed Settings Dialog for Startup Terminal.

Provides a clean GUI for General/Window behavior, Services & Logs defaults,
Windows startup/shortcuts, and GitHub Releases Auto-Updater settings.
"""

from __future__ import annotations

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
from settings_manager import get_settings
from ui.wrap_button import WrapButton
from updater import UpdateManager, get_install_mode
from version import APP_NAME, APP_VERSION, GITHUB_RELEASES_URL


class SettingsDialog(QDialog):
    """Application Settings dialog with General, Services & Logs, and Updates tabs."""

    settings_applied = Signal()

    def __init__(self, update_mgr: Optional[UpdateManager] = None, parent=None):
        super().__init__(parent)
        self.settings = get_settings()
        self.update_mgr = update_mgr
        self._initial_scale = self.settings.data.ui_scale_percent

        self.setWindowTitle(f"⚙ {APP_NAME} Settings")
        self.setMinimumSize(500, 440)
        self.resize(560, 490)
        self._build_ui()
        self._load_values()
        self._wire_updater()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #252b3d; border-radius: 8px; background: #13161f; }"
            "QTabBar::tab { background: #191c26; color: #94a3b8; padding: 8px 14px; "
            "border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 4px; }"
            "QTabBar::tab:selected { background: #232a3d; color: #f8fafc; font-weight: 600; }"
        )
        root.addWidget(self.tabs, 1)

        # ---------------- Tab 1: General ----------------
        gen_tab = QWidget()
        gen_tab.setStyleSheet("background: transparent;")
        gen_form = QFormLayout(gen_tab)
        gen_form.setContentsMargins(16, 16, 16, 16)
        gen_form.setSpacing(12)

        self.chk_autostart = QCheckBox("Launch Startup Terminal automatically on Windows login")
        self.chk_autostart_min = QCheckBox("Start minimized to system tray on Windows boot")
        self.chk_start_min = QCheckBox("Always start minimized to system tray")
        self.chk_close_tray = QCheckBox("Minimize to system tray when clicking the window close (X) button")
        self.chk_remember_geom = QCheckBox("Remember window size, position, and sidebar width")

        self.combo_scale = QComboBox()
        for pct in (75, 85, 90, 100, 110, 125, 150, 175, 200):
            self.combo_scale.addItem(f"{pct}%", pct)

        scale_hint = QLabel("Restart Startup Terminal to apply UI scale changes.")
        scale_hint.setStyleSheet("color: #94a3b8; font-size: 11px;")

        shortcut_row = QHBoxLayout()
        self.btn_install_shortcut = WrapButton("📌 Create Start Menu Shortcut")
        self.btn_install_shortcut.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_install_shortcut.clicked.connect(self._on_install_shortcut)
        self.btn_desktop_shortcut = WrapButton("🖥 Desktop Shortcut")
        self.btn_desktop_shortcut.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_desktop_shortcut.clicked.connect(self._on_install_desktop_shortcut)
        shortcut_row.addWidget(self.btn_install_shortcut)
        shortcut_row.addWidget(self.btn_desktop_shortcut)

        gen_form.addRow(self.chk_autostart)
        gen_form.addRow(self.chk_autostart_min)
        gen_form.addRow(self.chk_start_min)
        gen_form.addRow(self.chk_close_tray)
        gen_form.addRow(self.chk_remember_geom)
        gen_form.addRow("UI Scale:", self.combo_scale)
        gen_form.addRow("", scale_hint)
        gen_form.addRow("Shortcuts:", shortcut_row)

        self.tabs.addTab(gen_tab, "General")

        # ---------------- Tab 2: Services & Logs ----------------
        svc_tab = QWidget()
        svc_tab.setStyleSheet("background: transparent;")
        svc_form = QFormLayout(svc_tab)
        svc_form.setContentsMargins(16, 16, 16, 16)
        svc_form.setSpacing(12)

        self.chk_auto_start_all = QCheckBox("Automatically start all enabled auto-start services on launch")

        self.spin_max_logs = QSpinBox()
        self.spin_max_logs.setRange(500, 100000)
        self.spin_max_logs.setSingleStep(1000)
        self.spin_max_logs.setSuffix(" lines")

        self.spin_log_font = QSpinBox()
        self.spin_log_font.setRange(8, 22)
        self.spin_log_font.setSuffix(" pt")

        self.chk_log_wrap = QCheckBox("Wrap long lines in log viewer")

        svc_form.addRow(self.chk_auto_start_all)
        svc_form.addRow("Max Log Buffer:", self.spin_max_logs)
        svc_form.addRow("Log Font Size:", self.spin_log_font)
        svc_form.addRow(self.chk_log_wrap)

        self.tabs.addTab(svc_tab, "Services & Logs")

        # ---------------- Tab 3: Updates ----------------
        upd_tab = QWidget()
        upd_tab.setStyleSheet("background: transparent;")
        upd_layout = QVBoxLayout(upd_tab)
        upd_layout.setContentsMargins(16, 16, 16, 16)
        upd_layout.setSpacing(12)

        info_box = QFrame()
        info_box.setStyleSheet("background: #191c26; border: 1px solid #252b3d; border-radius: 8px; padding: 10px;")
        info_form = QFormLayout(info_box)
        info_form.setSpacing(6)
        mode_label = {
            "frozen_win": "Standalone Windows GUI (.exe)",
            "uv_tool": "uv tool install",
            "python": "Python source / pip",
        }.get(get_install_mode(), get_install_mode())
        info_form.addRow("Current Version:", QLabel(f"v{APP_VERSION}"))
        info_form.addRow("Install Mode:", QLabel(mode_label))
        repo_lbl = QLabel(f"<a href='{GITHUB_RELEASES_URL}' style='color:#818cf8;'>{GITHUB_RELEASES_URL}</a>")
        repo_lbl.setOpenExternalLinks(True)
        info_form.addRow("Releases:", repo_lbl)
        upd_layout.addWidget(info_box)

        self.chk_auto_check = QCheckBox("Check GitHub Releases for updates automatically on startup")
        self.chk_auto_install = QCheckBox("Download and install updates automatically (services stay running)")
        upd_layout.addWidget(self.chk_auto_check)
        upd_layout.addWidget(self.chk_auto_install)

        self.upd_status_lbl = QLabel("Ready to check for updates.")
        self.upd_status_lbl.setStyleSheet("color: #94a3b8; font-size: 12px;")
        self.upd_status_lbl.setWordWrap(True)
        upd_layout.addWidget(self.upd_status_lbl)

        self.upd_progress = QProgressBar()
        self.upd_progress.setRange(0, 100)
        self.upd_progress.setVisible(False)
        upd_layout.addWidget(self.upd_progress)

        upd_btn_row = QHBoxLayout()
        self.btn_check_now = WrapButton("🔄 Check for Updates Now")
        self.btn_check_now.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_check_now.clicked.connect(self._on_check_now)

        self.btn_install_now = WrapButton("⬇ Install Update")
        self.btn_install_now.setObjectName("primaryButton")
        self.btn_install_now.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_install_now.setVisible(False)
        self.btn_install_now.clicked.connect(self._on_install_now)

        upd_btn_row.addWidget(self.btn_check_now)
        upd_btn_row.addWidget(self.btn_install_now)
        upd_btn_row.addStretch()
        upd_layout.addLayout(upd_btn_row)
        upd_layout.addStretch()

        self.tabs.addTab(upd_tab, "Updates")

        # ---------------- Footer Buttons ----------------
        footer = QHBoxLayout()
        footer.addStretch()
        self.btn_cancel = WrapButton("Cancel")
        self.btn_cancel.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_save = WrapButton("💾 Save Settings")
        self.btn_save.setObjectName("primaryButton")
        self.btn_save.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_save.clicked.connect(self._on_save)

        footer.addWidget(self.btn_cancel)
        footer.addWidget(self.btn_save)
        root.addLayout(footer)

    def _load_values(self):
        d = self.settings.data
        self.chk_autostart.setChecked(autostart.is_autostart_registered())
        self.chk_autostart_min.setChecked(d.autostart_minimized)
        self.chk_start_min.setChecked(d.start_minimized)
        self.chk_close_tray.setChecked(d.close_to_tray)
        self.chk_remember_geom.setChecked(d.remember_window_geometry)

        idx = self.combo_scale.findData(d.ui_scale_percent)
        self.combo_scale.setCurrentIndex(idx if idx >= 0 else self.combo_scale.findData(100))

        self.chk_auto_start_all.setChecked(d.auto_start_all)
        self.spin_max_logs.setValue(max(500, int(d.max_log_lines)))
        self.spin_log_font.setValue(max(8, min(22, int(d.log_font_size))))
        self.chk_log_wrap.setChecked(d.log_word_wrap)

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
            lambda err: self.upd_status_lbl.setText(f"⚠️ {err}")
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
            self.upd_progress.setValue(0)
            self.update_mgr.install_update()

    def _on_install_shortcut(self):
        ok, msg = autostart.install_start_menu_shortcut(desktop=False)
        if ok:
            QMessageBox.information(self, "Shortcut Created", msg)
        else:
            QMessageBox.warning(self, "Shortcut Error", msg)

    def _on_install_desktop_shortcut(self):
        ok, msg = autostart.install_start_menu_shortcut(desktop=True)
        if ok:
            QMessageBox.information(self, "Shortcuts Created", "Start Menu & Desktop shortcuts created.")
        else:
            QMessageBox.warning(self, "Shortcut Error", msg)

    def _on_save(self):
        scale_val = int(self.combo_scale.currentData() or 100)
        autostart_min = self.chk_autostart_min.isChecked()

        # Sync Windows startup registry
        ok, msg = autostart.set_autostart(self.chk_autostart.isChecked(), start_minimized=autostart_min)
        if not ok:
            QMessageBox.warning(self, "Windows Startup Error", msg)

        self.settings.update(
            save=True,
            notify=True,
            autostart_minimized=autostart_min,
            start_minimized=self.chk_start_min.isChecked(),
            close_to_tray=self.chk_close_tray.isChecked(),
            remember_window_geometry=self.chk_remember_geom.isChecked(),
            ui_scale_percent=scale_val,
            auto_start_all=self.chk_auto_start_all.isChecked(),
            max_log_lines=self.spin_max_logs.value(),
            log_font_size=self.spin_log_font.value(),
            log_word_wrap=self.chk_log_wrap.isChecked(),
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
