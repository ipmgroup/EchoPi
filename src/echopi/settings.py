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
    "sample_rate": 96000,
    "version": "0.0.1"
}


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


def get_config_file_path() -> Path:
    """Get path to configuration file.
    
    Returns:
        Path to init.json
    """
    return CONFIG_FILE
