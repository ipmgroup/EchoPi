#!/usr/bin/env python3
"""Измерение дистанции с выводом всех пиков."""

import sys
sys.path.insert(0, '/home/pi/src/EchoPi5/src')

import numpy as np
from echopi.config import AudioDeviceConfig, ChirpConfig
from echopi.dsp.chirp import generate_chirp, normalize
from echopi.dsp.correlation import cross_correlation, find_peaks, parabolic_interpolate
from echopi.io.audio import play_and_record
from echopi import settings


def main():
    # Конфигурация
    cfg_audio = AudioDeviceConfig(
        sample_rate=96000,
        frames_per_buffer=1024,
    )
    
    cfg_chirp = ChirpConfig(
        start_freq=2000,
        end_freq=20000,
        duration=0.05,
        amplitude=0.8,
        fade_fraction=0.0
    )
    
    # Системная латентность из конфига
    system_latency_s = settings.get_system_latency()
    print(f"System latency: {system_latency_s*1000:.3f} ms")
    print()
    
    # ВАЖНО: ограничим окно поиска разумной дистанцией (например, 2.5 метров)
    # Это предотвратит выбор дальних отражений
    max_distance_m = 2.5  # метров
    print(f"Max search distance: {max_distance_m} m")
    print()
    
    # Генерация чирпа для излучения (БЕЗ окна)
    chirp_tx = generate_chirp(cfg_chirp, sample_rate=cfg_audio.sample_rate)
    chirp_tx = normalize(chirp_tx, peak=cfg_chirp.amplitude)
    
    # Генерация эталона для корреляции (С окном)
    cfg_ref = ChirpConfig(
        start_freq=cfg_chirp.start_freq,
        end_freq=cfg_chirp.end_freq,
        duration=cfg_chirp.duration,
        amplitude=cfg_chirp.amplitude,
        fade_fraction=0.05  # С окном для эталона
    )
    chirp_ref = generate_chirp(cfg_ref, sample_rate=cfg_audio.sample_rate)
    chirp_ref = normalize(chirp_ref, peak=1.0)
    
    print("Recording...")
    recorded = play_and_record(chirp_tx, cfg_audio, extra_record_seconds=0.1)
    print()
    
    # Корреляция
    lag_samples, peak, corr = cross_correlation(chirp_ref, recorded)
    
    # Вычисляем окно поиска на основе max_distance_m
    ref_offset = len(chirp_ref) - 1
    sound_speed = 343.0  # м/с
    min_lag_samples = system_latency_s * cfg_audio.sample_rate + 50
    max_lag_samples = (2.0 * max_distance_m / sound_speed) * cfg_audio.sample_rate
    
    start_idx = int(ref_offset + max(0, int(min_lag_samples)))
    end_idx = int(min(len(corr) - 2, ref_offset + int(max_lag_samples)))
    
    print(f"Search window: samples {start_idx} to {end_idx} (lag {int(min_lag_samples)} to {int(max_lag_samples)})")
    print()
    
    # Поиск нескольких пиков ТОЛЬКО в окне поиска
    corr_window = corr[start_idx:end_idx]
    peaks_window = find_peaks(corr_window, num_peaks=10, min_distance=100)
    
    # Преобразуем индексы обратно к полному массиву корреляции
    peaks = [(start_idx + idx, value) for idx, value in peaks_window]
    
    print(f"Найдено {len(peaks)} пиков в окне поиска:")
    print("="*80)
    
    for i, (idx, value) in enumerate(peaks, 1):
        # Интерполяция
        refined_idx, refined_value = parabolic_interpolate(corr, idx)
        refined_lag = refined_idx - ref_offset
        
        # Время
        total_time_s = refined_lag / cfg_audio.sample_rate
        time_of_flight_s = total_time_s - system_latency_s
        
        # Расстояние
        distance_m = (sound_speed * time_of_flight_s) / 2
        
        marker = "★" if i == 1 else " "
        
        print(f"{marker} Пик {i}:")
        print(f"    Задержка: {refined_lag:.2f} samples ({total_time_s*1000:.3f} ms)")
        print(f"    Time of flight: {time_of_flight_s*1000:.3f} ms")
        print(f"    Дистанция: {distance_m:.3f} m ({distance_m*100:.1f} cm)")
        print(f"    Амплитуда: {refined_value:.1f} ({value/peaks[0][1]*100:.1f}%)")
        print()


if __name__ == "__main__":
    main()
