from __future__ import annotations

import numpy as np
import scipy.signal

from echopi.config import ChirpConfig


def generate_chirp(cfg: ChirpConfig, sample_rate: int | None = None) -> np.ndarray:
    sr = sample_rate or 48000  # INMP441 максимум 50 кГц, по умолчанию 48 кГц
    t = np.linspace(0.0, cfg.duration, int(sr * cfg.duration), endpoint=False)
    sweep = scipy.signal.chirp(t, f0=cfg.start_freq, f1=cfg.end_freq, t1=cfg.duration, method="linear")
    if cfg.fade_fraction > 0:
        n = len(sweep)
        fade_len = max(1, int(n * cfg.fade_fraction))
        window = np.ones(n)
        ramp = np.linspace(0.0, 1.0, fade_len)
        window[:fade_len] = ramp
        window[-fade_len:] = ramp[::-1]
        sweep *= window
    return (cfg.amplitude * sweep).astype(np.float32)


def normalize(signal: np.ndarray, peak: float = 0.9) -> np.ndarray:
    max_val = np.max(np.abs(signal)) or 1.0
    return (signal / max_val * peak).astype(np.float32)
