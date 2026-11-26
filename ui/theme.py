"""Visual theme and stylesheets for Startup Terminal.

Provides a modern dark theme inspired by Windows 11 Fluent and developer tools.
"""

DARK_THEME_QSS = """
/* Global Application Styles */
QWidget {
    background-color: #0f1117;
    color: #e2e8f0;
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
    font-size: 13px;
    selection-background-color: #4f46e5;
    selection-color: #ffffff;
}

/* Scrollbars */
QScrollBar:vertical {
    border: none;
    background: #141721;
    width: 8px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background: #333a4f;
    min-height: 24px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #4f5875;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar:horizontal {
    border: none;
    background: #141721;
    height: 8px;
    margin: 0px;
}
QScrollBar::handle:horizontal {
    background: #333a4f;
    min-width: 24px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal:hover {
    background: #4f5875;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* Push Buttons */
QPushButton {
    background-color: #1e2230;
    color: #e2e8f0;
    border: 1px solid #2d3345;
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #282e42;
    border-color: #434c66;
}
QPushButton:pressed {
    background-color: #1a1e2b;
}
QPushButton:disabled {
    background-color: #151822;
    color: #555e75;
    border-color: #202534;
}

/* Primary Button */
QPushButton#primaryButton {
    background-color: #4f46e5;
    color: #ffffff;
    border: 1px solid #6366f1;
}
QPushButton#primaryButton:hover {
    background-color: #4338ca;
}

/* Success Button (Start) */
QPushButton#startBtn {
    background-color: #065f46;
    color: #ecfdf5;
    border: 1px solid #059669;
}
QPushButton#startBtn:hover {
    background-color: #047857;
}

/* Danger Button (Stop) */
QPushButton#stopBtn {
    background-color: #7f1d1d;
    color: #fef2f2;
    border: 1px solid #b91c1c;
}
QPushButton#stopBtn:hover {
    background-color: #991b1b;
}

/* Line Edits & Text Inputs */
QLineEdit, QTextEdit, QPlainTextEdit {
    background-color: #161922;
    color: #f1f5f9;
    border: 1px solid #2b3142;
    border-radius: 6px;
    padding: 6px 10px;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border: 1px solid #6366f1;
}

/* Combo Box */
QComboBox {
    background-color: #161922;
    color: #f1f5f9;
    border: 1px solid #2b3142;
    border-radius: 6px;
    padding: 5px 10px;
}
QComboBox:hover {
    border-color: #434c66;
}
QComboBox QAbstractItemView {
    background-color: #161922;
    color: #f1f5f9;
    border: 1px solid #2b3142;
    selection-background-color: #4f46e5;
    selection-color: #ffffff;
}

/* Checkbox */
QCheckBox {
    spacing: 8px;
    color: #cbd5e1;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid #3b435a;
    background-color: #161922;
}
QCheckBox::indicator:checked {
    background-color: #4f46e5;
    border-color: #6366f1;
}

/* Tooltips */
QToolTip {
    background-color: #1e2230;
    color: #f8fafc;
    border: 1px solid #3b435a;
    border-radius: 4px;
    padding: 5px;
}

/* Splitter */
QSplitter::handle {
    background-color: #1f2433;
}
QSplitter::handle:horizontal {
    width: 2px;
}

/* Menu */
QMenu {
    background-color: #1a1e2a;
    border: 1px solid #2d3345;
    padding: 6px;
    border-radius: 6px;
}
QMenu::item {
    padding: 6px 20px;
    border-radius: 4px;
}
QMenu::item:selected {
    background-color: #4f46e5;
    color: #ffffff;
}
QMenu::separator {
    height: 1px;
    background-color: #2d3345;
    margin: 4px 6px;
}
"""

COLOR_RUNNING = "#10b981"  # Emerald
COLOR_STOPPED = "#64748b"  # Slate
COLOR_STARTING = "#f59e0b" # Amber
COLOR_FAILED = "#ef4444"   # Red
COLOR_ACCENT = "#6366f1"   # Indigo
