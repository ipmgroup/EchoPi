from __future__ import annotations

import numpy as np


def cross_correlation(ref: np.ndarray, sig: np.ndarray) -> tuple[int, float, np.ndarray]:
    """Cross-correlation between reference signal and recorded signal using FFT.
    
    FFT-based correlation is more accurate and faster for large signals.
    
    Returns:
        lag: Sample index in corr array where peak is found
        peak: Peak correlation value
        corr: Full correlation array
    """
    ref = ref.astype(np.float32)
    sig = sig.astype(np.float32)
    
    # FFT-based correlation: IFFT(FFT(sig) * conj(FFT(ref)))
    n = len(sig) + len(ref) - 1
    n_fft = 2 ** int(np.ceil(np.log2(n)))
    
    # FFT of both signals
    fft_ref = np.fft.fft(ref, n=n_fft)
    fft_sig = np.fft.fft(sig, n=n_fft)
    
    # Cross-correlation in frequency domain
    fft_corr = fft_sig * np.conj(fft_ref)
    
    # IFFT to get correlation in time domain
    corr_full = np.fft.ifft(fft_corr).real
    corr = corr_full[:n]
    
    # Find peak index
    peak_idx = int(np.argmax(corr))
    peak = float(corr[peak_idx])
    
    return peak_idx, peak, corr


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
