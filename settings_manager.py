"""Centralized persistent UI & application settings for Startup Terminal.

Stores typed user preferences (window geometry, splitter state, UI scale,
log viewer preferences, tray behavior, and GitHub Releases auto-update
settings) in %APPDATA%/StartupTerminal/settings.json (or ~/.startup_terminal_settings.json).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Callable, List, Optional


def get_settings_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        base = Path(appdata) / "StartupTerminal"
    else:
        base = Path.home() / ".startupterminal"
    return base / "settings.json"


@dataclass
class SettingsData:
    # General & Window
    start_minimized: bool = False
    autostart_minimized: bool = True
    close_to_tray: bool = True
    remember_window_geometry: bool = True
    window_x: Optional[int] = None
    window_y: Optional[int] = None
    window_width: Optional[int] = None
    window_height: Optional[int] = None
    window_maximized: bool = False
    splitter_sizes: Optional[List[int]] = None
    ui_scale_percent: int = 100

    # Services & Logs
    auto_start_all: bool = True
    max_log_lines: int = 5000
    log_font_size: int = 10
    log_word_wrap: bool = False

    # Auto-Update (GitHub Releases)
    auto_check_updates: bool = True
    auto_install_updates: bool = True
    skipped_version: str = ""
    last_update_check: float = 0.0


class AppSettings:
    """Singleton-friendly settings store with atomic JSON persistence."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else get_settings_path()
        self.data = SettingsData()
        self._listeners: List[Callable[[], None]] = []
        self.load()

    def load(self):
        if self.path.is_file():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    valid = {fld.name for fld in fields(SettingsData)}
                    for k, v in raw.items():
                        if k in valid:
                            setattr(self.data, k, v)
            except Exception:
                pass
        else:
            self.save()

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.path.with_suffix(".json.tmp")
            tmp_path.write_text(json.dumps(asdict(self.data), indent=2), encoding="utf-8")
            os.replace(tmp_path, self.path)
        except Exception:
            pass

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self.data, key, default)

    def set(self, key: str, value: Any, save: bool = True, notify: bool = False):
        if hasattr(self.data, key):
            setattr(self.data, key, value)
            if save:
                self.save()
            if notify:
                self.notify_changed()

    def update(self, save: bool = True, notify: bool = True, **kwargs):
        changed = False
        for k, v in kwargs.items():
            if hasattr(self.data, k) and getattr(self.data, k) != v:
                setattr(self.data, k, v)
                changed = True
        if changed:
            if save:
                self.save()
            if notify:
                self.notify_changed()

    def add_listener(self, cb: Callable[[], None]):
        if cb not in self._listeners:
            self._listeners.append(cb)

    def notify_changed(self):
        for cb in list(self._listeners):
            try:
                cb()
            except Exception:
                pass


_global_settings: Optional[AppSettings] = None


def get_settings() -> AppSettings:
    global _global_settings
    if _global_settings is None:
        _global_settings = AppSettings()
    return _global_settings
