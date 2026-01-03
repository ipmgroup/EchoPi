#!/usr/bin/env python3
"""Калибровка амплитуды выходного сигнала для предотвращения насыщения микрофона.

Использование:
    python calibrate_amplitude.py [--target 0.8] [--save]

Подбирает оптимальную amplitude (0.0-1.0) так, чтобы:
- Микрофон не клипировал (max < 1.0)
- Сигнал был достаточно сильным для хорошего SNR
"""

import sys
sys.path.insert(0, "/home/pi/src/EchoPi5/src")

import argparse
import numpy as np
from echopi.config import ChirpConfig, AudioDeviceConfig
from echopi.dsp.chirp import generate_chirp
from echopi.io.audio import play_and_record
from echopi import settings


def test_amplitude(amplitude: float, cfg_audio: AudioDeviceConfig, cfg_chirp: ChirpConfig) -> dict:
    """Проверить одну amplitude и вернуть статистику записи."""
    cfg_test = ChirpConfig(
        start_freq=cfg_chirp.start_freq,
        end_freq=cfg_chirp.end_freq,
        duration=cfg_chirp.duration,
        amplitude=amplitude,
        fade_fraction=cfg_chirp.fade_fraction,
    )
    
    chirp = generate_chirp(cfg_test, sample_rate=cfg_audio.sample_rate)
    recording = play_and_record(chirp, cfg_audio, extra_record_seconds=0.1)
    
    max_val = float(np.max(np.abs(recording)))
    rms = float(np.sqrt(np.mean(recording**2)))
    clipped = max_val >= 0.99
    
    return {
        "amplitude": amplitude,
        "max": max_val,
        "rms": rms,
        "clipped": clipped,
    }


def binary_search_amplitude(
    target_max: float,
    cfg_audio: AudioDeviceConfig,
    cfg_chirp: ChirpConfig,
    min_amp: float = 0.1,
    max_amp: float = 1.0,
    tolerance: float = 0.05,
    max_iterations: int = 10,
) -> dict:
    """Бинарный поиск оптимальной amplitude."""
    print(f"Цель: максимум записи = {target_max:.2f}")
    print(f"Диапазон поиска: {min_amp:.2f} - {max_amp:.2f}")
    print(f"Допуск: ±{tolerance:.2f}")
    print()
    
    best_result = None
    
    for iteration in range(1, max_iterations + 1):
        mid_amp = (min_amp + max_amp) / 2.0
        
        print(f"[{iteration}/{max_iterations}] Тест amplitude={mid_amp:.3f}...", end=" ", flush=True)
        result = test_amplitude(mid_amp, cfg_audio, cfg_chirp)
        
        max_val = result["max"]
        clipped = result["clipped"]
        
        status = "КЛИП!" if clipped else "OK"
        print(f"max={max_val:.3f}, rms={result['rms']:.3f} [{status}]")
        
        # Сохранить лучший результат
        if not clipped and (best_result is None or abs(max_val - target_max) < abs(best_result["max"] - target_max)):
            best_result = result
        
        # Проверка сходимости
        if abs(max_val - target_max) < tolerance:
            print()
            print(f"✓ Сошлось за {iteration} итераций")
            return result
        
        # Корректировка диапазона
        if max_val > target_max or clipped:
            # Слишком громко, уменьшить
            max_amp = mid_amp
        else:
            # Слишком тихо, увеличить
            min_amp = mid_amp
        
        # Проверка на слишком узкий диапазон
        if (max_amp - min_amp) < 0.01:
            print()
            print(f"⚠ Диапазон слишком узкий: [{min_amp:.3f}, {max_amp:.3f}]")
            break
    
    print()
    if best_result:
        print(f"✓ Лучший результат после {max_iterations} итераций")
        return best_result
    else:
        print(f"✗ Не удалось найти подходящую amplitude")
        return result


def linear_scan_amplitude(
    target_max: float,
    cfg_audio: AudioDeviceConfig,
    cfg_chirp: ChirpConfig,
    start_amp: float = 0.2,
    max_amp: float = 1.0,
    step: float = 0.1,
) -> dict:
    """Линейное сканирование amplitude от малых к большим значениям."""
    print(f"Цель: максимум записи = {target_max:.2f}")
    print(f"Сканирование: {start_amp:.2f} → {max_amp:.2f}, шаг {step:.2f}")
    print()
    
    amp = start_amp
    results = []
    
    while amp <= max_amp:
        print(f"Тест amplitude={amp:.2f}...", end=" ", flush=True)
        result = test_amplitude(amp, cfg_audio, cfg_chirp)
        results.append(result)
        
        max_val = result["max"]
        clipped = result["clipped"]
        status = "КЛИП!" if clipped else "OK"
        
        print(f"max={max_val:.3f}, rms={result['rms']:.3f} [{status}]")
        
        # Если начал клипировать - выбрать предыдущее значение
        if clipped:
            if len(results) > 1:
                best = results[-2]  # Предыдущий результат без клипирования
                print()
                print(f"⚠ Клипирование при amplitude={amp:.2f}")
                print(f"✓ Выбрано безопасное значение: amplitude={best['amplitude']:.2f}")
                return best
            else:
                print()
                print(f"✗ Клипирование уже при минимальной amplitude={amp:.2f}!")
                print("  Попробуйте уменьшить start_amp или увеличить расстояние микрофон-динамик")
                return result
        
        # Если достигли цели
        if max_val >= target_max:
            print()
            print(f"✓ Достигнута цель при amplitude={amp:.2f}")
            return result
        
        amp += step
    
    # Достигнут максимум без клипирования
    best = results[-1]
    print()
    print(f"✓ Максимальная безопасная amplitude={best['amplitude']:.2f} (max={best['max']:.3f})")
    return best


