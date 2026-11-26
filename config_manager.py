"""Configuration Manager for Startup Terminal.

Handles loading, validating, saving, and auto-generating the YAML configuration.
Supports both local workspace config (./config.yaml) and the intuitive Windows
roaming app data location (%APPDATA%/StartupTerminal/config.yaml).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import yaml

APP_NAME = "StartupTerminal"
CONFIG_FILE_NAME = "config.yaml"
SUPPORTED_SHELLS = ("cmd", "powershell", "pwsh")


class _ConfigDumper(yaml.SafeDumper):
    """Dumps multi-line strings (e.g. scripts) as readable YAML '|' blocks."""


def _represent_str(dumper: yaml.SafeDumper, value: str):
    if "\n" in value:
        return dumper.represent_scalar("tag:yaml.org,2002:str", value, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", value)


_ConfigDumper.add_representer(str, _represent_str)

DEFAULT_CONFIG_TEMPLATE = f"""# ==============================================================================
# Startup Terminal Configuration
# ==============================================================================
# This configuration file controls the commands and services managed by Startup Terminal.
# The app can start with Windows automatically and execute these commands in parallel.
#
# Global Settings:
#   start_with_windows: true/false  # Auto-register in Windows Startup (Registry)
#   minimize_to_tray_on_close: true # Minimize to system tray when X is clicked
#   start_minimized: false          # Start minimized in system tray when Windows boots
#   auto_start_all: true            # Automatically start all enabled services on launch
#   max_log_lines: 5000             # Max memory buffer lines per service
#
# Service Options:
#   id: (optional) Unique identifier (slug)
#   name: Display name in the sidebar
#   command: Command line to run (e.g. python server.py, uvicorn app:main --port 8000).
#            May span multiple lines (use a YAML "|" block) - it is then run as a script.
#   shell: cmd | powershell | pwsh (Default: cmd) - interpreter used to run the command
#   cwd: (optional) Working directory for the command (defaults to config directory)
#   enabled: true/false (Default: true) - disabled services never start (manual, autostart or auto-restart)
#   auto_start: true/false (Default: true)
#   restart_on_failure: true/false (Default: false)
#   restart_delay_sec: Number of seconds to wait before auto-restarting (Default: 3)
#   env: (optional) Dictionary of environment variables to inject
# ==============================================================================

settings:
  start_with_windows: true
  minimize_to_tray_on_close: true
  start_minimized: false
  auto_start_all: true
  max_log_lines: 5000

services:
  - id: "fastapi-demo"
    name: "FastAPI Backend"
    command: "python sample_servers/api_server.py"
    auto_start: true
    restart_on_failure: true
    restart_delay_sec: 3
    env:
      PORT: "5055"
      ENV: "development"

  - id: "worker-demo"
    name: "Background Worker"
    command: "python sample_servers/worker.py"
    auto_start: true
    restart_on_failure: true
    restart_delay_sec: 5
    env:
      WORKER_CONCURRENCY: "2"

  - id: "metrics-demo"
    name: "Metrics Collector"
    command: "python sample_servers/metrics_server.py"
    auto_start: true
    restart_on_failure: false
"""


def get_appdata_dir() -> Path:
    """Returns the intuitive Windows AppData directory for Startup Terminal."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        base_dir = Path(appdata) / APP_NAME
    else:
        base_dir = Path.home() / f".{APP_NAME.lower()}"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def get_resolved_config_path(preferred_path: Optional[str] = None) -> Path:
    """Resolves which config file to use.

    Priority:
    1. preferred_path argument (if provided)
    2. Local `./config.yaml` in current working directory or script directory
    3. `%APPDATA%/StartupTerminal/config.yaml`
    """
    if preferred_path:
        return Path(preferred_path).resolve()

    # Check local workspace
    local_script_cfg = Path(__file__).resolve().parent / CONFIG_FILE_NAME
    if local_script_cfg.is_file():
        return local_script_cfg

    local_cwd_cfg = Path.cwd() / CONFIG_FILE_NAME
    if local_cwd_cfg.is_file():
        return local_cwd_cfg

    # Fallback to intuitive Windows AppData
    appdata_cfg = get_appdata_dir() / CONFIG_FILE_NAME
    return appdata_cfg


def ensure_config_exists(config_path: Optional[Path] = None) -> Path:
    """Ensures a config file exists on disk, creating a commented default if not."""
    path = config_path or get_resolved_config_path()
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_CONFIG_TEMPLATE, encoding="utf-8")
    return path


def validate_config(data: Any) -> Tuple[bool, str]:
    """Validates configuration schema.

    Returns (is_valid, error_message).
    """
    if not isinstance(data, dict):
        return False, "Config root must be a YAML mapping (dictionary)."

    services = data.get("services")
    if services is not None and not isinstance(services, list):
        return False, "'services' must be a list of service definitions."

    if isinstance(services, list):
        for idx, svc in enumerate(services):
            if not isinstance(svc, dict):
                return False, f"Service #{idx + 1} must be a dictionary."
            if not svc.get("name"):
                return False, f"Service #{idx + 1} is missing a 'name' field."
            if not svc.get("command"):
                return False, f"Service '{svc.get('name')}' is missing a 'command' field."

    return True, ""


