#!/usr/bin/env python3
"""Проверка расчетов эхолота."""

import sys
sys.path.insert(0, '/home/pi/src/EchoPi5/src')

from echopi.cli import main
from echopi.config import AudioDeviceConfig, ChirpConfig
from echopi import settings
from echopi.utils.distance import measure_distance

def main_test():
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
    
    system_latency_s = settings.get_system_latency()
    
    print("=" * 80)
    print("ЭХОЛОТ - Расчет расстояния")
    print("=" * 80)
    print()
    
    result = measure_distance(cfg_audio, cfg_chirp, medium="air", system_latency_s=system_latency_s)
    
    sound_speed = result['sound_speed']
    total_time_s = result['total_time_s']
    system_latency_s = result['system_latency_s']
    time_of_flight_s = result['time_of_flight_s']
    distance_m = result['distance_m']
    
    print(f"Скорость звука в воздухе: {sound_speed} м/с")
    print()
    
    print(f"Измеренное время (samples → время):")
    print(f"  Задержка: {result['refined_lag']:.2f} samples")
    print(f"  Общее время: {total_time_s*1000:.3f} ms")
    print()
    
    print(f"Системная латентность (электроника):")
    print(f"  Латентность: {system_latency_s*1000:.3f} ms")
    print()
    
    print(f"Время распространения звука (ТУДА и ОБРАТНО):")
    print(f"  Time of flight = Общее время - Латентность")
    print(f"  Time of flight = {total_time_s*1000:.3f} - {system_latency_s*1000:.3f}")
    print(f"  Time of flight = {time_of_flight_s*1000:.3f} ms")
    print()
    
    # Полное расстояние (туда и обратно)
    full_distance = sound_speed * time_of_flight_s
    
    print(f"Полное расстояние (ТУДА + ОБРАТНО):")
    print(f"  Полное расстояние = Скорость × Время")
    print(f"  Полное расстояние = {sound_speed} м/с × {time_of_flight_s:.6f} с")
    print(f"  Полное расстояние = {full_distance:.3f} м ({full_distance*100:.1f} см)")
    print()
    
    print(f"Расстояние до цели (только ТУДА):")
    print(f"  Расстояние = Полное расстояние / 2")
    print(f"  Расстояние = {full_distance:.3f} / 2")
    print(f"  Расстояние = {distance_m:.3f} м ({distance_m*100:.1f} см)")
    print()
    
    print("=" * 80)
    print(f"РЕЗУЛЬТАТ: До препятствия {distance_m:.2f} м ({distance_m*100:.0f} см)")
    print("=" * 80)

if __name__ == "__main__":
    main_test()
