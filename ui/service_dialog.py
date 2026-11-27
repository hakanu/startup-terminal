"""Service Editor Dialog (PM2-style) for Startup Terminal.

Provides a clean, intuitive form to add or edit commands/services without touching YAML.
Supports browsing directories, setting auto-start/auto-restart, and port configuration.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)


class ServiceDialog(QDialog):
    """Dialog to create or edit a server/job service."""

    def __init__(
        self,
        service_data: Optional[Dict[str, Any]] = None,
        default_shell: str = "cmd",
        parent=None,
    ):
        super().__init__(parent)
        self.is_edit_mode = service_data is not None
        self.service_data = service_data or {"shell": default_shell}
        self.setWindowTitle("Edit Service" if self.is_edit_mode else "➕ Add New Service")
        self.resize(680, 600)
        self._setup_ui()
        self._populate_fields()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        header_title = "Edit Managed Service" if self.is_edit_mode else "Add New Server or Job"
        header_desc = "Configure your command, working directory, and restart policies:"
        header = QLabel(f"<b>{header_title}</b><br><span style='color: #94a3b8; font-size: 11px;'>{header_desc}</span>")
        layout.addWidget(header)

        form_layout = QFormLayout()
        form_layout.setSpacing(10)
        form_layout.setLabelAlignment(Qt.AlignRight)

        # 1. Service Name
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. FastAPI Backend, Celery Worker, Vite Frontend")
        form_layout.addRow("Service Name:", self.name_edit)

        # 2. Command
        self.cmd_edit = QPlainTextEdit()
        self.cmd_edit.setPlaceholderText(
            "e.g. python -m uvicorn main:app --port 8000\n\n"
            "Multi-line scripts are supported - pick the matching shell below."
        )
        self.cmd_edit.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.cmd_edit.setStyleSheet("font-family: Consolas, 'Cascadia Mono', monospace; font-size: 12px;")
        self.cmd_edit.setMinimumHeight(140)
        self.cmd_edit.textChanged.connect(self._auto_detect_shell)
        form_layout.addRow("Command:", self.cmd_edit)

        # Shell used to run the command
        self.shell_combo = QComboBox()
        self.shell_combo.addItem("cmd.exe (Command Prompt / .bat syntax)", "cmd")
        self.shell_combo.addItem("Windows PowerShell", "powershell")
        self.shell_combo.addItem("PowerShell 7 (pwsh)", "pwsh")
        self.shell_combo.activated.connect(self._on_shell_chosen)
        self._shell_chosen_manually = False
        form_layout.addRow("Shell:", self.shell_combo)

        # 3. Working Directory with Browse button
        cwd_layout = QHBoxLayout()
        cwd_layout.setSpacing(6)
        self.cwd_edit = QLineEdit()
        self.cwd_edit.setPlaceholderText("Optional (defaults to app directory)")
        self.browse_btn = QPushButton("📁 Browse...")
        self.browse_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.browse_btn.clicked.connect(self._browse_directory)
        cwd_layout.addWidget(self.cwd_edit, 1)
        cwd_layout.addWidget(self.browse_btn)
        form_layout.addRow("Working Dir:", cwd_layout)

        # 4. Enabled + Auto Start Checkboxes
        self.enabled_chk = QCheckBox("Service enabled (uncheck to keep it from ever starting)")
        self.enabled_chk.setChecked(True)
        form_layout.addRow("Enabled:", self.enabled_chk)

        self.auto_start_chk = QCheckBox("Start automatically when app / Windows boots")
        self.auto_start_chk.setChecked(True)
        form_layout.addRow("Autostart:", self.auto_start_chk)

        # 5. Auto Restart on Crash Checkbox & Delay
        restart_layout = QHBoxLayout()
        restart_layout.setSpacing(8)
        self.restart_chk = QCheckBox("Auto-restart if process crashes")
        self.restart_chk.setChecked(True)
        self.restart_delay_spin = QSpinBox()
        self.restart_delay_spin.setRange(1, 120)
        self.restart_delay_spin.setValue(3)
        self.restart_delay_spin.setSuffix(" sec")
        restart_layout.addWidget(self.restart_chk)
        restart_layout.addWidget(QLabel("Delay:"))
        restart_layout.addWidget(self.restart_delay_spin)
        restart_layout.addStretch()
        form_layout.addRow("Crash Policy:", restart_layout)

        # 6. Environment Variables
        self.env_edit = QPlainTextEdit()
        self.env_edit.setPlaceholderText("Optional environment variables (KEY=VALUE per line):\nPORT=8000\nENV=production")
        self.env_edit.setFixedHeight(75)
        form_layout.addRow("Env Variables:", self.env_edit)

        layout.addLayout(form_layout)

        # Error label
        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #ef4444; font-size: 11px;")
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        btn_layout.addStretch()

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.cancel_btn.clicked.connect(self.reject)

        self.save_btn = QPushButton("Save Service")
        self.save_btn.setObjectName("primaryButton")
        self.save_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.save_btn.clicked.connect(self._on_save_clicked)

        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.save_btn)
        layout.addLayout(btn_layout)

    def _populate_fields(self):
        if not self.is_edit_mode:
            idx = self.shell_combo.findData(self.service_data.get("shell", "cmd"))
            if idx >= 0:
                self.shell_combo.setCurrentIndex(idx)
            return

        self.name_edit.setText(self.service_data.get("name", ""))
        self.cmd_edit.setPlainText(self.service_data.get("command", ""))
        idx = self.shell_combo.findData(self.service_data.get("shell", "cmd"))
        self.shell_combo.setCurrentIndex(max(idx, 0))
        self._shell_chosen_manually = True  # respect the saved setting
        self.cwd_edit.setText(self.service_data.get("cwd") or "")
        self.enabled_chk.setChecked(self.service_data.get("enabled", True))
        self.auto_start_chk.setChecked(self.service_data.get("auto_start", True))
        self.restart_chk.setChecked(self.service_data.get("restart_on_failure", True))
        self.restart_delay_spin.setValue(int(self.service_data.get("restart_delay_sec", 3)))

        # Parse env dict into text
        env_dict = self.service_data.get("env") or {}
        if isinstance(env_dict, dict):
            env_lines = [f"{k}={v}" for k, v in env_dict.items()]
            self.env_edit.setPlainText("\n".join(env_lines))

    def _on_shell_chosen(self, _index: int):
        self._shell_chosen_manually = True

    def _auto_detect_shell(self):
        """Switches to PowerShell when pasted text clearly uses PowerShell syntax."""
        if self._shell_chosen_manually or self.shell_combo.currentData() != "cmd":
            return
        text = self.cmd_edit.toPlainText()
        if re.search(r"\$env:|^\s*\$\w+\s*=|`\s*$", text, re.MULTILINE):
            self.shell_combo.setCurrentIndex(self.shell_combo.findData("powershell"))

    def _browse_directory(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Working Directory", self.cwd_edit.text() or os.getcwd())
        if folder:
            self.cwd_edit.setText(folder)

    def _on_save_clicked(self):
        name = self.name_edit.text().strip()
        command = self.cmd_edit.toPlainText().strip()

        if not name:
            self.error_label.setText("Please enter a service name.")
            self.error_label.setVisible(True)
            self.name_edit.setFocus()
            return

        if not command:
            self.error_label.setText("Please enter a command to execute.")
            self.error_label.setVisible(True)
            self.cmd_edit.setFocus()
            return

        # Parse environment variables
        env_dict = {}
        for line in self.env_edit.toPlainText().strip().splitlines():
            line = line.strip()
            if line and "=" in line:
                k, v = line.split("=", 1)
                env_dict[k.strip()] = v.strip()

        cwd_val = self.cwd_edit.text().strip() or None

        # Build payload
        svc_id = self.service_data.get("id") or re.sub(r"[^a-zA-Z0-9_-]", "-", name.lower()).strip("-")
        self.result_data = {
            "id": svc_id,
            "name": name,
            "command": command,
            "shell": self.shell_combo.currentData(),
            "cwd": cwd_val,
            "enabled": self.enabled_chk.isChecked(),
            "auto_start": self.auto_start_chk.isChecked(),
            "restart_on_failure": self.restart_chk.isChecked(),
            "restart_delay_sec": self.restart_delay_spin.value(),
            "env": env_dict,
        }

        self.accept()

    def get_service_data(self) -> Dict[str, Any]:
        return getattr(self, "result_data", {})
