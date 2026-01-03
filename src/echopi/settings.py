"""Configuration file management for EchoPi.

Handles loading and saving persistent settings like system latency.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


# Default configuration directory
CONFIG_DIR = Path.home() / ".config" / "echopi"
CONFIG_FILE = CONFIG_DIR / "init.json"

# Default settings
DEFAULT_SETTINGS = {
    "system_latency_s": 0.00121,  # Default system latency in seconds
    "min_distance_m": 0.0,        # Default min distance for echo window (meters)
    "max_distance_m": 17.0,       # Default max distance for echo window (meters)
    # GUI defaults (persisted in init.json)
    "start_freq_hz": 1000.0,
    "end_freq_hz": 10000.0,
    "chirp_duration_s": 0.05,
    "amplitude": 0.8,
    "medium": "air",
    "update_rate_hz": 2.0,
    "filter_size": 3,
    "sample_rate": 48000,  # INMP441 максимум 50 кГц, по умолчанию 48 кГц
    "version": "0.0.1"
}


def _get_value(key: str, default: Any) -> Any:
    settings = load_settings()
    return settings.get(key, default)


def get_gui_settings() -> dict[str, Any]:
    """Return GUI-related settings (merged with defaults)."""
    s = load_settings()
    return {
        "start_freq_hz": s.get("start_freq_hz", DEFAULT_SETTINGS["start_freq_hz"]),
        "end_freq_hz": s.get("end_freq_hz", DEFAULT_SETTINGS["end_freq_hz"]),
        "chirp_duration_s": s.get("chirp_duration_s", DEFAULT_SETTINGS["chirp_duration_s"]),
        "amplitude": s.get("amplitude", DEFAULT_SETTINGS["amplitude"]),
        "medium": s.get("medium", DEFAULT_SETTINGS["medium"]),
        "update_rate_hz": s.get("update_rate_hz", DEFAULT_SETTINGS["update_rate_hz"]),
        "filter_size": s.get("filter_size", DEFAULT_SETTINGS["filter_size"]),
        "min_distance_m": s.get("min_distance_m", DEFAULT_SETTINGS["min_distance_m"]),
        "max_distance_m": s.get("max_distance_m", DEFAULT_SETTINGS["max_distance_m"]),
        "system_latency_s": s.get("system_latency_s", DEFAULT_SETTINGS["system_latency_s"]),
    }


def set_gui_settings(values: dict[str, Any]) -> bool:
    """Save a subset of GUI-related settings."""
    allowed = {
        "start_freq_hz",
        "end_freq_hz",
        "chirp_duration_s",
        "amplitude",
        "medium",
        "update_rate_hz",
        "filter_size",
        "max_distance_m",
        "system_latency_s",
    }
    payload = {k: v for k, v in values.items() if k in allowed}
    if not payload:
        return True
    return save_settings(payload)


def ensure_config_dir():
    """Ensure configuration directory exists."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_settings() -> dict[str, Any]:
    """Load settings from init.json file.
    
    Returns:
        Dictionary with settings. If file doesn't exist, returns defaults.
    """
    if not CONFIG_FILE.exists():
        return DEFAULT_SETTINGS.copy()
    
    try:
        with open(CONFIG_FILE, 'r') as f:
            settings = json.load(f)
        
        # Merge with defaults to ensure all keys exist
        result = DEFAULT_SETTINGS.copy()
        result.update(settings)
        return result
        
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Failed to load config from {CONFIG_FILE}: {e}")
        print("Using default settings")
        return DEFAULT_SETTINGS.copy()


def save_settings(settings: dict[str, Any]) -> bool:
    """Save settings to init.json file.
    
    Args:
        settings: Dictionary with settings to save
        
    Returns:
        True if successful, False otherwise
    """
    try:
        ensure_config_dir()
        
        # Merge with existing settings to preserve other values
        current = load_settings()
        current.update(settings)
        
        with open(CONFIG_FILE, 'w') as f:
            json.dump(current, f, indent=2)
        
        print(f"Settings saved to {CONFIG_FILE}")
        return True
        
    except (IOError, OSError) as e:
        print(f"Error: Failed to save config to {CONFIG_FILE}: {e}")
        return False


