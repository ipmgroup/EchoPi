from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AudioDeviceConfig:
    play_device: int | str | None = None
    rec_device: int | str | None = None
    sample_rate: int = 96000
    channels_play: int = 1
    channels_rec: int = 1
    frames_per_buffer: int = 2048
    latency: str | float | None = None  # "low", "high", float seconds or None


@dataclass
class ChirpConfig:
    start_freq: float = 2000.0
    end_freq: float = 20000.0
    duration: float = 0.05
    amplitude: float = 0.8
    fade_fraction: float = 0.0  # 0 = без окна (максимальная энергия), >0 = с окном Tukey
