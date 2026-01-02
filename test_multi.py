#!/usr/bin/env python3
"""Многократное измерение для усреднения."""

import sys
sys.path.insert(0, '/home/pi/src/EchoPi5/src')

from echopi.config import AudioDeviceConfig, ChirpConfig
from echopi import settings
from echopi.utils.distance import measure_distance
import time

def main():
    cfg_audio = AudioDeviceConfig(sample_rate=96000, frames_per_buffer=1024)
    cfg_chirp = ChirpConfig(start_freq=2000, end_freq=20000, duration=0.05, amplitude=0.8, fade_fraction=0.0)
    sys_latency = settings.get_system_latency()
    
    n_measurements = 10
    distances = []
    
    print(f"Выполняем {n_measurements} измерений...")
    for i in range(n_measurements):
        result = measure_distance(cfg_audio, cfg_chirp, medium='air', system_latency_s=sys_latency, reference_fade=0.05)
        dist = result['distance_m']
        distances.append(dist)
        print(f"  {i+1}. {dist:.3f} m ({dist*100:.0f} cm)")
        time.sleep(0.2)
    
    print()
    print("="*60)
    print(f"Минимум: {min(distances):.2f} м ({min(distances)*100:.0f} см)")
    print(f"Максимум: {max(distances):.2f} м ({max(distances)*100:.0f} см)")
    print(f"Среднее: {sum(distances)/len(distances):.2f} м ({sum(distances)/len(distances)*100:.0f} см)")
    print("="*60)

if __name__ == "__main__":
    main()
