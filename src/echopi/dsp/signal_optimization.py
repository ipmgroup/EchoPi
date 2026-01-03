"""Signal optimization module for chirp parameter calculation.

This module provides functions to optimize chirp parameters (duration, bandwidth)
based on physical propagation models and target requirements (distance, SNR, resolution).

Формулы основаны на:
- Теории согласованной фильтрации (matched filter)
- Физической модели распространения звука
- Критерии Рэлея для разрешающей способности
"""

from __future__ import annotations

import numpy as np


def optimize_chirp_duration(
    distance_m: float,
    target_snr_db: float,
    bandwidth_hz: float,
    speed_of_sound: float = 343.0,
    absorption_coeff: float = 0.1,
    ambient_noise_db: float = -60.0
) -> tuple[float, float, float]:
    """Оптимизация длительности чирпа для заданной дистанции и целевого SNR.
    
    Физическая модель учитывает:
    1. Потери при распространении (сферическое расхождение)
    2. Поглощение в воздухе
    3. Processing gain от согласованной фильтрации
    
    ФОРМУЛЫ:
    ========
    
    1. Потери сигнала (туда-обратно):
       Loss_spreading = 40 * log10(2 * distance)  [дБ]
       Loss_absorption = α * 2 * distance          [дБ]
       Loss_total = Loss_spreading + Loss_absorption
    
    2. Требуемый processing gain для достижения целевого SNR:
       PG_required = SNR_target + Loss_total
    
    3. Processing gain от согласованной фильтрации:
       PG = 10 * log10(T_chirp * BW)  [дБ]
       где T_chirp - длительность чирпа [с]
           BW - полоса частот [Гц]
    
    4. Решение для длительности чирпа:
       T_chirp = 10^(PG_required/10) / BW  [с]
    
    5. Разрешение по дальности (критерий Рэлея):
       Δr = c / (2 * BW)  [м]
       коэффициент 2 учитывает путь туда-обратно
    
    Args:
        distance_m: Дистанция до цели в метрах (в одну сторону)
        target_snr_db: Целевой SNR в дБ
        bandwidth_hz: Полоса частот чирпа в Гц (f_max - f_min)
        speed_of_sound: Скорость звука в м/с (по умолчанию: 343 м/с для воздуха при 20°C)
        absorption_coeff: Коэффициент поглощения в дБ/м (по умолчанию: 0.1 для 10 кГц)
        ambient_noise_db: Уровень окружающего шума в дБFS
    
    Returns:
        Кортеж (T_chirp, estimated_snr, distance_resolution):
        - T_chirp: Оптимальная длительность чирпа в секундах
        - estimated_snr: Оценочный SNR на заданной дистанции в дБ
        - distance_resolution: Разрешение по дальности в метрах
    
    Example:
        >>> T_chirp, snr, resolution = optimize_chirp_duration(
        ...     distance_m=2.0,
        ...     target_snr_db=15.0,
        ...     bandwidth_hz=9000.0
        ... )
        >>> print(f"Длительность чирпа: {T_chirp*1000:.2f} мс")
        >>> print(f"Ожидаемый SNR: {snr:.1f} дБ")
        >>> print(f"Разрешение: {resolution*1000:.1f} мм")
    """
    # Дистанция туда-обратно для эхо-сигнала
    round_trip_distance = 2.0 * distance_m
    
    # ФОРМУЛА 1: Потери при распространении (сферическое расхождение)
    # Для одного направления: L = 20*log10(r)
    # Для туда-обратно: L = 40*log10(r)
    # Нормализовано к 1 метру
    spreading_loss_db = 40.0 * np.log10(round_trip_distance / 1.0)
    
    # ФОРМУЛА 2: Атмосферное поглощение
    # L_abs = α * d, где α - коэффициент поглощения [дБ/м]
    # Типичные значения на ~10 кГц: 0.1 дБ/м
    absorption_loss_db = absorption_coeff * round_trip_distance
    
    # ФОРМУЛА 3: Суммарные потери
    total_loss_db = spreading_loss_db + absorption_loss_db
    
    # ФОРМУЛА 4: Требуемый processing gain
    # SNR_out = SNR_in + PG
    # PG_required = SNR_target - SNR_in
    # Предполагаем, что мощность передачи = 0 дБFS
    received_signal_db = 0 - total_loss_db
    snr_in_db = received_signal_db - ambient_noise_db
    required_gain_db = target_snr_db - snr_in_db
    
    # ФОРМУЛА 5: Processing gain согласованного фильтра
    # PG = 10 * log10(TBP), где TBP = T * BW
    # Отсюда: T = 10^(PG/10) / BW
    required_tbp = 10 ** (required_gain_db / 10.0)
    T_chirp = required_tbp / bandwidth_hz
    
    # Практические ограничения
    min_duration_s = 0.001  # 1 мс минимум (аппаратные ограничения)
    max_duration_s = 0.200  # 200 мс максимум (ограничение реального времени)
    T_chirp = np.clip(T_chirp, min_duration_s, max_duration_s)
    
    # ФОРМУЛА 6: Фактический SNR с оптимальной длительностью
    actual_tbp = T_chirp * bandwidth_hz
    actual_processing_gain_db = 10 * np.log10(actual_tbp)
    estimated_snr = snr_in_db + actual_processing_gain_db
    
    # ФОРМУЛА 7: Разрешение по дальности (критерий Рэлея)
    # Δr = c / (2 * BW)
    # Коэффициент 2 учитывает путь туда-обратно
    time_resolution_s = 1.0 / bandwidth_hz
    distance_resolution = (time_resolution_s * speed_of_sound) / 2.0
    
    return T_chirp, estimated_snr, distance_resolution


