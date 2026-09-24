"""Loopback capture of one output device: whatever the computer plays (the prospect's voice), never the mic."""
from __future__ import annotations

import sys
import threading
import warnings
from typing import Callable

import numpy as np
import soundcard

SAMPLE_RATE = 16000  # what the speech model wants; WASAPI converts for us
BLOCK = SAMPLE_RATE // 10  # 100 ms reads: few wakeups, so capture keeps up while the model runs
WINDOWS = sys.platform == "win32"


def list_outputs() -> list[dict]:
    default = soundcard.default_speaker()
    return [{"id": s.id, "name": s.name, "default": s.id == default.id} for s in soundcard.all_speakers()]


class Capture:
    """Reads mono float32 blocks on its own thread and hands them to on_block (which must return fast)."""

    def __init__(self, device_id: str, on_block: Callable[[np.ndarray], None], on_error: Callable[[str], None]):
        self.device_id = device_id
        self.on_block = on_block
        self.on_error = on_error
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        speaker = soundcard.get_speaker(self.device_id)
        source = soundcard.get_microphone(id=self.device_id, include_loopback=True)
        if not source.isloopback:
            raise RuntimeError("The selected device is not an output loopback.")
        self._stop.clear()
        self._threads = [threading.Thread(target=self._record, args=(source,), name="capture", daemon=True)]
        if WINDOWS:
            # Windows sends no loopback packets while nothing plays; playing silence keeps the stream flowing.
            self._threads.append(threading.Thread(target=self._play_silence, args=(speaker,), name="keepalive",
                                                  daemon=True))
        for t in self._threads:
            t.start()

    def stop(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=2)
        self._threads = []

    def _record(self, source) -> None:
        warnings.filterwarnings("ignore", message="data discontinuity in recording")
        try:
            with source.recorder(samplerate=SAMPLE_RATE, channels=1, blocksize=BLOCK) as rec:
                while not self._stop.is_set():
                    data = rec.record(numframes=BLOCK)
                    if self._stop.is_set():
                        break
                    samples = np.clip(np.nan_to_num(np.asarray(data, dtype=np.float32).reshape(-1)), -1.0, 1.0)
                    if samples.size:
                        self.on_block(samples)
        except Exception as exc:  # device unplugged, driver error, ...
            if not self._stop.is_set():
                self.on_error(f"Audio capture stopped: {exc}")

    def _play_silence(self, speaker) -> None:
        try:
            with speaker.player(samplerate=SAMPLE_RATE, channels=1) as player:
                silence = np.zeros(SAMPLE_RATE // 20, dtype=np.float32)
                while not self._stop.is_set():
                    player.play(silence)
        except Exception:
            pass  # capture still works whenever the call itself plays audio
