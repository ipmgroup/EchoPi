from __future__ import annotations

import numpy as np
from collections import deque
from functools import lru_cache

from echopi.config import AudioDeviceConfig, ChirpConfig
from echopi.dsp.chirp import generate_chirp, normalize
from echopi.dsp.correlation import cross_correlation, parabolic_interpolate, find_peaks
from echopi.io.audio_safe import get_global_stream


# Speed of sound (m/s)
SPEED_OF_SOUND = {
    "air": 343.0,      # 20°C, dry air
    "water": 1480.0,   # fresh water, 20°C
}


# Global smoothing buffer for distance measurements
_distance_smoothing_buffer = deque(maxlen=3)

# Cache for generated chirps (for amplitude stability)
_chirp_cache: dict[tuple, np.ndarray] = {}


def compute_extra_record_seconds(
    *,
    medium: str,
    max_distance_m: float | None = None,
    extra_record_seconds: float | None = None,
    default_extra_record_seconds: float = 0.1,
    guard_seconds: float = 0.005,
) -> float:
    """Compute how long to keep recording after the chirp ends.

    This separates chirp emission duration from the echo/record window.
    If `max_distance_m` is provided, the echo window is sized to capture
    the round-trip time for that distance.
    """
    if extra_record_seconds is not None:
        if extra_record_seconds < 0:
            raise ValueError(f"extra_record_seconds must be >= 0, got {extra_record_seconds}")
        return float(extra_record_seconds)

    if max_distance_m is None:
        if default_extra_record_seconds < 0:
            raise ValueError(
                f"default_extra_record_seconds must be >= 0, got {default_extra_record_seconds}"
            )
        return float(default_extra_record_seconds)

    if max_distance_m <= 0:
        raise ValueError(f"max_distance_m must be > 0, got {max_distance_m}")
    if guard_seconds < 0:
        raise ValueError(f"guard_seconds must be >= 0, got {guard_seconds}")

    sound_speed = SPEED_OF_SOUND.get(medium, SPEED_OF_SOUND["air"])
    return (2.0 * float(max_distance_m)) / float(sound_speed) + float(guard_seconds)


def set_smoothing_buffer_size(size: int):
    """Set the size of the distance smoothing buffer.
    
    Args:
        size: Buffer size (1 = no smoothing, 3-5 = moderate, 7-10 = heavy)
    """
    global _distance_smoothing_buffer
    max_size = max(1, size)  # At least 1
    _distance_smoothing_buffer = deque(_distance_smoothing_buffer, maxlen=max_size)


def clear_distance_smoothing():
    """Clear distance smoothing buffer (call when starting new measurement session)."""
    global _distance_smoothing_buffer
    _distance_smoothing_buffer.clear()


def clear_chirp_cache():
    """Clear chirp cache (call when parameters change significantly)."""
    global _chirp_cache
    _chirp_cache.clear()


