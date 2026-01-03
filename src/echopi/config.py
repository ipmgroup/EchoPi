from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AudioDeviceConfig:
    play_device: int | str | None = None
    rec_device: int | str | None = None
    sample_rate: int = 48000
    channels_play: int = 1
    channels_rec: int = 1
    frames_per_buffer: int = 2048  # Рекомендуется 256 для низкой задержки (см. README 5.3), но 2048 безопаснее (меньше XRUN)
    latency: str | float | None = None  # "low", "high", float seconds or None

    @classmethod
    def from_file(cls, config_path: str | Path | None = None) -> AudioDeviceConfig:
        """Load audio device config from file.
        
        Args:
            config_path: Path to config file. If None, uses ~/.config/echopi/audio_config.json
        """
        if config_path is None:
            config_path = Path.home() / ".config" / "echopi" / "audio_config.json"
        
        if not Path(config_path).exists():
            return cls()
        
        try:
            with open(config_path) as f:
                data = json.load(f)
            return cls(**{k: v for k, v in data.items() if hasattr(cls, k)})
        except Exception:
            return cls()


@dataclass
class ChirpConfig:
    start_freq: float = 2000.0
    end_freq: float = 20000.0
    duration: float = 0.05
    amplitude: float = 0.8
    fade_fraction: float = 0.0  # 0 = без окна (максимальная энергия), >0 = с окном Tukey