def calculate_correlation_threshold(
    chirp_duration_s: float,
    bandwidth_hz: float,
    sample_rate: float,
    window_alpha: float = 0.25
) -> tuple[float, float, float]:
    """Расчет адаптивного порога корреляции на основе свойств сигнала.
    
    Комплексная формула учитывает:
    - Длительность чирпа (больше = лучше SNR, шире главный лепесток)
    - Полосу частот (шире = уже главный лепесток, лучше разрешение)
    - Тип окна (через параметр alpha, влияет на подавление боковых лепестков)
    - Частоту дискретизации (влияет на дискретное временное разрешение)
    
    ФОРМУЛЫ:
    ========
    
    1. Временное разрешение от теории согласованного фильтра:
       Δt ≈ 1 / BW  [с]
    
    2. Ширина главного лепестка с оконной функцией:
       W_mainlobe = Δt * (1 + α/2)  [с]
       где α - параметр окна Tukey (доля затухания)
    
    3. Processing gain (произведение время-полоса):
       TBP = T_chirp * BW  [безразмерная]
       PG = 10 * log10(TBP)  [дБ]
    
    4. Оценка уровня шума для согласованного фильтра:
       σ_noise = 1 / sqrt(TBP)  [нормализованная]
    
    5. Порог обнаружения (6 дБ запас над шумом):
       threshold = σ_noise * 10^(6/20) = 2 * σ_noise
       (дает ~99.7% вероятность обнаружения, эквивалент 3-σ)
    
    Args:
        chirp_duration_s: Длительность чирпа в секундах
        bandwidth_hz: Полоса частот чирпа в Гц
        sample_rate: Частота дискретизации в Гц
        window_alpha: Параметр α окна Tukey (доля затухания, от 0 до 1)
    
    Returns:
        Кортеж (threshold, mainlobe_width_samples, processing_gain_db):
        - threshold: Нормализованный порог корреляции (от 0 до 1)
        - mainlobe_width_samples: Ожидаемая ширина главного лепестка в отсчетах
        - processing_gain_db: Processing gain в дБ
    
    Example:
        >>> threshold, width, gain = calculate_correlation_threshold(
        ...     chirp_duration_s=0.05,
        ...     bandwidth_hz=9000.0,
        ...     sample_rate=48000.0,
        ...     window_alpha=0.25
        ... )
        >>> print(f"Порог: {threshold:.4f}")
        >>> print(f"Ширина главного лепестка: {width:.1f} отсчетов")
        >>> print(f"Processing gain: {gain:.1f} дБ")
    """
    # ФОРМУЛА 1: Теоретическое временное разрешение
    time_resolution_s = 1.0 / bandwidth_hz
    
    # ФОРМУЛА 2: Ширина главного лепестка с учетом окна
    # Окно Tukey расширяет главный лепесток: коэффициент = 1 + α/2
    # Для α=0.25: коэффициент ≈ 1.125
    window_broadening = 1.0 + window_alpha * 0.5
    mainlobe_width_s = time_resolution_s * window_broadening
    mainlobe_width_samples = mainlobe_width_s * sample_rate
    
    # ФОРМУЛА 3: Processing gain от произведения время-полоса
    # TBP = T_chirp * BW (безразмерная величина)
    # Processing Gain = 10*log10(TBP) [дБ]
    time_bandwidth_product = chirp_duration_s * bandwidth_hz
    processing_gain_db = 10.0 * np.log10(time_bandwidth_product)
    
    # ФОРМУЛА 4: Отношение пик/боковые лепестки от окна
    # Окно Tukey с α=0.25: уровень боковых лепестков ≈ -40 дБ
    sidelobe_suppression_db = 40.0 * window_alpha / 0.25
    
    # ФОРМУЛА 5: Оценка уровня шума для согласованного фильтра
    # Для белого шума, улучшение SNR согласованного фильтра = TBP
    # Стандартное отклонение шума: σ = 1/sqrt(TBP)
    noise_floor = 1.0 / np.sqrt(time_bandwidth_product)
    
    # ФОРМУЛА 6: Порог обнаружения с запасом
    # Используем 6 дБ (коэффициент 2) над уровнем шума
    # Это дает ~99.7% вероятность обнаружения (эквивалент 3-σ)
    detection_margin_db = 6.0
    detection_margin_linear = 10 ** (detection_margin_db / 20.0)
    
    # Итоговый порог (нормализован к пику корреляции = 1.0)
    threshold = noise_floor * detection_margin_linear
    
    return threshold, mainlobe_width_samples, processing_gain_db


