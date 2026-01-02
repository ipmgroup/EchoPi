#!/usr/bin/env python3
"""Сравнение результатов find_peaks и measure_distance."""

import sys
sys.path.insert(0, '/home/pi/src/EchoPi5/src')

import numpy as np
from echopi.config import AudioDeviceConfig, ChirpConfig
from echopi.dsp.chirp import generate_chirp, normalize
from echopi.dsp.correlation import cross_correlation, find_peaks, parabolic_interpolate
from echopi.io.audio import play_and_record
from echopi import settings


def main():
    cfg_audio = AudioDeviceConfig(sample_rate=96000, frames_per_buffer=1024)
    cfg_chirp = ChirpConfig(start_freq=2000, end_freq=20000, duration=0.05, amplitude=0.8, fade_fraction=0.0)
    
    system_latency_s = settings.get_system_latency()
    
    # ОДНО измерение для обоих методов
    print("Выполняем ОДНО измерение...")
    
    # Генерация чирпа для излучения (БЕЗ окна)
    chirp_tx = generate_chirp(cfg_chirp, sample_rate=cfg_audio.sample_rate)
    chirp_tx = normalize(chirp_tx, peak=cfg_chirp.amplitude)
    
    # Генерация эталона для корреляции (С окном 5%)
    cfg_ref = ChirpConfig(
        start_freq=cfg_chirp.start_freq,
        end_freq=cfg_chirp.end_freq,
        duration=cfg_chirp.duration,
        amplitude=cfg_chirp.amplitude,
        fade_fraction=0.05
    )
    chirp_ref = generate_chirp(cfg_ref, sample_rate=cfg_audio.sample_rate)
    chirp_ref = normalize(chirp_ref, peak=1.0)
    
    # ОДНА запись для обоих
    recorded = play_and_record(chirp_tx, cfg_audio, extra_record_seconds=0.1)
    
    # Корреляция
    lag_samples, peak, corr = cross_correlation(chirp_ref, recorded)
    
    # Поиск пиков
    peaks = find_peaks(corr, num_peaks=15, min_distance=50)
    
    ref_offset = len(chirp_ref) - 1
    sound_speed = 343.0
    
    print()
    print("="*80)
    print("ВСЕ ПИКИ (отсортированы по амплитуде):")
    print("="*80)
    
    for i, (idx, value) in enumerate(peaks[:10], 1):
        refined_idx, refined_value = parabolic_interpolate(corr, idx)
        refined_lag = refined_idx - ref_offset
        total_time_s = refined_lag / cfg_audio.sample_rate
        time_of_flight_s = total_time_s - system_latency_s
        distance_m = (sound_speed * time_of_flight_s) / 2.0
        
        print(f"Пик {i}: lag={refined_lag:.2f} samples, "
              f"ToF={time_of_flight_s*1000:.3f} ms, "
              f"dist={distance_m:.3f} m ({distance_m*100:.0f} cm), "
              f"amplitude={value:.1f}")
    
    print()
    print("="*80)
    print("ЛОГИКА measure_distance (первый пик после латентности):")
    print("="*80)
    
    min_lag_samples = system_latency_s * cfg_audio.sample_rate + 50
    print(f"Минимальная задержка: {min_lag_samples:.0f} samples ({min_lag_samples/cfg_audio.sample_rate*1000:.3f} ms)")
    print()
    
    best_peak_idx = None
    for i, (idx, value) in enumerate(peaks, 1):
        lag = idx - ref_offset
        
        status = ""
        if lag < min_lag_samples:
            status = "ПРОПУЩЕН (до латентности)"
        else:
            if best_peak_idx is None:
                best_peak_idx = idx
                status = "✓ ВЫБРАН (первый после латентности)"
            else:
                status = "пропущен (уже выбран другой)"
        
        print(f"Пик {i}: lag={lag:.0f} samples, amplitude={value:.1f} -> {status}")
    
    if best_peak_idx:
        refined_idx, refined_value = parabolic_interpolate(corr, best_peak_idx)
        refined_lag = refined_idx - ref_offset
        total_time_s = refined_lag / cfg_audio.sample_rate
        time_of_flight_s = total_time_s - system_latency_s
        distance_m = (sound_speed * time_of_flight_s) / 2.0
        
        print()
        print("="*60)
        print(f"РЕЗУЛЬТАТ: До препятствия {distance_m:.2f} м ({distance_m*100:.0f} см)")
        print("="*60)


if __name__ == "__main__":
    main()
