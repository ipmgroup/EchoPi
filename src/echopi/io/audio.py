from __future__ import annotations

import atexit
import contextlib
import time
import threading
from typing import Iterable

import numpy as np
import sounddevice as sd

from echopi.config import AudioDeviceConfig


def _cfg_signature(cfg: AudioDeviceConfig) -> tuple:
    return (
        cfg.sample_rate,
        cfg.frames_per_buffer,
        cfg.channels_rec,
        cfg.channels_play,
        cfg.rec_device,
        cfg.play_device,
        cfg.latency,
    )


class PersistentAudioStream:
    """Persistent duplex stream for stable repeated play+record calls.

    Provides built-in priming (flush) and pacing (rate-limit) to reduce
    driver overload risks under extreme measurement settings.
    """

    def __init__(self, cfg: AudioDeviceConfig):
        self.cfg = cfg
        self.stream: sd.Stream | None = None
        self._next_allowed_time = 0.0
        self._job_lock = threading.Lock()
        self._job: dict | None = None
        self._jobs_run = 0
        self._create_stream()

    def _create_stream(self):
        if self.stream is not None:
            self.close()

        # Small delay helps some drivers stabilize.
        time.sleep(0.05)
        self.stream = sd.Stream(
            samplerate=self.cfg.sample_rate,
            blocksize=self.cfg.frames_per_buffer,
            dtype="float32",
            channels=(self.cfg.channels_rec, self.cfg.channels_play),
            device=(self.cfg.rec_device, self.cfg.play_device),
            latency=self.cfg.latency,
            callback=self._callback,
        )
        self.stream.start()
        time.sleep(0.05)
        self._jobs_run = 0

    def _callback(self, indata, outdata, frames, time_info, status):  # noqa: ANN001
        # Keep callback lean; no logging.
        with self._job_lock:
            job = self._job

        if job is None:
            outdata[:] = 0
            return

        if status:
            job["had_xrun"] = True

        idx = job["idx"]
        total = job["total"]
        end = min(idx + frames, total)
        n = end - idx

        # Output
        out_ch = job["out_ch"]
        if n > 0:
            chunk = job["play"][idx:end]
            if out_ch == 1:
                outdata[:n, 0] = chunk
            else:
                outdata[:n, :] = chunk.reshape(-1, 1)
            if n < frames:
                outdata[n:, :] = 0
        else:
            outdata[:] = 0

        # Input
        if n > 0:
            job["rec"][idx:end] = indata[:n, 0]

        job["idx"] = end
        if end >= total:
            job["done"].set()
            with self._job_lock:
                self._job = None

    def close(self):
        if self.stream is None:
            return
        try:
            self.stream.stop()
            time.sleep(0.05)
            self.stream.close()
            time.sleep(0.05)
        finally:
            self.stream = None

    def play_and_record(self, play_signal: np.ndarray, extra_record_seconds: float = 0.1) -> np.ndarray:
        if self.stream is None:
            self._create_stream()

        if extra_record_seconds < 0:
            raise ValueError(f"extra_record_seconds must be >= 0, got {extra_record_seconds}")

        # Rate-limit: ensure we don't start a new measurement too soon.
        now = time.monotonic()
        if now < self._next_allowed_time:
            time.sleep(self._next_allowed_time - now)

        out_ch = int(self.cfg.channels_play)
        if out_ch < 1:
            raise ValueError(f"channels_play must be >= 1, got {out_ch}")

        play_signal = np.asarray(play_signal, dtype=np.float32)
        extra_frames = int(extra_record_seconds * self.cfg.sample_rate)
        total_frames = int(play_signal.shape[0]) + extra_frames

        # Priming: prepend silent blocks and trim them from the returned
        # recording. This flushes stale buffered samples without shifting the
        # time origin of play_signal.
        priming_blocks = 3 if self._jobs_run == 0 else 1
        priming_frames = int(self.cfg.frames_per_buffer) * int(priming_blocks)
        play_buf = np.concatenate(
            [
                np.zeros(priming_frames, dtype=np.float32),
                play_signal,
                np.zeros(extra_frames, dtype=np.float32),
            ]
        )
        total_with_priming = int(play_buf.shape[0])

        # One retry on xrun helps stability under load.
        for attempt in range(2):
            recorded_full = np.zeros(total_with_priming, dtype=np.float32)
            done = threading.Event()
            job = {
                "play": play_buf,
                "rec": recorded_full,
                "idx": 0,
                "total": total_with_priming,
                "done": done,
                "out_ch": out_ch,
                "had_xrun": False,
            }

            with self._job_lock:
                if self._job is not None:
                    raise RuntimeError("Audio stream is busy")
                self._job = job

            timeout_s = (total_with_priming / float(self.cfg.sample_rate)) + 1.0
            if not done.wait(timeout=timeout_s):
                with self._job_lock:
                    self._job = None
                raise TimeoutError("Timed out waiting for audio stream")

            had_xrun = bool(job.get("had_xrun"))
            if (not had_xrun) or attempt == 1:
                recorded = recorded_full[
                    priming_frames:priming_frames + total_frames
                ]
                cooldown_s = 0.005
                self._next_allowed_time = time.monotonic() + cooldown_s
                self._jobs_run += 1
                return recorded

            # Brief pause before retry.
            time.sleep(0.02)

        raise RuntimeError("Unreachable")


_global_stream: PersistentAudioStream | None = None
_global_signature: tuple | None = None


def get_global_stream(cfg: AudioDeviceConfig) -> PersistentAudioStream:
    global _global_stream, _global_signature
    sig = _cfg_signature(cfg)
    if _global_stream is None or _global_signature != sig:
        if _global_stream is not None:
            try:
                _global_stream.close()
            except Exception:
                pass
        _global_stream = PersistentAudioStream(cfg)
        _global_signature = sig
    return _global_stream


def close_global_stream():
    global _global_stream, _global_signature
    if _global_stream is not None:
        try:
            _global_stream.close()
        finally:
            _global_stream = None
            _global_signature = None


atexit.register(close_global_stream)


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
    """Play signal and simultaneously record via a persistent duplex stream."""
    stream = get_global_stream(cfg)
    return stream.play_and_record(play_signal, extra_record_seconds=extra_record_seconds)


def rms_level(samples: Iterable[float]) -> float:
    arr = np.asarray(list(samples), dtype=np.float32)
    if arr.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(arr ** 2)))