def calculate_optimal_bandwidth(
    target_resolution_m: float,
    speed_of_sound: float = 343.0
) -> float:
    """Расчет оптимальной полосы частот для желаемого разрешения по дальности.
    
    ФОРМУЛА:
    ========
    Из критерия Рэлея для разрешения по дальности:
    
    Δr = c / (2 * BW)
    
    Отсюда:
    BW = c / (2 * Δr)  [Гц]
    
    где:
    - Δr - разрешение по дальности [м]
    - c - скорость звука [м/с]
    - BW - полоса частот [Гц]
    - коэффициент 2 учитывает путь туда-обратно
    
    Args:
        target_resolution_m: Желаемое разрешение по дальности в метрах
        speed_of_sound: Скорость звука в м/с
    
    Returns:
        Требуемая полоса частот в Гц
    
    Example:
        >>> bw = calculate_optimal_bandwidth(
        ...     target_resolution_m=0.02  # 2 см разрешение
        ... )
        >>> print(f"Требуемая полоса: {bw/1000:.1f} кГц")
    """
    # ФОРМУЛА: BW = c / (2 * Δr)
    bandwidth_hz = speed_of_sound / (2.0 * target_resolution_m)
    return bandwidth_hz


def calculate_max_unambiguous_distance(
    chirp_duration_s: float,
    speed_of_sound: float = 343.0
) -> float:
    """Расчет максимальной однозначной дистанции измерения.
    
    ФОРМУЛА:
    ========
    Максимальная однозначная дистанция определяется временем между импульсами:
    
    d_max = (c * T_chirp) / 2  [м]
    
    где:
    - c - скорость звука [м/с]
    - T_chirp - длительность чирпа (период повторения) [с]
    - коэффициент 2 учитывает путь туда-обратно
    
    Альтернативная форма через PRF (частоту повторения импульсов):
    PRF = 1 / T_chirp  [Гц]
    d_max = c / (2 * PRF)  [м]
    
    Args:
        chirp_duration_s: Длительность чирпа в секундах
        speed_of_sound: Скорость звука в м/с
    
    Returns:
        Максимальная однозначная дистанция в метрах
    
    Example:
        >>> # Для чирпа 50 мс
        >>> d_max = calculate_max_unambiguous_distance(0.05)
        >>> print(f"Макс. дистанция: {d_max:.1f} м")
    """
    # ФОРМУЛА: d_max = (c * T) / 2
    max_distance_m = (speed_of_sound * chirp_duration_s) / 2.0
    return max_distance_m


def calculate_processing_gain(
    chirp_duration_s: float,
    bandwidth_hz: float
) -> tuple[float, float]:
    """Расчет processing gain согласованного фильтра.
    
    ФОРМУЛЫ:
    ========
    
    1. Произведение время-полоса (Time-Bandwidth Product):
       TBP = T_chirp * BW  [безразмерная]
    
    2. Processing gain в дБ:
       PG = 10 * log10(TBP)  [дБ]
    
    3. Processing gain в линейной шкале:
       PG_linear = TBP  [безразмерная]
    
    Физический смысл:
    - TBP показывает, во сколько раз улучшается SNR после согласованной фильтрации
    - Большее TBP = лучшее обнаружение слабых сигналов на фоне шума
    
    Args:
        chirp_duration_s: Длительность чирпа в секундах
        bandwidth_hz: Полоса частот в Гц
    
    Returns:
        Кортеж (tbp, processing_gain_db):
        - tbp: Произведение время-полоса (безразмерная)
        - processing_gain_db: Processing gain в дБ
    
    Example:
        >>> tbp, pg_db = calculate_processing_gain(0.05, 9000.0)
        >>> print(f"TBP: {tbp:.0f}")
        >>> print(f"Processing gain: {pg_db:.1f} дБ")
    """
    # ФОРМУЛА 1: TBP = T * BW
    time_bandwidth_product = chirp_duration_s * bandwidth_hz
    
    # ФОРМУЛА 2: PG = 10 * log10(TBP)
    processing_gain_db = 10.0 * np.log10(time_bandwidth_product)
    
    return time_bandwidth_product, processing_gain_db
