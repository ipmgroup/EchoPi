#!/usr/bin/env python3
"""Проверка АЧХ (амплитудно-частотной характеристики) системы."""

import numpy as np
from echopi.config import AudioDeviceConfig
from echopi.io.audio import play_and_record

SAMPLE_RATE = 48000
TEST_AMPLITUDE = 0.5
TONE_DURATION = 0.1  # 100 ms

cfg_audio = AudioDeviceConfig(rec_device=0, play_device=0, sample_rate=SAMPLE_RATE)

# Тестируем частоты от 500 Гц до 20 кГц
test_frequencies = [
    500, 750, 1000, 1500, 2000, 2500, 3000, 4000, 5000, 
    6000, 7000, 8000, 10000, 12000, 15000, 18000, 20000
]

print("=" * 80)
print("ПРОВЕРКА АЧХ СИСТЕМЫ")
print("=" * 80)
print(f"Sample rate: {SAMPLE_RATE} Hz")
print(f"Amplitude TX: {TEST_AMPLITUDE}")
print(f"Tone duration: {TONE_DURATION * 1000:.0f} ms")
print()

results = []

for freq in test_frequencies:
    # Генерация тона
    t = np.linspace(0, TONE_DURATION, int(TONE_DURATION * SAMPLE_RATE), endpoint=False)
    tone = TEST_AMPLITUDE * np.sin(2 * np.pi * freq * t).astype(np.float32)
    
    # Окно для сглаживания начала/конца
    window = np.hanning(len(tone))
    tone = tone * window
    
    # Запись
    try:
        recording = play_and_record(tone, cfg_audio, extra_record_seconds=0.05)
        
        # Анализ
        max_rx = np.max(np.abs(recording))
        rms_rx = np.sqrt(np.mean(recording**2))
        
        # Отношение RX/TX
        rms_tx = np.sqrt(np.mean(tone**2))
        gain_linear = rms_rx / rms_tx if rms_tx > 0 else 0
        gain_db = 20 * np.log10(gain_linear) if gain_linear > 0 else -100
        
        results.append({
            'freq': freq,
            'max_rx': max_rx,
            'rms_rx': rms_rx,
            'gain_db': gain_db
        })
        
        status = "✓"
        if max_rx >= 0.95:
            status = "⚠ CLIP"
        elif max_rx < 0.01:
            status = "⚠ WEAK"
        
        print(f"  {freq:5d} Hz: RX max={max_rx:.3f}, RMS={rms_rx:.4f}, Gain={gain_db:+6.1f} dB  {status}")
        
    except Exception as e:
        print(f"  {freq:5d} Hz: ERROR - {e}")
        results.append({
            'freq': freq,
            'max_rx': 0,
            'rms_rx': 0,
            'gain_db': -100
        })

print()
print("=" * 80)
print("АНАЛИЗ АЧХ")
print("=" * 80)

# Найти лучшую частоту
valid_results = [r for r in results if r['gain_db'] > -90]
if valid_results:
    best = max(valid_results, key=lambda x: x['gain_db'])
    worst = min(valid_results, key=lambda x: x['gain_db'])
    
    print(f"Лучшая частота: {best['freq']} Hz (gain {best['gain_db']:+.1f} dB)")
    print(f"Худшая частота: {worst['freq']} Hz (gain {worst['gain_db']:+.1f} dB)")
    print(f"Динамический диапазон: {best['gain_db'] - worst['gain_db']:.1f} dB")
    print()
    
    # Рекомендуемый диапазон (в пределах -6 dB от лучшей)
    threshold_db = best['gain_db'] - 6
    good_freqs = [r['freq'] for r in valid_results if r['gain_db'] >= threshold_db]
    
    if len(good_freqs) >= 2:
        print(f"Рекомендуемый диапазон (в пределах -6 dB от пика):")
        print(f"  {min(good_freqs)} - {max(good_freqs)} Hz")
        print()
        print(f"Частоты с хорошим откликом: {', '.join(map(str, good_freqs))} Hz")
    
    # Диапазоны для чирпа
    usable_freqs = [r['freq'] for r in valid_results if r['gain_db'] >= (best['gain_db'] - 10)]
    if len(usable_freqs) >= 2:
        print()
        print(f"Рекомендуемый диапазон для чирпа:")
        print(f"  start_freq_hz: {min(usable_freqs)}")
        print(f"  end_freq_hz: {max(usable_freqs)}")
else:
    print("⚠ Нет валидных измерений - проверьте подключение динамика/микрофона")

print()
print("=" * 80)
