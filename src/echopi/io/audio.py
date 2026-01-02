from __future__ import annotations

import contextlib
from typing import Iterable

import numpy as np
import sounddevice as sd

from echopi.config import AudioDeviceConfig


def list_devices() -> list[dict]:
    devices = sd.query_devices()
    return [dict(d) for d in devices]


def default_devices() -> dict:
    return {
        "default_input": sd.default.device[0],
        "default_output": sd.default.device[1],
    }


@contextlib.contextmanager
def audio_stream(cfg: AudioDeviceConfig):
    stream = sd.Stream(
        samplerate=cfg.sample_rate,
        blocksize=cfg.frames_per_buffer,
        dtype="float32",
        channels=(cfg.channels_rec, cfg.channels_play),
        device=(cfg.rec_device, cfg.play_device),
        latency=cfg.latency,
    )
    stream.start()
    try:
        yield stream
    finally:
        stream.stop()
        stream.close()


def play_blocking(signal: np.ndarray, cfg: AudioDeviceConfig):
    sd.play(signal, samplerate=cfg.sample_rate, device=cfg.play_device, blocking=True)


def record_blocking(duration: float, cfg: AudioDeviceConfig) -> np.ndarray:
    frames = int(duration * cfg.sample_rate)
    data = sd.rec(frames, samplerate=cfg.sample_rate, channels=cfg.channels_rec, device=cfg.rec_device, dtype="float32")
    sd.wait()
    return data[:, 0]


def monitor_microphone(cfg: AudioDeviceConfig, callback):
    def _callback(indata, frames, time_info, status):  # noqa: ANN001, ANN202
        if status:
            callback(None, str(status))
            return
        callback(indata[:, 0].copy(), None)

    with sd.InputStream(
        channels=cfg.channels_rec,
        samplerate=cfg.sample_rate,
        blocksize=cfg.frames_per_buffer,
        device=cfg.rec_device,
        dtype="float32",
        callback=_callback,
    ):
        sd.sleep(int(1e9))


def play_and_record(play_signal: np.ndarray, cfg: AudioDeviceConfig, extra_record_seconds: float = 0.1) -> np.ndarray:
    """Воспроизведение и запись через DUPLEX stream с параллельной работой.
    
    Использует один duplex stream для точной синхронизации между
    воспроизведением и записью.
    """
    import sounddevice as sd
    
    # Длительность записи = длительность сигнала + extra time
    record_frames = len(play_signal) + int(extra_record_seconds * cfg.sample_rate)
    recorded = np.zeros(record_frames, dtype=np.float32)
    
    # Создаем duplex stream (одновременно input и output)
    with sd.Stream(
        samplerate=cfg.sample_rate,
        blocksize=cfg.frames_per_buffer,
        dtype='float32',
        channels=(cfg.channels_rec, cfg.channels_play),
        device=(cfg.rec_device, cfg.play_device),
        latency=cfg.latency,
    ) as stream:
        
        idx = 0
        while idx < record_frames:
            # Подготовка данных для воспроизведения
            chunk_size = min(cfg.frames_per_buffer, len(play_signal) - idx)
            if chunk_size > 0 and idx < len(play_signal):
                chunk_out = play_signal[idx:idx + chunk_size]
                if len(chunk_out) < cfg.frames_per_buffer:
                    chunk_out = np.pad(chunk_out, (0, cfg.frames_per_buffer - len(chunk_out)))
            else:
                # После окончания сигнала продолжаем записывать тишину
                chunk_out = np.zeros(cfg.frames_per_buffer, dtype=np.float32)
            
            # ПАРАЛЛЕЛЬНАЯ работа: одновременно write и read
            stream.write(chunk_out.reshape(-1, 1))
            in_chunk, _ = stream.read(cfg.frames_per_buffer)
            
            # Сохранение записанных данных
            end = min(idx + cfg.frames_per_buffer, record_frames)
            recorded[idx:end] = in_chunk[:end - idx, 0]
            idx += cfg.frames_per_buffer
    
    return recorded


def rms_level(samples: Iterable[float]) -> float:
    arr = np.asarray(list(samples), dtype=np.float32)
    if arr.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(arr ** 2)))
