from __future__ import annotations

import numpy as np


def generate_sine(freq: float = 1000.0, duration: float = 1.0, amplitude: float = 0.8, sample_rate: int = 48000) -> np.ndarray:  # INMP441 maximum 50 kHz, default 48 kHz
    t = np.linspace(0.0, duration, int(sample_rate * duration), endpoint=False)
    signal = amplitude * np.sin(2 * np.pi * freq * t)
    return signal.astype(np.float32)
