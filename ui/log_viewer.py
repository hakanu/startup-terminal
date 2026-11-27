"""Terminal Log Viewer widget for Startup Terminal.

Displays real-time logs with precise datetimes, color-coded stdout/stderr/system
streams, search filtering, auto-scrolling, uptime counter, and process metrics.
Uses responsive FlowLayout + WrapButton so controls remain 100% readable even
in narrow windows.
"""

from __future__ import annotations

import datetime
import html
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QFont, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from process_manager import LogEntry, ManagedService, ServiceState
from ui.flow_layout import FlowLayout
from ui.theme import (
    COLOR_FAILED,
    COLOR_RUNNING,
    COLOR_STARTING,
    COLOR_STOPPED,
)
from ui.wrap_button import WrapButton


class LogViewerWidget(QWidget):
    """Real-time log viewer for the active service."""

    start_requested = Signal(str)
    stop_requested = Signal(str)
    restart_requested = Signal(str)
    clear_logs_requested = Signal(str)
    edit_requested = Signal(str)
    delete_requested = Signal(str)
    enable_toggled = Signal(str, bool)  # (service_id, enabled)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_service: Optional[ManagedService] = None
        self.auto_scroll_enabled = True
        self.filter_text = ""
        self.stream_filter = "All"

        self._setup_ui()

        self.uptime_timer = QTimer(self)
        self.uptime_timer.setInterval(1000)
        self.uptime_timer.timeout.connect(self._update_uptime_display)
        self.uptime_timer.start()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 12, 14, 12)
        main_layout.setSpacing(8)

        # 1a. Service Title + Status Badge Row
        title_row = QHBoxLayout()
        title_row.setSpacing(10)

        self.title_label = QLabel("No Service Selected")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.title_label.setStyleSheet("color: #ffffff;")
        self.title_label.setWordWrap(True)
        self.title_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self.status_badge = QLabel("STOPPED")
        self.status_badge.setStyleSheet(
            f"background-color: #232838; color: {COLOR_STOPPED}; font-weight: bold; "
            "padding: 4px 10px; border-radius: 6px; font-size: 11px;"
        )
        self.status_badge.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        title_row.addWidget(self.title_label, 1)
        title_row.addWidget(self.status_badge, 0, Qt.AlignTop)
        main_layout.addLayout(title_row)

        # 1b. Metrics / Uptime Meta Line
        self.meta_label = QLabel("")
        self.meta_label.setStyleSheet("color: #94a3b8; font-size: 12px;")
        self.meta_label.setWordWrap(True)
        main_layout.addWidget(self.meta_label)

        # 1c. Responsive Action Buttons (FlowLayout + WrapButton -> zero clipping)
        actions_container = QWidget()
        actions_container.setStyleSheet("background: transparent;")
        actions_layout = FlowLayout(actions_container, margin=0, h_spacing=6, v_spacing=6)

        self.toggle_run_btn = WrapButton("▶ Start")
        self.toggle_run_btn.setObjectName("startBtn")
        self.toggle_run_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.toggle_run_btn.clicked.connect(self._on_toggle_run_clicked)

        self.restart_btn = WrapButton("🔄 Restart")
        self.restart_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.restart_btn.clicked.connect(self._on_restart_clicked)

        self.enable_btn = WrapButton("⛔ Disable")
        self.enable_btn.setToolTip("Disabled services never start: not manually, on boot, or via auto-restart")
        self.enable_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.enable_btn.clicked.connect(self._on_enable_clicked)

        self.edit_btn = WrapButton("✏ Edit")
        self.edit_btn.setToolTip("Edit service parameters")
        self.edit_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.edit_btn.clicked.connect(self._on_edit_clicked)

        self.delete_btn = WrapButton("🗑 Delete")
        self.delete_btn.setToolTip("Remove service from config")
        self.delete_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.delete_btn.clicked.connect(self._on_delete_clicked)

        self.clear_btn = WrapButton("🧹 Clear Logs")
        self.clear_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.clear_btn.clicked.connect(self._on_clear_clicked)

        for btn in (
            self.toggle_run_btn,
            self.restart_btn,
            self.enable_btn,
            self.edit_btn,
            self.delete_btn,
            self.clear_btn,
        ):
            actions_layout.addWidget(btn)

        main_layout.addWidget(actions_container)

        # 2. Command Details Sub-bar
        self.cmd_bar = QLabel("Command: -")
        self.cmd_bar.setStyleSheet(
            "background-color: #151822; color: #a5b4fc; font-family: 'Cascadia Code', Consolas, monospace; "
            "font-size: 11px; padding: 6px 10px; border-radius: 6px; border: 1px solid #232838;"
        )
        self.cmd_bar.setWordWrap(True)
        self.cmd_bar.setTextInteractionFlags(Qt.TextSelectableByMouse)
        main_layout.addWidget(self.cmd_bar)

        # 3. Search & Log Control Toolbar (wrapping so nothing clips when narrow)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Filter logs (live text search)...")
        self.search_input.textChanged.connect(self._on_search_changed)
        main_layout.addWidget(self.search_input)

        toolbar_container = QWidget()
        toolbar_container.setStyleSheet("background: transparent;")
        toolbar_layout = FlowLayout(toolbar_container, margin=0, h_spacing=8, v_spacing=6)

        self.stream_combo = QComboBox()
        self.stream_combo.addItems(["All Streams", "stdout only", "stderr only", "system only"])
        self.stream_combo.currentTextChanged.connect(self._on_stream_filter_changed)
        toolbar_layout.addWidget(self.stream_combo)

        self.auto_scroll_chk = QCheckBox("Auto-scroll")
        self.auto_scroll_chk.setChecked(True)
        self.auto_scroll_chk.setCursor(QCursor(Qt.PointingHandCursor))
        self.auto_scroll_chk.toggled.connect(self._on_auto_scroll_toggled)
        toolbar_layout.addWidget(self.auto_scroll_chk)

        self.copy_btn = WrapButton("📋 Copy All")
        self.copy_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.copy_btn.clicked.connect(self._on_copy_all_clicked)
        toolbar_layout.addWidget(self.copy_btn)

        self.export_btn = WrapButton("💾 Export")
        self.export_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.export_btn.clicked.connect(self._on_export_clicked)
        toolbar_layout.addWidget(self.export_btn)

        main_layout.addWidget(toolbar_container)

        # 4. Terminal Text Area
        self.terminal = QTextEdit()
        self.terminal.setReadOnly(True)
        self.terminal.setLineWrapMode(QTextEdit.NoWrap)
        mono_font = QFont("Cascadia Code", 10)
        mono_font.setStyleHint(QFont.Monospace)
        self.terminal.setFont(mono_font)
        self.terminal.setStyleSheet(
            "QTextEdit {"
            "  background-color: #0b0d13;"
            "  color: #e2e8f0;"
            "  border: 1px solid #1f2433;"
            "  border-radius: 8px;"
            "  padding: 8px;"
            "}"
        )
        main_layout.addWidget(self.terminal, 1)

    def apply_settings(self, font_size: int = 10, word_wrap: bool = False):
        mono_font = QFont("Cascadia Code", max(8, min(22, int(font_size))))
        mono_font.setStyleHint(QFont.Monospace)
        self.terminal.setFont(mono_font)
        self.terminal.setLineWrapMode(QTextEdit.WidgetWidth if word_wrap else QTextEdit.NoWrap)

    def set_service(self, svc: Optional[ManagedService]):
        """Switches viewer to display the selected service and its log history."""
        self.current_service = svc
        if not svc:
            self.title_label.setText("No Service Selected")
            self.status_badge.setText("N/A")
            self.meta_label.setText("")
            self.cmd_bar.setText("Command: -")
            self.terminal.clear()
            self.toggle_run_btn.setEnabled(False)
            self.restart_btn.setEnabled(False)
            self.enable_btn.setEnabled(False)
            self.clear_btn.setEnabled(False)
            return

        self.enable_btn.setEnabled(True)
        self.clear_btn.setEnabled(True)

        self.title_label.setText(svc.name)
        lines = svc.command.strip().splitlines() or [""]
        cmd_text = lines[0] + (f"  … (+{len(lines) - 1} lines)" if len(lines) > 1 else "")
        self.cmd_bar.setText(f"Command [{svc.shell}]: {cmd_text}  |  CWD: {svc.resolved_cwd}")
        self.cmd_bar.setToolTip(svc.command)
        self.update_status(svc.state, svc.pid)
        self.reload_logs()

    def _repolish_btn(self, btn: WrapButton):
        btn.style().unpolish(btn)
        btn.style().polish(btn)
        btn.update()

    def update_status(self, state: str, pid: Optional[int] = None):
        """Updates header badge and button labels based on service state."""
        svc_enabled = self.current_service.enabled if self.current_service else True
        self.enable_btn.setText("⛔ Disable" if svc_enabled else "✅ Enable")
        self.restart_btn.setEnabled(svc_enabled)
        is_active = state in (ServiceState.RUNNING, ServiceState.STARTING)
        self.toggle_run_btn.setEnabled(svc_enabled or is_active)

        self.status_badge.setText(state)
        if state == ServiceState.RUNNING:
            color = COLOR_RUNNING
            self.status_badge.setStyleSheet(
                f"background-color: #064e3b; color: {color}; font-weight: bold; "
                "padding: 4px 10px; border-radius: 6px; font-size: 11px; border: 1px solid #059669;"
            )
            self.toggle_run_btn.setText("⏹ Stop")
            self.toggle_run_btn.setObjectName("stopBtn")
            self._repolish_btn(self.toggle_run_btn)
        elif state == ServiceState.STARTING:
            color = COLOR_STARTING
            self.status_badge.setStyleSheet(
                f"background-color: #78350f; color: {color}; font-weight: bold; "
                "padding: 4px 10px; border-radius: 6px; font-size: 11px;"
            )
            self.toggle_run_btn.setText("⏹ Stop")
            self.toggle_run_btn.setObjectName("stopBtn")
            self._repolish_btn(self.toggle_run_btn)
        elif state == ServiceState.FAILED:
            color = COLOR_FAILED
            self.status_badge.setStyleSheet(
                f"background-color: #7f1d1d; color: {color}; font-weight: bold; "
                "padding: 4px 10px; border-radius: 6px; font-size: 11px; border: 1px solid #b91c1c;"
            )
            self.toggle_run_btn.setText("▶ Start")
            self.toggle_run_btn.setObjectName("startBtn")
            self._repolish_btn(self.toggle_run_btn)
        else:  # STOPPED
            color = COLOR_STOPPED
            self.status_badge.setStyleSheet(
                f"background-color: #1e2230; color: {color}; font-weight: bold; "
                "padding: 4px 10px; border-radius: 6px; font-size: 11px; border: 1px solid #2d3345;"
            )
            self.toggle_run_btn.setText("▶ Start")
            self.toggle_run_btn.setObjectName("startBtn")
            self._repolish_btn(self.toggle_run_btn)

        self._update_uptime_display()

    def update_metrics(self, cpu_percent: float, memory_mb: float, vram_mb: float = 0.0):
        if not self.current_service or self.current_service.state != ServiceState.RUNNING:
            return
        self._update_uptime_display()

    @staticmethod
    def _fmt_mem(mb: float) -> str:
        return f"{mb / 1024.0:.1f} GB" if mb >= 1024.0 else f"{int(round(mb))} MB"

    def _update_uptime_display(self):
        if not self.current_service:
            self.meta_label.setText("")
            return

        svc = self.current_service
        if svc.state == ServiceState.RUNNING and svc.started_at:
            delta = datetime.datetime.now() - svc.started_at
            total_sec = int(delta.total_seconds())
            hours, rem = divmod(total_sec, 3600)
            mins, secs = divmod(rem, 60)
            uptime_str = f"{hours:02}:{mins:02}:{secs:02}"
            pid_str = f"PID: {svc.pid}" if svc.pid else ""
            restarts_str = f"↺ {svc.restart_count}"
            metrics_str = f"CPU: {svc.cpu_percent}%  RAM: {self._fmt_mem(svc.memory_mb)}"
            if svc.vram_mb >= 1.0:
                metrics_str += f"  VRAM: {self._fmt_mem(svc.vram_mb)}"
            self.meta_label.setText(f"⏱ {uptime_str}  •  {pid_str}  •  {metrics_str}  •  {restarts_str}")
        elif svc.state == ServiceState.FAILED and svc.exit_code is not None:
            self.meta_label.setText(f"Exited with code {svc.exit_code}  •  ↺ {svc.restart_count} restarts")
        else:
            self.meta_label.setText(f"Inactive  •  ↺ {svc.restart_count} restarts")

    def append_log_entry(self, entry: LogEntry):
        if not self._entry_matches_filters(entry):
            return

        formatted_html = self._format_entry_html(entry)
        cursor = self.terminal.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertHtml(formatted_html + "<br>")

        if self.auto_scroll_enabled:
            self.terminal.moveCursor(QTextCursor.End)

    def reload_logs(self):
        self.terminal.clear()
        if not self.current_service:
            return

        matching = [e for e in self.current_service.logs if self._entry_matches_filters(e)]
        if not matching:
            return

        html_blocks = [self._format_entry_html(e) for e in matching]
        full_html = "<br>".join(html_blocks) + "<br>"
        self.terminal.setHtml(full_html)

        if self.auto_scroll_enabled:
            self.terminal.moveCursor(QTextCursor.End)

    def _entry_matches_filters(self, entry: LogEntry) -> bool:
        if self.stream_filter == "stdout only" and entry.stream != "stdout":
            return False
        if self.stream_filter == "stderr only" and entry.stream != "stderr":
            return False
        if self.stream_filter == "system only" and entry.stream != "system":
            return False
        if self.filter_text and self.filter_text not in entry.text.lower():
            return False
        return True

    def _format_entry_html(self, entry: LogEntry) -> str:
        dt_str = entry.timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        dt_color = "#38bdf8"

        if entry.stream == "stderr":
            stream_badge = "<span style='color: #f87171;'>[STDERR]</span>"
            text_color = "#fca5a5"
        elif entry.stream == "system":
            stream_badge = "<span style='color: #c084fc;'>[SYSTEM]</span>"
            text_color = "#cbd5e1"
        else:
            stream_badge = "<span style='color: #64748b;'>[STDOUT]</span>"
            text_color = "#f1f5f9"

        escaped_text = html.escape(entry.text)
        return (
            f"<span style='color: {dt_color}; font-weight: 500;'>[{dt_str}]</span> "
            f"{stream_badge} "
            f"<span style='color: {text_color};'>{escaped_text}</span>"
        )

    def _on_toggle_run_clicked(self):
        if not self.current_service:
            return
        if self.current_service.state in (ServiceState.RUNNING, ServiceState.STARTING):
            self.stop_requested.emit(self.current_service.id)
        else:
            self.start_requested.emit(self.current_service.id)

    def _on_restart_clicked(self):
        if self.current_service:
            self.restart_requested.emit(self.current_service.id)

    def _on_enable_clicked(self):
        if self.current_service:
            self.enable_toggled.emit(self.current_service.id, not self.current_service.enabled)

    def _on_edit_clicked(self):
        if self.current_service:
            self.edit_requested.emit(self.current_service.id)

    def _on_delete_clicked(self):
        if self.current_service:
            self.delete_requested.emit(self.current_service.id)

    def _on_clear_clicked(self):
        if self.current_service:
            self.clear_logs_requested.emit(self.current_service.id)
            self.terminal.clear()

    def _on_search_changed(self, text: str):
        self.filter_text = text.strip().lower()
        self.reload_logs()

    def _on_stream_filter_changed(self, val: str):
        self.stream_filter = val
        self.reload_logs()

    def _on_auto_scroll_toggled(self, checked: bool):
        self.auto_scroll_enabled = checked
        if checked:
            self.terminal.moveCursor(QTextCursor.End)

    def _on_copy_all_clicked(self):
        if not self.current_service:
            return
        lines = [
            f"[{e.timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}] [{e.stream.upper()}] {e.text}"
            for e in self.current_service.logs
        ]
        QApplication.clipboard().setText("\n".join(lines))

    def _on_export_clicked(self):
        if not self.current_service:
            return
        default_name = f"{self.current_service.id}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Log", default_name, "Log Files (*.log *.txt);;All Files (*.*)"
        )
        if file_path:
            lines = [
                f"[{e.timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}] [{e.stream.upper()}] {e.text}\n"
                for e in self.current_service.logs
            ]
            with open(file_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