def load_config(config_path: Optional[Path] = None) -> Tuple[Dict[str, Any], Path]:
    """Loads configuration from YAML file.

    If file doesn't exist, initializes it with default template.
    Returns (config_dict, resolved_path).
    """
    path = ensure_config_exists(config_path)

    try:
        content = path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
        if not data:
            data = {}
    except Exception as exc:
        raise ValueError(f"Failed to parse YAML from {path}: {exc}") from exc

    is_valid, err = validate_config(data)
    if not is_valid:
        raise ValueError(f"Invalid configuration in {path}: {err}")

    # Normalize defaults
    if "settings" not in data or not isinstance(data["settings"], dict):
        data["settings"] = {}

    settings = data["settings"]
    settings.setdefault("start_with_windows", True)
    settings.setdefault("minimize_to_tray_on_close", True)
    settings.setdefault("start_minimized", False)
    settings.setdefault("auto_start_all", True)
    settings.setdefault("max_log_lines", 5000)

    services: List[Dict[str, Any]] = data.get("services", [])
    normalized_services = []
    for idx, svc in enumerate(services):
        if not isinstance(svc, dict):
            continue
        name = str(svc.get("name", f"Service {idx+1}")).strip()
        svc_id = str(svc.get("id", "")).strip() or f"svc_{idx}_{name.lower().replace(' ', '_')}"

        normalized = {
            "id": svc_id,
            "name": name,
            "command": str(svc.get("command", "")).strip(),
            "shell": shell if (shell := str(svc.get("shell") or "cmd").lower()) in SUPPORTED_SHELLS else "cmd",
            "cwd": svc.get("cwd"),
            "enabled": bool(svc.get("enabled", True)),
            "auto_start": bool(svc.get("auto_start", True)),
            "restart_on_failure": bool(svc.get("restart_on_failure", False)),
            "restart_delay_sec": int(svc.get("restart_delay_sec", 3)),
            "env": svc.get("env") if isinstance(svc.get("env"), dict) else {},
        }
        normalized_services.append(normalized)

    data["services"] = normalized_services
    return data, path


def save_config_text(content: str, path: Path) -> Tuple[bool, str]:
    """Validates and saves raw YAML text to file."""
    try:
        parsed = yaml.safe_load(content)
        is_valid, err = validate_config(parsed)
        if not is_valid:
            return False, err
        path.write_text(content, encoding="utf-8")
        return True, ""
    except Exception as exc:
        return False, str(exc)


def save_config_dict(data: Dict[str, Any], path: Path) -> Tuple[bool, str]:
    """Serializes and saves dictionary config to YAML."""
    try:
        is_valid, err = validate_config(data)
        if not is_valid:
            return False, err
        raw_yaml = yaml.dump(data, Dumper=_ConfigDumper, sort_keys=False, default_flow_style=False, allow_unicode=True)
        path.write_text(raw_yaml, encoding="utf-8")
        return True, ""
    except Exception as exc:
        return False, str(exc)


def add_service_to_config(service_dict: Dict[str, Any], config_path: Optional[Path] = None) -> Tuple[bool, str]:
    """Adds a new service to the config file."""
    try:
        data, path = load_config(config_path)
        services = data.setdefault("services", [])
        
        # Ensure unique ID
        svc_id = service_dict.get("id") or service_dict["name"].lower().replace(" ", "-")
        existing_ids = {s.get("id") for s in services}
        base_id = svc_id
        counter = 1
        while svc_id in existing_ids:
            svc_id = f"{base_id}-{counter}"
            counter += 1
        service_dict["id"] = svc_id

        services.append(service_dict)
        return save_config_dict(data, path)
    except Exception as exc:
        return False, str(exc)


def update_service_in_config(
    service_id: str, updated_dict: Dict[str, Any], config_path: Optional[Path] = None
) -> Tuple[bool, str]:
    """Updates an existing service in the config file."""
    try:
        data, path = load_config(config_path)
        services = data.get("services", [])
        found = False
        for idx, svc in enumerate(services):
            if svc.get("id") == service_id:
                updated_dict["id"] = service_id
                services[idx] = updated_dict
                found = True
                break

        if not found:
            return False, f"Service with ID '{service_id}' not found."

        return save_config_dict(data, path)
    except Exception as exc:
        return False, str(exc)


def set_service_enabled_in_config(
    service_id: str, enabled: bool, config_path: Optional[Path] = None
) -> Tuple[bool, str]:
    """Enables or disables a service in the config file."""
    try:
        data, path = load_config(config_path)
        for svc in data.get("services", []):
            if svc.get("id") == service_id:
                svc["enabled"] = bool(enabled)
                return save_config_dict(data, path)
        return False, f"Service with ID '{service_id}' not found."
    except Exception as exc:
        return False, str(exc)


def delete_service_from_config(service_id: str, config_path: Optional[Path] = None) -> Tuple[bool, str]:
    """Deletes a service from the config file."""
    try:
        data, path = load_config(config_path)
        services = data.get("services", [])
        initial_len = len(services)
        data["services"] = [s for s in services if s.get("id") != service_id]

        if len(data["services"]) == initial_len:
            return False, f"Service with ID '{service_id}' not found."

        return save_config_dict(data, path)
    except Exception as exc:
        return False, str(exc)
