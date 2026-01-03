"""
FIX для kernel panic в audio драйвере.

ПРОБЛЕМА:
- Каждый вызов play_and_record() создает новый audio stream
- При частых вызовах (GUI с 2 Hz) это вызывает:
  * Быстрое создание/уничтожение DMA буферов
  * Use-after-free в dma_pool_alloc
  * Kernel panic: "deaddeaddeaddead"

РЕШЕНИЕ:
- Использовать persistent audio stream
- Переиспользовать один stream для множества измерений
- Добавить задержки для стабилизации драйвера
"""
from __future__ import annotations

import atexit
import time
import numpy as np
import sounddevice as sd

from echopi.config import AudioDeviceConfig


class PersistentAudioStream:
    """Persistent audio stream для предотвращения kernel panic.
    
    Вместо создания нового stream при каждом измерении,
    создаем один stream и переиспользуем его.
    """
    
    def __init__(self, cfg: AudioDeviceConfig):
        self.cfg = cfg
        self.stream = None
        self._next_allowed_time = 0.0
        self._primed = False
        self._create_stream()
    
    def _create_stream(self):
        """Создать audio stream с задержкой для стабилизации."""
        if self.stream is not None:
            self._close_stream()
        
        # Задержка перед созданием stream (дает драйверу время)
        time.sleep(0.05)
        
        self.stream = sd.Stream(
            samplerate=self.cfg.sample_rate,
            blocksize=self.cfg.frames_per_buffer,
            dtype="float32",
            channels=(self.cfg.channels_rec, self.cfg.channels_play),
            device=(self.cfg.rec_device, self.cfg.play_device),
            latency=self.cfg.latency,
        )
        self.stream.start()
        
        # Задержка после создания (дает драйверу время инициализации)
        time.sleep(0.05)

        # Stream just created; prime on first use to drop stale buffers.
        self._primed = False
    
    def _close_stream(self):
        """Закрыть stream с задержкой."""
        if self.stream is not None:
            try:
                self.stream.stop()
                # Задержка перед закрытием (дает драйверу время завершить операции)
                time.sleep(0.05)
                self.stream.close()
                # Задержка после закрытия (дает драйверу время освободить ресурсы)
                time.sleep(0.05)
            except Exception as e:
                print(f"Warning: Error closing stream: {e}")
            finally:
                self.stream = None
    
    def play_and_record(
        self, 
        play_signal: np.ndarray, 
        extra_record_seconds: float = 0.1
    ) -> np.ndarray:
        """Воспроизведение и запись с использованием persistent stream.

        Встроенный pacing (rate-limit) предотвращает слишком частые вызовы,
        которые могут перегружать аудио-драйвер при экстремальных настройках.
        """
        if self.stream is None:
            self._create_stream()

        if extra_record_seconds < 0:
            raise ValueError(f"extra_record_seconds must be >= 0, got {extra_record_seconds}")

        # Rate-limit: ensure we don't start a new measurement too soon.
        now = time.monotonic()
        if now < self._next_allowed_time:
            time.sleep(self._next_allowed_time - now)

        # One-time priming: write/read one block of silence to flush old buffered samples.
        if not self._primed:
            try:
                zeros = np.zeros(self.cfg.frames_per_buffer, dtype=np.float32)
                self.stream.write(zeros.reshape(-1, 1))
                self.stream.read(self.cfg.frames_per_buffer)
            except Exception as e:
                print(f"Warning: stream priming failed: {e}")
            self._primed = True
        
        total_frames = len(play_signal) + int(extra_record_seconds * self.cfg.sample_rate)
        recorded = np.zeros(total_frames, dtype=np.float32)

        # Enforce a minimum real-time cycle based on stream blocksize.
        blocks = max(1, int(np.ceil(total_frames / self.cfg.frames_per_buffer)))
        min_cycle_s = (blocks * self.cfg.frames_per_buffer) / float(self.cfg.sample_rate)
        # Small additional cooldown to give the driver breathing room.
        cooldown_s = 0.005
        start_t = time.monotonic()
        
        try:
            idx = 0
            while idx < total_frames:
                chunk_out = play_signal[idx : idx + self.cfg.frames_per_buffer]
                if len(chunk_out) < self.cfg.frames_per_buffer:
                    chunk_out = np.pad(
                        chunk_out, 
                        (0, self.cfg.frames_per_buffer - len(chunk_out))
                    )
                
                self.stream.write(chunk_out.reshape(-1, 1))
                in_chunk, _ = self.stream.read(self.cfg.frames_per_buffer)
                end = min(idx + self.cfg.frames_per_buffer, total_frames)
                recorded[idx:end] = in_chunk[: end - idx, 0]
                idx += self.cfg.frames_per_buffer

            # If the loop returned faster than real-time (unexpected buffering), slow down.
            elapsed = time.monotonic() - start_t
            if elapsed < min_cycle_s:
                time.sleep(min_cycle_s - elapsed)

            self._next_allowed_time = time.monotonic() + cooldown_s
            return recorded
            
        except Exception as e:
            print(f"Error in play_and_record: {e}")
            # Пересоздать stream при ошибке
            self._create_stream()
            raise
    
    def close(self):
        """Закрыть stream."""
        self._close_stream()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# Глобальный persistent stream (опционально)
_global_stream = None


def get_global_stream(cfg: AudioDeviceConfig) -> PersistentAudioStream:
    """Получить глобальный persistent stream (создается один раз)."""
    global _global_stream
    if _global_stream is None:
        _global_stream = PersistentAudioStream(cfg)
    return _global_stream


def close_global_stream():
    """Закрыть глобальный stream."""
    global _global_stream
    if _global_stream is not None:
        _global_stream.close()
        _global_stream = None


atexit.register(close_global_stream)


def play_and_record_safe(
    play_signal: np.ndarray, 
    cfg: AudioDeviceConfig, 
    extra_record_seconds: float = 0.1,
    use_global: bool = True
) -> np.ndarray:
    """Безопасная версия play_and_record с persistent stream.
    
    Args:
        play_signal: Сигнал для воспроизведения
        cfg: Конфигурация audio
        extra_record_seconds: Дополнительное время записи
        use_global: Использовать глобальный stream (рекомендуется для GUI)
    
    Returns:
        Записанный сигнал
    """
    if use_global:
        stream = get_global_stream(cfg)
        return stream.play_and_record(play_signal, extra_record_seconds)
    else:
        with PersistentAudioStream(cfg) as stream:
            return stream.play_and_record(play_signal, extra_record_seconds)
