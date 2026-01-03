#!/usr/bin/env python3
"""Измерение АЧХ микрофона на разных уровнях выходной мощности.

Проверяет, как меняется частотная характеристика при разной amplitude.
"""

import sys
sys.path.insert(0, "/home/pi/src/EchoPi5/src")

import numpy as np
from echopi.config import AudioDeviceConfig
from echopi.io.audio import play_and_record
import argparse


def measure_frequency_response_at_power(
    frequencies: list[float],
    amplitude: float,
    tone_duration: float,
    cfg_audio: AudioDeviceConfig,
) -> dict[float, float]:
    """Измерить АЧХ при заданной amplitude.
    
    Returns:
        dict: {frequency_hz: peak_amplitude}
    """
    results = {}
    
    for freq in frequencies:
        # Генерация тона
        t = np.linspace(0, tone_duration, int(cfg_audio.sample_rate * tone_duration), endpoint=False)
        tone = amplitude * np.sin(2 * np.pi * freq * t).astype(np.float32)
        
        # Запись
        recording = play_and_record(tone, cfg_audio, extra_record_seconds=0.05)
        
        # Измерение амплитуды записанного сигнала
        peak = float(np.max(np.abs(recording)))
        rms = float(np.sqrt(np.mean(recording**2)))
        
        results[freq] = peak
    
    return results


def normalize_response(response: dict[float, float], reference_freq: float = 1000.0) -> dict[float, float]:
    """Нормализовать АЧХ относительно опорной частоты (в дБ)."""
    ref_value = response.get(reference_freq)
    if ref_value is None or ref_value == 0:
        ref_value = max(response.values())
    
    normalized = {}
    for freq, value in response.items():
        if value > 0:
            db = 20 * np.log10(value / ref_value)
        else:
            db = -100.0  # Very low
        normalized[freq] = db
    
    return normalized


