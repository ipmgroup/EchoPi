from __future__ import annotations

import numpy as np
import time

from echopi.config import AudioDeviceConfig, ChirpConfig
from echopi.dsp.chirp import generate_chirp, normalize
from echopi.dsp.correlation import cross_correlation, find_peaks, parabolic_interpolate
from echopi.io.audio import get_global_stream, close_global_stream


def _pick_latency_from_recording(
    *,
    recorded: np.ndarray,
    chirp_ref: np.ndarray,
    sample_rate: int,
    max_latency_s: float = 0.003,  # Reduced from 0.005 to 0.003 (3ms) to avoid picking echoes
    min_latency_s: float = 0.0005,
) -> tuple[float, int, float, int, float, np.ndarray]:
    """Return (latency_s, lag_samples, peak, global_lag, global_peak, corr)."""
    global_lag_samples, global_peak, corr = cross_correlation(chirp_ref, recorded)
    ref_offset = len(chirp_ref) - 1

    min_lag_samples = max(10, int(min_latency_s * sample_rate))
    start_idx = ref_offset + min_lag_samples
    end_idx = int(
        min(
            len(corr) - 2,
            ref_offset + max(3, int(max_latency_s * sample_rate)),
        )
    )
    corr_window = corr[start_idx:end_idx]

    if corr_window.size:
        # For latency measurement, we want the EARLIEST strong peak in a narrow window
        # This is the direct signal path (microphone/speaker should be close for latency calibration)
        # We take earliest (chronologically first) to avoid echoes/reflections
        peaks = find_peaks(corr_window, num_peaks=30, min_distance=10)
        
        if peaks:
            # Filter peaks to only strong ones (>50% of strongest peak)
            max_amp = peaks[0][1]  # peaks sorted by amplitude descending
            strong_peaks = [(idx, amp) for idx, amp in peaks if amp > max_amp * 0.5]
            
            # Take the EARLIEST (lowest index) among strong peaks
            earliest_idx = min(strong_peaks, key=lambda p: p[0])[0]
            best_peak_idx = int(start_idx + earliest_idx)
        else:
            best_peak_idx = int(start_idx + np.argmax(corr_window))
    else:
        best_peak_idx = int(np.argmax(corr))

    refined_idx, refined_peak = parabolic_interpolate(corr, best_peak_idx)
    refined_lag = refined_idx - ref_offset
    latency_seconds = float(refined_lag / sample_rate)
    return (
        latency_seconds,
        int(round(refined_lag)),
        float(refined_peak),
        int(global_lag_samples),
        float(global_peak),
        corr,
    )


def measure_latency(
    cfg_audio: AudioDeviceConfig,
    cfg_chirp: ChirpConfig,
    *,
    repeats: int = 7,
    discard: int = 2,
) -> dict:
    chirp = generate_chirp(cfg_chirp, sample_rate=cfg_audio.sample_rate)
    chirp = normalize(chirp, peak=cfg_chirp.amplitude)

    # For correlation, prefer a windowed reference to reduce sidelobes.
    cfg_ref = ChirpConfig(
        start_freq=cfg_chirp.start_freq,
        end_freq=cfg_chirp.end_freq,
        duration=cfg_chirp.duration,
        amplitude=cfg_chirp.amplitude,
        fade_fraction=0.05,
    )
    chirp_ref = generate_chirp(cfg_ref, sample_rate=cfg_audio.sample_rate)
    chirp_ref = normalize(chirp_ref, peak=1.0)

    if repeats < 1:
        raise ValueError(f"repeats must be >= 1, got {repeats}")
    if discard < 0:
        raise ValueError(f"discard must be >= 0, got {discard}")
    if discard >= repeats:
        discard = max(0, repeats - 1)

    # Warmup/flush: a short silent job helps drop stale buffered samples.
    # Use global persistent stream for all measurements
    stream = get_global_stream(cfg_audio)
    try:
        _ = stream.play_and_record(
            np.zeros(cfg_audio.frames_per_buffer, dtype=np.float32),
            extra_record_seconds=0.0,
        )
    except Exception:
        pass

    latencies_s: list[float] = []
    peaks: list[float] = []
    last_corr_len = 0
    last_global_lag = 0
    last_global_peak = 0.0

    extra_record_seconds = 0.1
    # Minimum repeat period: cannot be shorter than chirp+record window.
    # Add a small guard for driver buffering and scheduling jitter.
    min_repeat_s = float(cfg_chirp.duration) + float(extra_record_seconds) + 0.02

    for i in range(repeats):
        t0 = time.monotonic()
        recorded = stream.play_and_record(chirp, extra_record_seconds=extra_record_seconds)
        (
            latency_s,
            lag_samp,
            peak,
            global_lag,
            global_peak,
            corr,
        ) = _pick_latency_from_recording(
            recorded=recorded,
            chirp_ref=chirp_ref,
            sample_rate=cfg_audio.sample_rate,
        )
        last_corr_len = len(corr)
        last_global_lag = global_lag
        last_global_peak = global_peak

        if i >= discard:
            latencies_s.append(float(latency_s))
            peaks.append(float(peak))

        elapsed = time.monotonic() - t0
        if elapsed < min_repeat_s:
            time.sleep(min_repeat_s - elapsed)

    arr = np.asarray(latencies_s, dtype=np.float64)
    raw_median_s = float(np.median(arr))
    raw_std_s = float(np.std(arr)) if arr.size > 1 else 0.0

    # Robust inlier selection using MAD. This helps when a few runs lock onto a
    # reflection peak and produce large outliers.
    abs_dev = np.abs(arr - raw_median_s)
    mad_s = float(np.median(abs_dev))
    if mad_s > 0:
        inlier_mask = abs_dev <= (3.5 * mad_s)
        used = arr[inlier_mask]
    else:
        used = arr

    median_s = float(np.median(used))
    std_s = float(np.std(used)) if used.size > 1 else 0.0

    return {
        "lag_samples": int(round(median_s * cfg_audio.sample_rate)),
        "latency_seconds": float(median_s),
        "latency_std_seconds": float(std_s),
        "latencies_seconds": [float(x) for x in arr],
        "latencies_used_seconds": [float(x) for x in used],
        "latency_raw_median_seconds": float(raw_median_s),
        "latency_raw_std_seconds": float(raw_std_s),
        "latency_mad_seconds": float(mad_s),
        "peak": float(np.median(np.asarray(peaks, dtype=np.float64))) if peaks else 0.0,
        "correlation_length": int(last_corr_len),
        "repeats": int(repeats),
        "discard": int(discard),
        "search_window_s": 0.005,
        "global_lag_samples": int(last_global_lag),
        "global_peak": float(last_global_peak),
    }
