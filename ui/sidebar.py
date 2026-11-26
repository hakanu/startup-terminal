"""Sidebar widget for Startup Terminal.

Displays the list of managed commands/services, their live status,
quick start/stop controls, global start/stop all, config actions, and Settings.
Uses FlowLayout + WrapButton so buttons remain fully readable even when narrow.
"""

from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from process_manager import ManagedService, ServiceState
from ui.flow_layout import FlowLayout
from ui.theme import (
    COLOR_ACCENT,
    COLOR_FAILED,
    COLOR_RUNNING,
    COLOR_STARTING,
    COLOR_STOPPED,
)
from ui.wrap_button import WrapButton
from version import APP_VERSION


class ServiceCard(QFrame):
    """Clickable card representing a service in the sidebar."""

    clicked = Signal(str)  # service_id
    start_requested = Signal(str)
    stop_requested = Signal(str)
    restart_requested = Signal(str)
    edit_requested = Signal(str)
    delete_requested = Signal(str)
    enable_toggled = Signal(str, bool)  # (service_id, enabled)

    def __init__(self, svc: ManagedService, parent=None):
        super().__init__(parent)
        self.svc_id = svc.id
        self.enabled = svc.enabled
        self.is_selected = False
        self.current_state = svc.state
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._setup_ui(svc)

    def _setup_ui(self, svc: ManagedService):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(12, 10, 12, 10)
        self.layout.setSpacing(4)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        self.dot = QLabel("●")
        dot_font = QFont()
        dot_font.setPointSize(12)
        self.dot.setFont(dot_font)

        self.name_label = QLabel(svc.name)
        name_font = QFont()
        name_font.setPointSize(10)
        name_font.setBold(True)
        self.name_label.setFont(name_font)
        self.name_label.setWordWrap(True)
        self.name_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self.mini_action_btn = QPushButton("▶")
        self.mini_action_btn.setFixedSize(26, 26)
        self.mini_action_btn.setToolTip("Start / Stop service")
        self.mini_action_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.mini_action_btn.clicked.connect(self._on_mini_action_clicked)

        top_row.addWidget(self.dot, 0, Qt.AlignTop)
        top_row.addWidget(self.name_label, 1)
        top_row.addWidget(self.mini_action_btn, 0, Qt.AlignTop)
        self.layout.addLayout(top_row)

        bot_row = QHBoxLayout()
        bot_row.setSpacing(8)

        self.status_label = QLabel(svc.state)
        self.status_label.setStyleSheet("font-size: 11px; font-weight: 600;")

        first_line = svc.command.strip().splitlines()[0] if svc.command.strip() else ""
        self.info_label = QLabel(f"cmd: {first_line[:24]}..." if len(first_line) > 24 else first_line)
        self.info_label.setStyleSheet("font-size: 11px; color: #7e8b9b;")
        self.info_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        bot_row.addWidget(self.status_label)
        bot_row.addWidget(self.info_label)
        self.layout.addLayout(bot_row)

        self.update_state(svc.state, svc.pid)
        self._update_style()

    def update_state(self, state: str, pid: Optional[int] = None):
        self.current_state = state
        self.status_label.setText(state)

        if not self.enabled and state in (ServiceState.STOPPED, ServiceState.FAILED):
            self.dot.setStyleSheet(f"color: {COLOR_STOPPED};")
            self.status_label.setText("DISABLED")
            self.status_label.setStyleSheet(f"font-size: 11px; font-weight: 600; color: {COLOR_STOPPED};")
            self.name_label.setStyleSheet("color: #64748b;")
            self.mini_action_btn.setText("⛔")
            self.mini_action_btn.setToolTip("Service is disabled (right-click → Enable)")
            self.mini_action_btn.setEnabled(False)
            self.mini_action_btn.setStyleSheet(
                "QPushButton { background: #1e2230; color: #64748b; border: none; border-radius: 4px; padding: 0; }"
            )
            self.info_label.setText("Disabled")
            self._update_style()
            return

        self.name_label.setStyleSheet("")
        self.mini_action_btn.setToolTip("Start / Stop service")
        self.mini_action_btn.setEnabled(True)

        if state == ServiceState.RUNNING:
            color = COLOR_RUNNING
            self.dot.setStyleSheet(f"color: {color};")
            self.status_label.setStyleSheet(f"font-size: 11px; font-weight: 600; color: {color};")
            self.mini_action_btn.setText("⏹")
            self.mini_action_btn.setStyleSheet(
                "QPushButton { background: #7f1d1d; color: white; border: none; border-radius: 4px; padding: 0; }"
                "QPushButton:hover { background: #991b1b; }"
            )
            if pid:
                self.info_label.setText(f"PID: {pid}")
        elif state == ServiceState.STARTING:
            color = COLOR_STARTING
            self.dot.setStyleSheet(f"color: {color};")
            self.status_label.setStyleSheet(f"font-size: 11px; font-weight: 600; color: {color};")
            self.mini_action_btn.setText("⏳")
            self.mini_action_btn.setStyleSheet(
                "QPushButton { background: #78350f; color: white; border: none; border-radius: 4px; padding: 0; }"
            )
        elif state == ServiceState.FAILED:
            color = COLOR_FAILED
            self.dot.setStyleSheet(f"color: {color};")
            self.status_label.setStyleSheet(f"font-size: 11px; font-weight: 600; color: {color};")
            self.mini_action_btn.setText("▶")
            self.mini_action_btn.setStyleSheet(
                "QPushButton { background: #065f46; color: white; border: none; border-radius: 4px; padding: 0; }"
                "QPushButton:hover { background: #047857; }"
            )
        else:
            color = COLOR_STOPPED
            self.dot.setStyleSheet(f"color: {color};")
            self.status_label.setStyleSheet(f"font-size: 11px; font-weight: 600; color: {color};")
            self.mini_action_btn.setText("▶")
            self.mini_action_btn.setStyleSheet(
                "QPushButton { background: #065f46; color: white; border: none; border-radius: 4px; padding: 0; }"
                "QPushButton:hover { background: #047857; }"
            )
            self.info_label.setText("Stopped")

        self._update_style()

    def set_selected(self, selected: bool):
        self.is_selected = selected
        self._update_style()

    def _update_style(self):
        bg = "#232a3d" if self.is_selected else "#191c26"
        border_left = f"3px solid {COLOR_ACCENT}" if self.is_selected else "3px solid transparent"
        border_other = "#333c54" if self.is_selected else "#252b3d"

        self.setStyleSheet(f"""
            QFrame {{
                background-color: {bg};
                border: 1px solid {border_other};
                border-left: {border_left};
                border-radius: 8px;
            }}
            QFrame:hover {{
                background-color: {"#282f45" if self.is_selected else "#1f2433"};
                border-color: #404b69;
            }}
        """)

    def _on_mini_action_clicked(self):
        if self.current_state in (ServiceState.RUNNING, ServiceState.STARTING):
            self.stop_requested.emit(self.svc_id)
        else:
            self.start_requested.emit(self.svc_id)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.svc_id)
        super().mousePressEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        if self.current_state in (ServiceState.RUNNING, ServiceState.STARTING):
            stop_act = menu.addAction("⏹ Stop")
            stop_act.triggered.connect(lambda: self.stop_requested.emit(self.svc_id))
        else:
            start_act = menu.addAction("▶ Start")
            start_act.setEnabled(self.enabled)
            start_act.triggered.connect(lambda: self.start_requested.emit(self.svc_id))

        restart_act = menu.addAction("🔄 Restart")
        restart_act.setEnabled(self.enabled)
        restart_act.triggered.connect(lambda: self.restart_requested.emit(self.svc_id))

        menu.addSeparator()
        toggle_act = menu.addAction("⛔ Disable Service" if self.enabled else "✅ Enable Service")
        toggle_act.triggered.connect(lambda: self.enable_toggled.emit(self.svc_id, not self.enabled))

        menu.addSeparator()
        edit_act = menu.addAction("✏ Edit Service")
        edit_act.triggered.connect(lambda: self.edit_requested.emit(self.svc_id))

        del_act = menu.addAction("🗑 Delete Service")
        del_act.triggered.connect(lambda: self.delete_requested.emit(self.svc_id))

        menu.exec(event.globalPos())