def main():
    parser = argparse.ArgumentParser(description="Измерение АЧХ микрофона при разных уровнях мощности")
    parser.add_argument("--powers", type=str, default="0.2,0.4,0.6,0.8,1.0", help="Список amplitude через запятую")
    parser.add_argument("--freq-start", type=float, default=500, help="Начальная частота (Hz)")
    parser.add_argument("--freq-end", type=float, default=15000, help="Конечная частота (Hz)")
    parser.add_argument("--freq-step", type=float, default=1000, help="Шаг частоты (Hz)")
    parser.add_argument("--tone-duration", type=float, default=0.05, help="Длительность тона (сек)")
    parser.add_argument("--reference-freq", type=float, default=1000, help="Опорная частота для нормализации (Hz)")
    
    args = parser.parse_args()
    
    # Парсинг списка amplitude
    amplitudes = [float(x.strip()) for x in args.powers.split(",")]
    
    # Генерация списка частот
    frequencies = []
    freq = args.freq_start
    while freq <= args.freq_end:
        frequencies.append(freq)
        freq += args.freq_step
    
    print("="*80)
    print("Измерение АЧХ микрофона при разных уровнях выходной мощности")
    print("="*80)
    print(f"Частоты: {args.freq_start:.0f} - {args.freq_end:.0f} Hz (шаг {args.freq_step:.0f} Hz)")
    print(f"Levels: {amplitudes}")
    print(f"Длительность тона: {args.tone_duration*1000:.0f} ms")
    print(f"Опорная частота: {args.reference_freq:.0f} Hz")
    print(f"Всего измерений: {len(frequencies)} частот × {len(amplitudes)} уровней = {len(frequencies)*len(amplitudes)}")
    print()
    
    cfg_audio = AudioDeviceConfig()
    
    # Словарь для хранения результатов: {amplitude: {freq: peak}}
    all_results = {}
    
    # Измерения для каждой amplitude
    for amp_idx, amplitude in enumerate(amplitudes, 1):
        print(f"[{amp_idx}/{len(amplitudes)}] Измерение при amplitude={amplitude:.2f}...")
        response = measure_frequency_response_at_power(frequencies, amplitude, args.tone_duration, cfg_audio)
        all_results[amplitude] = response
        
        # Краткая статистика
        peak_freq = max(response, key=response.get)
        peak_val = response[peak_freq]
        min_freq = min(response, key=response.get)
        min_val = response[min_freq]
        avg_val = np.mean(list(response.values()))
        
        print(f"  Пик: {peak_freq:.0f} Hz = {peak_val:.3f}")
        print(f"  Мин: {min_freq:.0f} Hz = {min_val:.3f}")
        print(f"  Среднее: {avg_val:.3f}")
        print()
    
    # Нормализация относительно опорной частоты
    print("="*80)
    print("АЧХ в дБ (относительно опорной частоты)")
    print("="*80)
    print()
    
    normalized_results = {}
    for amplitude in amplitudes:
        normalized_results[amplitude] = normalize_response(all_results[amplitude], args.reference_freq)
    
    # Вывод таблицы
    print(f"{'Freq (Hz)':>10} | ", end="")
    for amplitude in amplitudes:
        print(f"amp={amplitude:.2f} (dB) | ", end="")
    print()
    print("-" * 80)
    
    for freq in frequencies:
        print(f"{freq:>10.0f} | ", end="")
        for amplitude in amplitudes:
            db = normalized_results[amplitude][freq]
            print(f"{db:>14.1f} | ", end="")
        print()
    
    print()
    print("="*80)
    print("АНАЛИЗ ЗАВИСИМОСТИ ОТ МОЩНОСТИ")
    print("="*80)
    print()
    
    # Проверка постоянства АЧХ
    for freq in frequencies:
        values_db = [normalized_results[amp][freq] for amp in amplitudes]
        std_db = np.std(values_db)
        mean_db = np.mean(values_db)
        
        if std_db > 2.0:
            status = "⚠ ВАРЬИРУЕТСЯ"
        elif std_db > 1.0:
            status = "ℹ слабая зависимость"
        else:
            status = "✓ стабильно"
        
        print(f"{freq:>6.0f} Hz: {mean_db:+6.1f} dB ± {std_db:4.1f} dB  [{status}]")
    
    print()
    
    # Общий вывод
    all_stds = []
    for freq in frequencies:
        values_db = [normalized_results[amp][freq] for amp in amplitudes]
        all_stds.append(np.std(values_db))
    
    max_std = max(all_stds)
    avg_std = np.mean(all_stds)
    
    print("="*80)
    print("ВЫВОД")
    print("="*80)
    print(f"Средняя вариация АЧХ: ±{avg_std:.2f} dB")
    print(f"Максимальная вариация: ±{max_std:.2f} dB")
    print()
    
    if max_std < 1.0:
        print("✓ АЧХ микрофона НЕ ЗАВИСИТ от выходной мощности (< 1 dB)")
        print("  Можно использовать любую amplitude без искажения частотной характеристики")
    elif max_std < 3.0:
        print("ℹ АЧХ микрофона СЛАБО ЗАВИСИТ от выходной мощности (1-3 dB)")
        print("  Рекомендуется использовать постоянную amplitude для точных измерений")
    else:
        print("⚠ АЧХ микрофона СУЩЕСТВЕННО ЗАВИСИТ от выходной мощности (> 3 dB)")
        print("  Возможна нелинейность или AGC. Калибровка необходима для каждой amplitude")
    
    # Проверка на AGC
    print()
    print("Проверка абсолютных уровней:")
    ref_freq = args.reference_freq
    ref_levels = [all_results[amp][ref_freq] for amp in amplitudes]
    
    print(f"Amplitude → Записанный пик на {ref_freq:.0f} Hz:")
    for amp, level in zip(amplitudes, ref_levels):
        ratio = level / amp if amp > 0 else 0
        print(f"  {amp:.2f} → {level:.3f} (отношение {ratio:.2f})")
    
    # Линейность
    expected_ratio = ref_levels[0] / amplitudes[0] if amplitudes[0] > 0 else 1.0
    deviations = []
    for amp, level in zip(amplitudes, ref_levels):
        expected = amp * expected_ratio
        deviation_pct = abs(level - expected) / expected * 100 if expected > 0 else 0
        deviations.append(deviation_pct)
    
    avg_deviation = np.mean(deviations)
    print()
    
    if avg_deviation < 5:
        print(f"✓ Линейность: {avg_deviation:.1f}% - микрофон/звуковая карта работают линейно")
    elif avg_deviation < 15:
        print(f"ℹ Линейность: {avg_deviation:.1f}% - небольшая нелинейность или AGC")
    else:
        print(f"⚠ Линейность: {avg_deviation:.1f}% - сильная нелинейность или AGC активен")
        print("  Записанный уровень не зависит от выходной amplitude")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
