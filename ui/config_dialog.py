"""YAML Configuration Editor Dialog for Startup Terminal.

Provides a built-in YAML editor with syntax validation, external editor launching,
and directory opening in Windows File Explorer.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QFont
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from config_manager import save_config_text


class ConfigDialog(QDialog):
    """In-app dialog to view and edit config.yaml."""

    config_saved = Signal()

    def __init__(self, config_path: Path, parent=None):
        super().__init__(parent)
        self.config_path = config_path
        self.setWindowTitle(f"Edit Configuration - {config_path.name}")
        self.resize(750, 580)
        self._setup_ui()
        self._load_file()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header Info
        header_layout = QHBoxLayout()
        header_layout.setSpacing(10)

        path_label = QLabel(f"File: <b>{self.config_path}</b>")
        path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        path_label.setStyleSheet("color: #94a3b8; font-size: 12px;")
        header_layout.addWidget(path_label, 1)

        # External Editor & Explorer buttons
        self.open_ext_btn = QPushButton("Open in Notepad")
        self.open_ext_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.open_ext_btn.clicked.connect(self._open_in_external_editor)

        self.reveal_btn = QPushButton("Reveal in Explorer")
        self.reveal_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.reveal_btn.clicked.connect(self._reveal_in_explorer)

        header_layout.addWidget(self.open_ext_btn)
        header_layout.addWidget(self.reveal_btn)
        layout.addLayout(header_layout)

        # Text Editor
        self.editor = QPlainTextEdit()
        mono_font = QFont("Cascadia Code", 10)
        mono_font.setStyleHint(QFont.Monospace)
        self.editor.setFont(mono_font)
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.editor.setStyleSheet(
            "QPlainTextEdit {"
            "  background-color: #0b0d13;"
            "  color: #f8fafc;"
            "  border: 1px solid #232838;"
            "  border-radius: 6px;"
            "  padding: 8px;"
            "}"
        )
        layout.addWidget(self.editor, 1)

        # Error notification banner (hidden by default)
        self.error_label = QLabel("")
        self.error_label.setStyleSheet(
            "background-color: #7f1d1d; color: #fee2e2; padding: 6px 10px; border-radius: 6px; font-size: 11px;"
        )
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        # Footer Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        btn_layout.addStretch()

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.cancel_btn.clicked.connect(self.reject)

        self.save_btn = QPushButton("💾 Save & Apply")
        self.save_btn.setObjectName("primaryButton")
        self.save_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.save_btn.clicked.connect(self._on_save_clicked)

        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.save_btn)
        layout.addLayout(btn_layout)

    def _load_file(self):
        try:
            content = self.config_path.read_text(encoding="utf-8")
            self.editor.setPlainText(content)
        except Exception as exc:
            self.error_label.setText(f"Error loading file: {exc}")
            self.error_label.setVisible(True)

    def _on_save_clicked(self):
        content = self.editor.toPlainText()
        ok, err = save_config_text(content, self.config_path)
        if not ok:
            self.error_label.setText(f"Validation Error: {err}")
            self.error_label.setVisible(True)
            return

        self.error_label.setVisible(False)
        self.config_saved.emit()
        self.accept()

    def _open_in_external_editor(self):
        try:
            os.startfile(str(self.config_path))
        except Exception as e:
            self.error_label.setText(f"Failed to open external editor: {e}")
            self.error_label.setVisible(True)

    def _reveal_in_explorer(self):
        try:
            folder = self.config_path.parent
            os.startfile(str(folder))
        except Exception as e:
            self.error_label.setText(f"Failed to open folder: {e}")
            self.error_label.setVisible(True)
