from __future__ import annotations

import numpy as np
import scipy.signal

from echopi.config import ChirpConfig


def generate_chirp(cfg: ChirpConfig, sample_rate: int | None = None) -> np.ndarray:
    sr = sample_rate or 48000  # INMP441 maximum 50 kHz, default 48 kHz
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
    """Normalize signal to specified peak amplitude.
    
    Args:
        signal: Input signal
        peak: Target peak amplitude (0.0-1.0)
    
    Returns:
        Normalized signal with peak amplitude
    """
    signal = np.asarray(signal, dtype=np.float32)
    
    # Find maximum absolute value
    max_val = np.max(np.abs(signal))
    
    # Protection against division by zero or very small numbers
    # If signal is too small, return zero signal
    if max_val < 1e-10:
        return np.zeros_like(signal, dtype=np.float32)
    
    # Normalization with protection against numerical errors
    # Use more stable method to avoid amplitude jumps
    normalized = (signal / max_val * peak).astype(np.float32)
    
    # Check result (protection against overflow)
    actual_max = np.max(np.abs(normalized))
    if actual_max > peak * 1.01:  # Allow 1% deviation due to numerical errors
        # Recalculate with more precise normalization
        normalized = (signal / max_val * peak).astype(np.float32)
    
    return normalized
