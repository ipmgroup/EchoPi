#!/usr/bin/env python3
"""Тест для поиска нескольких пиков корреляции."""

import sys
sys.path.insert(0, '/home/pi/src/EchoPi5/src')

import numpy as np
from echopi.config import AudioDeviceConfig, ChirpConfig
from echopi.dsp.chirp import generate_chirp, normalize
from echopi.dsp.correlation import cross_correlation, find_peaks, parabolic_interpolate
from echopi.io.audio import play_and_record


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
    
    # Генерация чирпа
    chirp = generate_chirp(cfg_chirp, sample_rate=cfg_audio.sample_rate)
    chirp = normalize(chirp, peak=cfg_chirp.amplitude)
    
    print(f"Chirp length: {len(chirp)} samples ({len(chirp)/cfg_audio.sample_rate*1000:.1f} ms)")
    print(f"Recording...")
    
    # Запись
    recorded = play_and_record(chirp, cfg_audio, extra_record_seconds=0.1)
    
    print(f"Recorded length: {len(recorded)} samples ({len(recorded)/cfg_audio.sample_rate*1000:.1f} ms)")
    print()
    
    # Корреляция
    lag_samples, peak, corr = cross_correlation(chirp, recorded)
    
    # Поиск нескольких пиков
    peaks = find_peaks(corr, num_peaks=10, min_distance=100)
    
    print(f"Найдено {len(peaks)} пиков корреляции:")
    print()
    
    ref_offset = len(chirp) - 1
    
    for i, (idx, value) in enumerate(peaks, 1):
        # Интерполяция
        refined_idx, refined_value = parabolic_interpolate(corr, idx)
        
        # Расчет задержки
        lag = idx - ref_offset
        refined_lag = refined_idx - ref_offset
        
        # Время в мс
        time_ms = refined_lag / cfg_audio.sample_rate * 1000
        
        # Расстояние
        sound_speed = 343.0  # м/с
        distance_m = (sound_speed * (time_ms / 1000)) / 2
        
        print(f"Пик {i}:")
        print(f"  Индекс: {idx} → {refined_idx:.2f}")
        print(f"  Задержка: {lag} samples → {refined_lag:.2f} samples")
        print(f"  Время: {time_ms:.3f} ms")
        print(f"  Расстояние: {distance_m:.3f} m ({distance_m*100:.1f} cm)")
        print(f"  Амплитуда: {value:.1f} → {refined_value:.1f}")
        print(f"  Относительная амплитуда: {value/peaks[0][1]*100:.1f}%")
        print()


if __name__ == "__main__":
    main()