def main():
    parser = argparse.ArgumentParser(description="Калибровка амплитуды динамика для предотвращения насыщения микрофона")
    parser.add_argument("--target", type=float, default=0.8, help="Целевой максимум записи (0.0-1.0, рекомендуется 0.7-0.85)")
    parser.add_argument("--method", choices=["binary", "linear"], default="linear", help="Метод поиска (binary=быстрый, linear=безопасный)")
    parser.add_argument("--save", action="store_true", help="Сохранить результат в конфигурацию")
    parser.add_argument("--start-freq", type=float, default=None, help="Начальная частота (Hz, default: из config)")
    parser.add_argument("--end-freq", type=float, default=None, help="Конечная частота (Hz, default: из config)")
    parser.add_argument("--duration", type=float, default=0.05, help="Длительность чирпа (сек)")
    
    args = parser.parse_args()
    
    if args.target <= 0 or args.target >= 1.0:
        print(f"Ошибка: target должен быть в диапазоне (0.0, 1.0), получено {args.target}")
        return 1
    
    # Загрузить параметры из конфигурации
    start_freq = args.start_freq if args.start_freq is not None else settings.get_start_freq()
    end_freq = args.end_freq if args.end_freq is not None else settings.get_end_freq()
    
    print("="*60)
    print("Калибровка амплитуды выходного сигнала")
    print("="*60)
    print(f"Частоты: {start_freq:.0f} - {end_freq:.0f} Hz")
    print(f"Длительность: {args.duration*1000:.0f} ms")
    print(f"Метод: {args.method}")
    print()
    
    cfg_audio = AudioDeviceConfig()
    cfg_chirp = ChirpConfig(
        start_freq=start_freq,
        end_freq=end_freq,
        duration=args.duration,
        amplitude=0.5,  # Начальное значение, будет подобрано
        fade_fraction=0.0,
    )
    
    # Выполнить калибровку
    if args.method == "binary":
        result = binary_search_amplitude(args.target, cfg_audio, cfg_chirp)
    else:  # linear
        result = linear_scan_amplitude(args.target, cfg_audio, cfg_chirp, start_amp=0.1, step=0.1)
    
    # Вывести результат
    print()
    print("="*60)
    print("РЕЗУЛЬТАТ КАЛИБРОВКИ")
    print("="*60)
    print(f"Оптимальная amplitude: {result['amplitude']:.3f}")
    print(f"Максимум записи:       {result['max']:.3f}")
    print(f"RMS записи:            {result['rms']:.3f}")
    print(f"Клипирование:          {'ДА (нестабильно!)' if result['clipped'] else 'НЕТ'}")
    print()
    
    # Рекомендация
    if result['clipped']:
        print("⚠ ВНИМАНИЕ: микрофон клипирует при этой amplitude!")
        print("  Рекомендуется уменьшить значение или увеличить расстояние")
    elif result['max'] < 0.3:
        print("⚠ ВНИМАНИЕ: сигнал очень слабый (max < 0.3)")
        print("  Рекомендуется увеличить amplitude или уменьшить расстояние")
    elif result['max'] < args.target * 0.8:
        print(f"ℹ Достигнуто {result['max']:.3f} из целевых {args.target:.2f}")
        print("  Можно попробовать увеличить amplitude для лучшего SNR")
    else:
        print("✓ Калибровка успешна!")
    
    # Сохранить в конфигурацию
    if args.save:
        print()
        old_amp = settings.get_amplitude()
        success = settings.save_settings({"amplitude": result['amplitude']})
        if success:
            print(f"✓ Amplitude сохранена в конфигурацию: {old_amp:.2f} → {result['amplitude']:.3f}")
            print(f"  Файл: {settings.get_config_file_path()}")
        else:
            print("✗ Не удалось сохранить в конфигурацию")
            return 1
    else:
        print()
        print("Для сохранения в конфигурацию запустите с флагом --save")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
