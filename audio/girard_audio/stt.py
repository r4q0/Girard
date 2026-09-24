"""Speech-to-text: silero VAD cuts speech at each pause (or at 5 s), Parakeet 0.6B transcribes each chunk."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import sherpa_onnx

from .capture import SAMPLE_RATE

MODELS = Path(os.environ.get("GIRARD_MODELS", Path(__file__).resolve().parents[1] / "models"))
PARAKEET = MODELS / "parakeet-0.6b"
MAX_CHUNK_S = 5.0     # force a cut in long speech so advice never waits for a pause
MIN_SILENCE_S = 0.5   # a pause this long ends a chunk
THREADS = 4


@dataclass
class Chunk:
    text: str
    audio_end: float  # seconds since capture start
    stt_ms: float     # time to transcribe this chunk


class Transcriber:
    def __init__(self):
        self.recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(PARAKEET / "encoder.int8.onnx"), decoder=str(PARAKEET / "decoder.int8.onnx"),
            joiner=str(PARAKEET / "joiner.int8.onnx"), tokens=str(PARAKEET / "tokens.txt"),
            num_threads=THREADS, model_type="nemo_transducer")
        # Warm the model so the first real chunk is not slow.
        s = self.recognizer.create_stream()
        s.accept_waveform(SAMPLE_RATE, np.zeros(SAMPLE_RATE, dtype=np.float32))
        self.recognizer.decode_stream(s)
        self.reset()

    def reset(self) -> None:
        cfg = sherpa_onnx.VadModelConfig()
        cfg.silero_vad.model = str(MODELS / "silero_vad.onnx")
        cfg.silero_vad.min_silence_duration = MIN_SILENCE_S
        cfg.silero_vad.max_speech_duration = MAX_CHUNK_S
        cfg.sample_rate = SAMPLE_RATE
        self.vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=30)
        self.pending = np.zeros(0, dtype=np.float32)
        self.samples_in = 0
        self.speaking = False

    def feed(self, samples: np.ndarray) -> tuple[bool, list[Chunk]]:
        """Feed audio. Returns (speech just started, finished chunks)."""
        self.pending = np.concatenate([self.pending, samples])
        started = False
        chunks: list[Chunk] = []
        window = 512  # silero works on 512-sample windows
        while len(self.pending) >= window:
            self.vad.accept_waveform(self.pending[:window])
            self.pending = self.pending[window:]
            self.samples_in += window
            detected = self.vad.is_speech_detected()
            if detected and not self.speaking:
                started = True
            self.speaking = detected
            chunks += self._drain()
        return started, chunks

    def _drain(self) -> list[Chunk]:
        out = []
        while not self.vad.empty():
            seg = self.vad.front
            samples = np.array(seg.samples, dtype=np.float32)
            end = (seg.start + len(samples)) / SAMPLE_RATE
            self.vad.pop()
            t = time.perf_counter()
            s = self.recognizer.create_stream()
            s.accept_waveform(SAMPLE_RATE, samples)
            self.recognizer.decode_stream(s)
            text = s.result.text.strip()
            if text:
                out.append(Chunk(text, end, (time.perf_counter() - t) * 1000))
        return out

    def flush(self) -> list[Chunk]:
        self.vad.flush()
        return self._drain()

