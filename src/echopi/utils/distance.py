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
        enable_smoothing: Включить сглаживание измерений
        filter_size: Размер фильтра сглаживания (1=без фильтра, 3=умеренный, 5+=сильный)
    
    Returns:
        dict с результатами измерения
        
    Raises:
        ValueError: Если параметры некорректны
    """
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
    if filter_size < 1:
        raise ValueError(f"Filter size must be >= 1, got {filter_size}")
    
    Returns:
        dict с результатами:
            - time_of_flight_s: время распространения до цели и обратно
            - distance_m: расстояние до цели в метрах
            - lag_samples: задержка в отсчетах
            - peak: пик корреляции (амплитуда отраженного сигнала)
            - sound_speed: использованная скорость звука
    """
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
    # Окно всегда используется на приеме для лучшего подавления шумов
    if reference_fade == 0.0:
        reference_fade = 0.05  # Минимум 5% окно
    
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
    recorded = play_and_record(chirp_tx, cfg_audio)
    
    # Корреляция с эталоном (с окном)
    lag_samples, peak, corr = cross_correlation(chirp_ref, recorded)
    
    # Поиск нескольких пиков для выбора правильного целевого отражения
    peaks = find_peaks(corr, num_peaks=15, min_distance=50)
    
    ref_offset = len(chirp_ref) - 1
    sound_speed = SPEED_OF_SOUND.get(medium, SPEED_OF_SOUND["air"])
    
    # Находим ПЕРВЫЙ (самый сильный) пик ПОСЛЕ системной латентности
    # find_peaks уже отсортировал пики по убыванию амплитуды
    best_peak_idx = None
    
    # Минимальная задержка для фильтрации прямого сигнала (системная латентность + небольшой запас)
    min_lag_samples = system_latency_s * cfg_audio.sample_rate + 50
    
    # Минимальная амплитуда пика для фильтрации шумов (20% от максимального пика)
    if len(peaks) > 0:
        max_peak_amplitude = peaks[0][1]  # Первый пик - самый сильный
        min_peak_amplitude = max_peak_amplitude * 0.2
    else:
        min_peak_amplitude = 0.1
    
    # Берем ПЕРВЫЙ пик из отсортированного списка, который проходит фильтры
    # Это будет самый сильный пик после системной латентности с достаточной амплитудой
    for idx, value in peaks:
        lag = idx - ref_offset
        
        # Пропускаем пики до системной латентности (это прямые сигналы/наводки)
        if lag < min_lag_samples:
            continue
        
        # Пропускаем слабые пики (шумы и слабые отражения)
        if value < min_peak_amplitude:
            continue
        
        # Берем первый подходящий = самый сильный (список уже отсортирован)
        best_peak_idx = idx
        break
    
    # Если не найден подходящий пик, используем просто самый сильный
    if best_peak_idx is None and len(peaks) > 0:
        best_peak_idx = peaks[0][0]
    
    # Финальная интерполяция выбранного пика
    refined_idx, refined_peak = parabolic_interpolate(corr, best_peak_idx)
    refined_lag = refined_idx - ref_offset
    lag_samples = best_peak_idx - ref_offset
    
    # Время распространения (вычитаем системную задержку)
    total_time_s = refined_lag / cfg_audio.sample_rate
    time_of_flight_s = total_time_s - system_latency_s
    
    # Расстояние: R = (c × t) / 2  (делим на 2, т.к. туда и обратно)
    distance_m = (sound_speed * time_of_flight_s) / 2.0
    
    # Apply smoothing if enabled
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
    }