class SidebarWidget(QWidget):
    """Main Sidebar holding service list and controls."""

    service_selected = Signal(str)
    start_service_requested = Signal(str)
    stop_service_requested = Signal(str)
    restart_service_requested = Signal(str)
    start_all_requested = Signal()
    stop_all_requested = Signal()
    add_service_requested = Signal()
    edit_service_requested = Signal(str)
    delete_service_requested = Signal(str)
    service_enable_toggled = Signal(str, bool)
    reload_config_requested = Signal()
    open_config_requested = Signal()
    edit_config_requested = Signal()
    autostart_toggled = Signal(bool)
    restart_app_requested = Signal()
    settings_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cards: Dict[str, ServiceCard] = {}
        self.selected_svc_id: Optional[str] = None
        self._setup_ui()

    def _setup_ui(self):
        self.setMinimumWidth(220)
        self.setMaximumWidth(380)
        self.setStyleSheet("background-color: #13161f; border-right: 1px solid #232736;")

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 12, 10, 10)
        main_layout.setSpacing(8)

        # Header Title + Version Badge
        header_layout = QHBoxLayout()
        header_layout.setSpacing(6)

        logo_label = QLabel("⚡")
        logo_label.setStyleSheet("font-size: 18px; border: none;")
        title_label = QLabel("Startup Terminal")
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #f8fafc; border: none;")

        ver_label = QLabel(f"v{APP_VERSION}")
        ver_label.setStyleSheet(
            "color: #818cf8; background-color: #1e2230; border: 1px solid #2d3345; "
            "border-radius: 4px; padding: 1px 6px; font-size: 10px; font-weight: 600;"
        )

        header_layout.addWidget(logo_label)
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addWidget(ver_label)
        main_layout.addLayout(header_layout)

        # Active Summary Bar
        self.summary_label = QLabel("0 active • 0 stopped")
        self.summary_label.setStyleSheet("color: #94a3b8; font-size: 11px; padding-left: 2px; border: none;")
        main_layout.addWidget(self.summary_label)

        # Prominent Add New Service Button
        self.add_svc_btn = WrapButton("➕ Add New Service")
        self.add_svc_btn.setObjectName("primaryButton")
        self.add_svc_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.add_svc_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.add_svc_btn.clicked.connect(self.add_service_requested.emit)
        main_layout.addWidget(self.add_svc_btn)

        # Master Start All / Stop All Action Row (wrapping so text never clips)
        master_box = QWidget()
        master_box.setStyleSheet("background: transparent; border: none;")
        master_flow = FlowLayout(master_box, margin=0, h_spacing=6, v_spacing=6)

        self.start_all_btn = WrapButton("▶ Start All")
        self.start_all_btn.setObjectName("startBtn")
        self.start_all_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.start_all_btn.clicked.connect(self.start_all_requested.emit)

        self.stop_all_btn = WrapButton("⏹ Stop All")
        self.stop_all_btn.setObjectName("stopBtn")
        self.stop_all_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.stop_all_btn.clicked.connect(self.stop_all_requested.emit)

        master_flow.addWidget(self.start_all_btn)
        master_flow.addWidget(self.stop_all_btn)
        main_layout.addWidget(master_box)

        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setStyleSheet("color: #232736;")
        main_layout.addWidget(div)

        # Services Scroll Area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background: transparent; border: none;")

        self.cards_container = QWidget()
        self.cards_container.setStyleSheet("background: transparent; border: none;")
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(0, 0, 4, 0)
        self.cards_layout.setSpacing(8)
        self.cards_layout.addStretch()

        scroll.setWidget(self.cards_container)
        main_layout.addWidget(scroll, 1)

        # Footer Area
        footer_frame = QFrame()
        footer_frame.setStyleSheet(
            "QFrame { background-color: #171b26; border-radius: 8px; border: 1px solid #252b3d; }"
        )
        footer_layout = QVBoxLayout(footer_frame)
        footer_layout.setContentsMargins(8, 8, 8, 8)
        footer_layout.setSpacing(8)

        # Windows Startup Toggle Checkbox
        self.autostart_chk = QCheckBox("Start with Windows")
        self.autostart_chk.setStyleSheet("background: transparent; border: none;")
        self.autostart_chk.setCursor(QCursor(Qt.PointingHandCursor))
        self.autostart_chk.toggled.connect(self.autostart_toggled.emit)
        footer_layout.addWidget(self.autostart_chk)

        # Wrapping Config & App Action Buttons
        cfg_box = QWidget()
        cfg_box.setStyleSheet("background: transparent; border: none;")
        cfg_flow = FlowLayout(cfg_box, margin=0, h_spacing=6, v_spacing=6)

        self.settings_btn = WrapButton("⚙ Settings")
        self.settings_btn.setToolTip("Open application settings, UI scale & auto-updates")
        self.settings_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.settings_btn.clicked.connect(self.settings_requested.emit)

        self.edit_cfg_btn = WrapButton("📝 YAML")
        self.edit_cfg_btn.setToolTip("Edit configuration in built-in YAML editor")
        self.edit_cfg_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.edit_cfg_btn.clicked.connect(self.edit_config_requested.emit)

        self.open_cfg_btn = WrapButton("📂 Open")
        self.open_cfg_btn.setToolTip("Open config.yaml in default editor")
        self.open_cfg_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.open_cfg_btn.clicked.connect(self.open_config_requested.emit)

        self.reload_btn = WrapButton("🔄 Reload")
        self.reload_btn.setToolTip("Reload configuration from file")
        self.reload_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.reload_btn.clicked.connect(self.reload_config_requested.emit)

        self.restart_app_btn = WrapButton("♻ Restart")
        self.restart_app_btn.setToolTip("Restart Startup Terminal (services keep running)")
        self.restart_app_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.restart_app_btn.clicked.connect(self.restart_app_requested.emit)

        for btn in (
            self.settings_btn,
            self.edit_cfg_btn,
            self.open_cfg_btn,
            self.reload_btn,
            self.restart_app_btn,
        ):
            cfg_flow.addWidget(btn)

        footer_layout.addWidget(cfg_box)
        main_layout.addWidget(footer_frame)

    def set_services(self, services: Dict[str, ManagedService]):
        """Populates or refreshes the service cards list."""
        for card in self.cards.values():
            card.setParent(None)
            card.deleteLater()
        self.cards.clear()

        while self.cards_layout.count() > 0:
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for svc in services.values():
            card = ServiceCard(svc)
            card.clicked.connect(self._on_card_clicked)
            card.start_requested.connect(self.start_service_requested.emit)
            card.stop_requested.connect(self.stop_service_requested.emit)
            card.restart_requested.connect(self.restart_service_requested.emit)
            card.edit_requested.connect(self.edit_service_requested.emit)
            card.delete_requested.connect(self.delete_service_requested.emit)
            card.enable_toggled.connect(self.service_enable_toggled.emit)
            self.cards_layout.addWidget(card)
            self.cards[svc.id] = card

        self.cards_layout.addStretch()

        if self.selected_svc_id in self.cards:
            self.select_service(self.selected_svc_id)
        elif self.cards:
            first_id = next(iter(self.cards.keys()))
            self.select_service(first_id)

        self.update_summary(services)

    def update_service_state(self, svc_id: str, state: str, pid: Optional[int] = None):
        if svc_id in self.cards:
            self.cards[svc_id].update_state(state, pid)

    def update_summary(self, services: Dict[str, ManagedService]):
        active = sum(1 for s in services.values() if s.state == ServiceState.RUNNING)
        disabled = sum(1 for s in services.values() if not s.enabled and s.state != ServiceState.RUNNING)
        stopped = len(services) - active - disabled
        text = f"{active} active • {stopped} stopped"
        if disabled:
            text += f" • {disabled} disabled"
        self.summary_label.setText(text)

    def select_service(self, svc_id: str):
        self.selected_svc_id = svc_id
        for cid, card in self.cards.items():
            card.set_selected(cid == svc_id)
        self.service_selected.emit(svc_id)

    def _on_card_clicked(self, svc_id: str):
        self.select_service(svc_id)

    def set_autostart_checked(self, enabled: bool):
        self.autostart_chk.blockSignals(True)
        self.autostart_chk.setChecked(enabled)
        self.autostart_chk.blockSignals(False)