def get_system_latency(verbose: bool = False) -> float:
    """Get system latency from configuration.
    
    Args:
        verbose: If True, print where the value was loaded from
    
    Returns:
        System latency in seconds (from init.json if exists, otherwise default)
    """
    settings = load_settings()
    latency = settings.get("system_latency_s", DEFAULT_SETTINGS["system_latency_s"])
    
    if verbose:
        if CONFIG_FILE.exists():
            print(f"✓ System latency loaded from {CONFIG_FILE}: {latency:.6f} s")
        else:
            print(f"ℹ Using default system latency: {latency:.6f} s (config file not found)")
    
    return latency


def set_system_latency(latency_s: float) -> bool:
    """Save system latency to configuration.
    
    Args:
        latency_s: System latency in seconds
        
    Returns:
        True if successful, False otherwise
    """
    return save_settings({"system_latency_s": latency_s})


def get_max_distance(verbose: bool = False) -> float:
    """Get max distance (meters) used to size echo record window."""
    settings = load_settings()
    value = settings.get("max_distance_m", DEFAULT_SETTINGS["max_distance_m"])
    try:
        value_f = float(value)
    except (TypeError, ValueError):
        value_f = float(DEFAULT_SETTINGS["max_distance_m"])

    if verbose:
        if CONFIG_FILE.exists():
            print(f"✓ Max distance loaded from {CONFIG_FILE}: {value_f:.2f} m")
        else:
            print(f"ℹ Using default max distance: {value_f:.2f} m (config file not found)")

    return value_f


def set_max_distance(max_distance_m: float) -> bool:
    """Save max distance (meters) to configuration."""
    try:
        value = float(max_distance_m)
    except (TypeError, ValueError):
        raise ValueError(f"max_distance_m must be a number, got {max_distance_m!r}")
    if value <= 0:
        raise ValueError(f"max_distance_m must be > 0, got {value}")
    return save_settings({"max_distance_m": value})


def get_min_distance(verbose: bool = False) -> float:
    """Get min distance (meters) used to filter close reflections."""
    settings = load_settings()
    value = settings.get("min_distance_m", DEFAULT_SETTINGS["min_distance_m"])
    try:
        value_f = float(value)
    except (TypeError, ValueError):
        value_f = float(DEFAULT_SETTINGS["min_distance_m"])

    if verbose:
        if CONFIG_FILE.exists():
            print(f"✓ Min distance loaded from {CONFIG_FILE}: {value_f:.2f} m")
        else:
            print(f"ℹ Using default min distance: {value_f:.2f} m (config file not found)")

    return value_f


def set_min_distance(min_distance_m: float) -> bool:
    """Save min distance (meters) to configuration."""
    try:
        value = float(min_distance_m)
    except (TypeError, ValueError):
        raise ValueError(f"min_distance_m must be a number, got {min_distance_m!r}")
    if value < 0:
        raise ValueError(f"min_distance_m must be >= 0, got {value}")
    return save_settings({"min_distance_m": value})


def get_start_freq() -> float:
    """Get start frequency (Hz) from config."""
    return _get_value("start_freq_hz", DEFAULT_SETTINGS["start_freq_hz"])


def get_end_freq() -> float:
    """Get end frequency (Hz) from config."""
    return _get_value("end_freq_hz", DEFAULT_SETTINGS["end_freq_hz"])


def get_amplitude() -> float:
    """Get amplitude (0-1) from config."""
    return _get_value("amplitude", DEFAULT_SETTINGS["amplitude"])


def get_config_file_path() -> Path:
    """Get path to configuration file.
    
    Returns:
        Path to init.json
    """
    return CONFIG_FILE
