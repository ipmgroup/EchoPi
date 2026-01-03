from __future__ import annotations

import numpy as np
from collections import deque

from echopi.config import AudioDeviceConfig, ChirpConfig
from echopi.dsp.chirp import generate_chirp, normalize
from echopi.dsp.correlation import cross_correlation, parabolic_interpolate, find_peaks
from echopi.io.audio import play_and_record


# Скорость звука (м/с)
SPEED_OF_SOUND = {
    "air": 343.0,      # 20°C, сухой воздух
    "water": 1480.0,   # пресная вода, 20°C
}


# Global smoothing buffer for distance measurements
_distance_smoothing_buffer = deque(maxlen=3)


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
) -> dict:
    """
    Измерение расстояния до цели с использованием чирп-сигнала.
    
    Args:
        cfg_audio: Конфигурация аудио устройства
        cfg_chirp: Конфигурация чирп-сигнала (для излучения)
        medium: Среда распространения ("air" или "water")
        system_latency_s: Известная системная задержка в секундах (TX→RX без акустики)
        reference_fade: Окно для эталона корреляции (0=без окна, >0=Tukey)
        min_distance_m: Минимальная дистанция (м) для окна поиска пика (None = загрузить из настроек, или 0)
        max_distance_m: Максимальная дистанция (м) для окна поиска пика (None = загрузить из настроек, обычно 5м)
        extra_record_seconds: Дополнительное время записи после конца импульса (сек). None = вычислить из max_distance_m
        enable_smoothing: Включить сглаживание измерений
        filter_size: Размер фильтра сглаживания (1=без фильтра, 3=умеренный, 5+=сильный)
    
    Returns:
        dict с результатами измерения
        
    Raises:
        ValueError: Если параметры некорректны
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
    
    # Генерация излучаемого чирпа БЕЗ окна (максимальная энергия)
    cfg_tx = ChirpConfig(
        start_freq=cfg_chirp.start_freq,
        end_freq=cfg_chirp.end_freq,
        duration=cfg_chirp.duration,
        amplitude=cfg_chirp.amplitude,
        fade_fraction=0.0,  # БЕЗ окна при излучении
    )
    chirp_tx = generate_chirp(cfg_tx, sample_rate=cfg_audio.sample_rate)
    chirp_tx = normalize(chirp_tx, peak=cfg_chirp.amplitude)
    
    # Формирование эталона ВСЕГДА С ОКНОМ для корреляции (уменьшаем боковые лепестки)
    # Окно всегда используется на приеме для лучшего подавления шумов.
    # Даже если пользователь просит 0, принудительно держим минимум 5%.
    if reference_fade <= 0.0 or reference_fade < 0.05:
        reference_fade = 0.05
    
    cfg_ref = ChirpConfig(
        start_freq=cfg_chirp.start_freq,
        end_freq=cfg_chirp.end_freq,
        duration=cfg_chirp.duration,
        amplitude=cfg_chirp.amplitude,
        fade_fraction=reference_fade,  # ВСЕГДА с окном для эталона
    )
    chirp_ref = generate_chirp(cfg_ref, sample_rate=cfg_audio.sample_rate)
    chirp_ref = normalize(chirp_ref, peak=1.0)  # Нормализуем эталон
    
    # Излучение и запись
    sound_speed = SPEED_OF_SOUND.get(medium, SPEED_OF_SOUND["air"])
    extra_rec = compute_extra_record_seconds(
        medium=medium,
        max_distance_m=max_distance_m,
        extra_record_seconds=extra_record_seconds,
        default_extra_record_seconds=0.1,
        guard_seconds=0.005,
    )

    recorded = play_and_record(chirp_tx, cfg_audio, extra_record_seconds=extra_rec)
    
    # Корреляция с эталоном (с окном)
    lag_samples, peak, corr = cross_correlation(chirp_ref, recorded)

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
        # Take the STRONGEST peak from the window (peaks are sorted by amplitude descending)
        # This is the actual target reflection
        # Original logic from first commit: strongest peak in valid window
        best_peak_relative_idx, best_peak_value = peaks[0]
        best_peak_idx = start_idx + best_peak_relative_idx
    else:
        # Fallback: use maximum value in window
        best_peak_idx = int(start_idx + np.argmax(corr_window))
    
    # Финальная интерполяция выбранного пика
    refined_idx, refined_peak = parabolic_interpolate(corr, best_peak_idx)
    refined_lag = refined_idx - ref_offset
    lag_samples = best_peak_idx - ref_offset
    
    # Время распространения (вычитаем системную задержку)
    total_time_s = refined_lag / cfg_audio.sample_rate
    time_of_flight_s = total_time_s - system_latency_s
    
    # Расстояние: R = (c × t) / 2  (делим на 2, т.к. туда и обратно)
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
    }
