from __future__ import annotations

import numpy as np

from echopi.config import AudioDeviceConfig, ChirpConfig
from echopi.dsp.chirp import generate_chirp, normalize
from echopi.dsp.correlation import cross_correlation, parabolic_interpolate
from echopi.io.audio import play_and_record


def measure_latency(cfg_audio: AudioDeviceConfig, cfg_chirp: ChirpConfig) -> dict:
    chirp = generate_chirp(cfg_chirp, sample_rate=cfg_audio.sample_rate)
    chirp = normalize(chirp, peak=cfg_chirp.amplitude)
    recorded = play_and_record(chirp, cfg_audio)
    lag_samples, peak, corr = cross_correlation(chirp, recorded)
    refined_idx, _ = parabolic_interpolate(corr, lag_samples + len(chirp) - 1)
    refined_lag = refined_idx - (len(chirp) - 1)
    latency_seconds = refined_lag / cfg_audio.sample_rate
    return {
        "lag_samples": int(lag_samples),
        "latency_seconds": float(latency_seconds),
        "peak": float(peak),
        "correlation_length": len(corr),
    }
