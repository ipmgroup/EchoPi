from __future__ import annotations

import numpy as np

from echopi.config import AudioDeviceConfig, ChirpConfig
from echopi.dsp.chirp import generate_chirp, normalize
from echopi.dsp.correlation import cross_correlation, parabolic_interpolate, find_peaks
from echopi.io.audio import play_and_record


# Скорость звука (м/с)
SPEED_OF_SOUND = {
    "air": 343.0,      # 20°C, сухой воздух
    "water": 1480.0,   # пресная вода, 20°C
}


def measure_distance(
    cfg_audio: AudioDeviceConfig,
    cfg_chirp: ChirpConfig,
    medium: str = "air",
    system_latency_s: float = 0.0,
    reference_fade: float = 0.05,
) -> dict:
    """
    Измерение расстояния до цели с использованием чирп-сигнала.
    
    Args:
        cfg_audio: Конфигурация аудио устройства
        cfg_chirp: Конфигурация чирп-сигнала (для излучения)
        medium: Среда распространения ("air" или "water")
        system_latency_s: Известная системная задержка в секундах (TX→RX без акустики)
        reference_fade: Окно для эталона корреляции (0=без окна, >0=Tukey)
    
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
    
    # Берем ПЕРВЫЙ пик из отсортированного списка, который проходит фильтр по времени
    # Это будет самый сильный пик после системной латентности
    for idx, value in peaks:
        lag = idx - ref_offset
        
        # Пропускаем пики до системной латентности (это прямые сигналы/наводки)
        if lag < min_lag_samples:
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
    
    return {
        "time_of_flight_s": float(time_of_flight_s),
        "distance_m": float(distance_m),
        "lag_samples": int(lag_samples),
        "refined_lag": float(refined_lag),
        "peak": float(peak),
        "refined_peak": float(refined_peak),
        "sound_speed": float(sound_speed),
        "medium": medium,
        "total_time_s": float(total_time_s),
        "system_latency_s": float(system_latency_s),
    }
