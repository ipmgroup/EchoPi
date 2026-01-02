from __future__ import annotations

import numpy as np


def cross_correlation(ref: np.ndarray, sig: np.ndarray) -> tuple[int, float, np.ndarray]:
    ref = ref.astype(np.float32)
    sig = sig.astype(np.float32)
    corr = np.correlate(sig, ref, mode="full")
    lag = int(np.argmax(corr) - (len(ref) - 1))
    peak = float(corr[lag + len(ref) - 1])
    return lag, peak, corr


def find_peaks(corr: np.ndarray, num_peaks: int = 5, min_distance: int = 100) -> list[tuple[int, float]]:
    """Найти несколько пиков в корреляции.
    
    Args:
        corr: Массив корреляции
        num_peaks: Количество пиков для поиска
        min_distance: Минимальное расстояние между пиками
        
    Returns:
        Список кортежей (индекс, значение) для каждого пика
    """
    peaks = []
    corr_copy = corr.copy()
    
    for _ in range(num_peaks):
        # Найти максимум
        idx = int(np.argmax(corr_copy))
        value = float(corr_copy[idx])
        
        if value <= 0:
            break
            
        peaks.append((idx, value))
        
        # Обнулить область вокруг найденного пика
        start = max(0, idx - min_distance)
        end = min(len(corr_copy), idx + min_distance)
        corr_copy[start:end] = 0
    
    return peaks


def parabolic_interpolate(corr: np.ndarray, index: int) -> tuple[float, float]:
    left = corr[index - 1] if index - 1 >= 0 else corr[index]
    center = corr[index]
    right = corr[index + 1] if index + 1 < len(corr) else corr[index]
    denom = 2 * (left - 2 * center + right)
    if abs(denom) < 1e-12:
        return float(index), float(center)
    delta = (left - right) / denom
    refined_index = index + delta
    refined_value = center - (left - right) * delta / 4
    return float(refined_index), float(refined_value)