def measure_distance(
    cfg_audio: AudioDeviceConfig,
    cfg_chirp: ChirpConfig,
    medium: str = "air",
    system_latency_s: float = 0.0,
    reference_fade: float = 0.05,
    min_distance_m: float | None = None,
    max_distance_m: float | None = None,
    extra_record_seconds: float | None = None,
    enable_smoothing: bool = True,
    filter_size: int = 3,
    normalize_recorded: bool = False,
) -> dict:
    """
    Measure distance to target using chirp signal.
    
    Args:
        cfg_audio: Audio device configuration
        cfg_chirp: Chirp signal configuration (for transmission)
        medium: Propagation medium ("air" or "water")
        system_latency_s: Known system latency in seconds (TX→RX without acoustics)
        reference_fade: Window for correlation reference (0=no window, >0=Tukey)
        min_distance_m: Minimum distance (m) for peak search window (None = load from settings, or 0)
        max_distance_m: Maximum distance (m) for peak search window (None = load from settings, typically 5m)
        extra_record_seconds: Additional recording time after pulse end (s). None = compute from max_distance_m
        enable_smoothing: Enable measurement smoothing
        filter_size: Smoothing filter size (1=no filter, 3=moderate, 5+=heavy)
        normalize_recorded: Normalize recorded signal before correlation (False = preserve SNR information)
    
    Returns:
        dict with measurement results
        
    Raises:
        ValueError: If parameters are invalid
    """
    # Load min_distance_m and max_distance_m from settings if not provided
    # This prevents selecting unwanted echoes (close objects or far walls)
    if min_distance_m is None:
        from echopi import settings
        min_distance_m = settings.get_min_distance()
    if max_distance_m is None:
        from echopi import settings
        max_distance_m = settings.get_max_distance()
    
    # Validate parameters
    if cfg_chirp.duration <= 0:
        raise ValueError(f"Chirp duration must be positive, got {cfg_chirp.duration}")
    if cfg_chirp.duration > 1.0:
        raise ValueError(f"Chirp duration too long (max 1.0s), got {cfg_chirp.duration}")
    if cfg_chirp.start_freq <= 0 or cfg_chirp.end_freq <= 0:
        raise ValueError("Frequencies must be positive")
    if cfg_chirp.start_freq >= cfg_chirp.end_freq:
        raise ValueError("Start frequency must be less than end frequency")
    if not (0.0 <= cfg_chirp.amplitude <= 1.0):
        raise ValueError(f"Amplitude must be in [0, 1], got {cfg_chirp.amplitude}")
    if filter_size < 0:
        raise ValueError(f"Filter size must be >= 0, got {filter_size}")
    if min_distance_m is not None and min_distance_m < 0:
        raise ValueError(f"min_distance_m must be >= 0, got {min_distance_m}")
    if max_distance_m is not None and max_distance_m <= 0:
        raise ValueError(f"max_distance_m must be > 0, got {max_distance_m}")
    if min_distance_m is not None and max_distance_m is not None and min_distance_m >= max_distance_m:
        raise ValueError(f"min_distance_m ({min_distance_m}) must be < max_distance_m ({max_distance_m})")
    if extra_record_seconds is not None and extra_record_seconds < 0:
        raise ValueError(f"extra_record_seconds must be >= 0, got {extra_record_seconds}")
    
    # Generate transmitted chirp WITHOUT window (maximum energy)
    # Use cache for amplitude stability (prevents volume jumps)
    cfg_tx = ChirpConfig(
        start_freq=cfg_chirp.start_freq,
        end_freq=cfg_chirp.end_freq,
        duration=cfg_chirp.duration,
        amplitude=cfg_chirp.amplitude,
        fade_fraction=0.0,  # NO window for transmission
    )
    
    # Cache key: chirp parameters + sample_rate + amplitude
    cache_key = (
        cfg_tx.start_freq,
        cfg_tx.end_freq,
        cfg_tx.duration,
        cfg_tx.fade_fraction,
        cfg_audio.sample_rate,
        cfg_chirp.amplitude,  # Include amplitude in key, as normalization depends on it
    )
    
    if cache_key in _chirp_cache:
        # Use cached chirp for stability
        chirp_tx = _chirp_cache[cache_key].copy()
    else:
        # Generate new chirp and cache it
        chirp_tx = generate_chirp(cfg_tx, sample_rate=cfg_audio.sample_rate)
        chirp_tx = normalize(chirp_tx, peak=cfg_chirp.amplitude)
        # Save to cache (copy for safety)
        _chirp_cache[cache_key] = chirp_tx.copy()
    
    # Form reference ALWAYS WITH WINDOW for correlation (reduces sidelobes)
    # Window is always used on receive for better noise suppression.
    # Even if user requests 0, we enforce minimum 5%.
    if reference_fade <= 0.0 or reference_fade < 0.05:
        reference_fade = 0.05
    
    cfg_ref = ChirpConfig(
        start_freq=cfg_chirp.start_freq,
        end_freq=cfg_chirp.end_freq,
        duration=cfg_chirp.duration,
        amplitude=cfg_chirp.amplitude,
        fade_fraction=reference_fade,  # ALWAYS with window for reference
    )
    chirp_ref = generate_chirp(cfg_ref, sample_rate=cfg_audio.sample_rate)
    chirp_ref = normalize(chirp_ref, peak=1.0)  # Normalize reference
    
    # Transmission and recording
    sound_speed = SPEED_OF_SOUND.get(medium, SPEED_OF_SOUND["air"])
    extra_rec = compute_extra_record_seconds(
        medium=medium,
        max_distance_m=max_distance_m,
        extra_record_seconds=extra_record_seconds,
        default_extra_record_seconds=0.1,
        guard_seconds=0.005,
    )

    # Check transmitted signal amplitude (for volume jump diagnostics)
    tx_max = np.max(np.abs(chirp_tx))
    tx_rms = np.sqrt(np.mean(chirp_tx**2))
    
    # Use global persistent stream for stable repeated measurements
    stream = get_global_stream(cfg_audio)
    # Get TX time anchor for accurate correlation
    recorded, tx_sample_index = stream.play_and_record(chirp_tx, extra_record_seconds=extra_rec)
    
    # Check for recorded signal clipping
    recorded_max = np.max(np.abs(recorded))
    if recorded_max >= 0.99:
        # Signal is clipped - this may distort correlation
        # Normalization may help in this case, but better to reduce amplitude
        pass  # Could add warning or automatic normalization
    
    # Optional normalization of recorded signal for matched filter
    # Normalization helps:
    # 1. Eliminate amplitude influence on correlation result
    # 2. Improve detection stability when volume changes
    # 3. Simplify detection threshold setting
    # 
    # BUT: normalization hides signal amplitude information (SNR)
    # Therefore by default we don't normalize to preserve SNR information
    # Use normalize_recorded=True if:
    # - There are amplitude instability issues
    # - Need more stable detection regardless of volume
    # - Signal is not clipped (recorded_max < 0.99)
    
    if normalize_recorded and recorded_max > 0.01 and recorded_max < 0.99:
        # Energy normalization (unit norm) - more stable for matched filter
        # This eliminates amplitude influence on correlation result
        recorded_energy = np.sqrt(np.sum(recorded**2))
        if recorded_energy > 1e-10:  # Protection against division by zero
            recorded = recorded / recorded_energy
    
    # Correlation with reference (matched filter: use reversed chirp)
    # For matched filter we need to use reversed reference
    #
    # IMPORTANT: TX time anchor (tx_sample_index) fixes the moment of TX chirp start
    # in the recorded signal. For simplex systems (play/record simultaneously)
    # tx_sample_index=0, i.e. TX chirp starts at recorded[0].
    # This is critical for accurate echo delay and distance calculation.
    #
    # In correlation:
    # - lag = 0 means echo arrived at tx_sample_index moment
    # - lag > 0 means echo delay relative to TX
    # - From lag we can compute distance: distance = (lag * sound_speed) / (2 * sample_rate)
    chirp_ref_reversed = chirp_ref[::-1]
    lag_samples, peak, corr = cross_correlation(chirp_ref_reversed, recorded)

    ref_offset = len(chirp_ref) - 1

    # Define valid lag window: after min_distance (or system latency), before max_distance.
    # This is critical to avoid selecting unwanted echoes (close objects or far walls).
    
    # System latency in samples (not counting guard margin)
    system_latency_samples = system_latency_s * cfg_audio.sample_rate
    
    # Start of search window: system latency + max(guard margin, min_distance round-trip)
    if min_distance_m is not None and min_distance_m > 0:
        min_distance_lag = (2.0 * float(min_distance_m) / float(sound_speed)) * cfg_audio.sample_rate
        start_lag_samples = system_latency_samples + max(50, min_distance_lag)
    else:
        start_lag_samples = system_latency_samples + 50  # At least 50 sample guard
    
    start_idx = int(ref_offset + int(start_lag_samples))
    
    # End of search window: max_distance round-trip time (or end of correlation)
    if max_distance_m is None or max_distance_m <= 0:
        end_idx = len(corr) - 2
    else:
        max_lag_samples = (2.0 * float(max_distance_m) / float(sound_speed)) * cfg_audio.sample_rate
        end_idx = int(min(len(corr) - 2, ref_offset + int(max_lag_samples)))
    
    if end_idx <= start_idx + 2:
        # Fallback if window is invalid
        end_idx = len(corr) - 2

    corr_window = corr[start_idx:end_idx]
    if corr_window.size == 0:
        raise ValueError("Correlation window is empty; check max_distance/latency")

    # Find all peaks in the correlation window
    peaks = find_peaks(corr_window, num_peaks=15, min_distance=50)
    
    if len(peaks) > 0:
        # Filter weak peaks (only peaks > 30% of maximum)
        max_peak_value = peaks[0][1]
        strong_peaks = [(idx, val) for idx, val in peaks if val > max_peak_value * 0.3]
        
        if len(strong_peaks) > 0:
            # If there are multiple strong peaks, choose the strongest
            # But if difference between top-2 peaks < 20%, this may be a problem
            if len(strong_peaks) > 1:
                top2_diff = (strong_peaks[0][1] - strong_peaks[1][1]) / strong_peaks[0][1]
                if top2_diff < 0.2:
                    # Two peaks close in amplitude - possible instability
                    # Choose earlier one (closer to window start) for stability
                    # This is preferable as distant reflections are usually weaker
                    best_peak_relative_idx, best_peak_value = min(strong_peaks[:2], key=lambda p: p[0])
                else:
                    # One peak is clearly stronger - use it
                    best_peak_relative_idx, best_peak_value = strong_peaks[0]
            else:
                best_peak_relative_idx, best_peak_value = strong_peaks[0]
            
            best_peak_idx = start_idx + best_peak_relative_idx
        else:
            # No strong peaks - use maximum
            best_peak_relative_idx, best_peak_value = peaks[0]
            best_peak_idx = start_idx + best_peak_relative_idx
    else:
        # Fallback: use maximum value in window
        best_peak_idx = int(start_idx + np.argmax(corr_window))
    
    # Final interpolation of selected peak
    refined_idx, refined_peak = parabolic_interpolate(corr, best_peak_idx)
    refined_lag = refined_idx - ref_offset
    lag_samples = best_peak_idx - ref_offset
    
    # Propagation time (subtract system latency)
    total_time_s = refined_lag / cfg_audio.sample_rate
    time_of_flight_s = total_time_s - system_latency_s
    
    # Distance: R = (c × t) / 2  (divide by 2, as it's round trip)
    distance_m = (sound_speed * time_of_flight_s) / 2.0
    
    # Apply smoothing if enabled and filter_size > 1 (0 or 1 = no filtering)
    global _distance_smoothing_buffer
    if enable_smoothing and filter_size > 1:
        # Update buffer size if changed
        if _distance_smoothing_buffer.maxlen != filter_size:
            set_smoothing_buffer_size(filter_size)
        _distance_smoothing_buffer.append(distance_m)
        # Calculate smoothed distance (average of recent measurements)
        if len(_distance_smoothing_buffer) > 0:
            smoothed_distance_m = sum(_distance_smoothing_buffer) / len(_distance_smoothing_buffer)
        else:
            smoothed_distance_m = distance_m
    else:
        smoothed_distance_m = distance_m
    
    return {
        "time_of_flight_s": float(time_of_flight_s),
        "distance_m": float(distance_m),
        "smoothed_distance_m": float(smoothed_distance_m),
        "lag_samples": int(lag_samples),
        "refined_lag": float(refined_lag),
        "peak": float(peak),
        "refined_peak": float(refined_peak),
        "sound_speed": float(sound_speed),
        "medium": medium,
        "total_time_s": float(total_time_s),
        "system_latency_s": float(system_latency_s),
        "extra_record_seconds": float(extra_rec),
        "max_distance_m": None if max_distance_m is None else float(max_distance_m),
        # Amplitude diagnostics (for volume jump detection)
        "tx_max": float(tx_max),
        "tx_rms": float(tx_rms),
        "recorded_max": float(recorded_max),
    }
