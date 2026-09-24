"""Girard audio sidecar. The Electron app starts this process and talks to it in JSON lines.

stdin  (commands): {"cmd": "devices"} | {"cmd": "start", "device": id, "names": [...]}
                   | {"cmd": "names", "names": [...]} | {"cmd": "stop"} | {"cmd": "quit"}
stdout (events):   ready, devices, started, stopped, level, speech, heard, line, error
Logs go to stderr so stdout stays pure JSON.
"""
from __future__ import annotations

import json
import queue
import sys
import threading
import time

import numpy as np

from .capture import SAMPLE_RATE, Capture, list_outputs
from .filter import LineFilter
from .stt import Transcriber

_out_lock = threading.Lock()
MAX_BACKLOG_S = 10.0  # audio waiting for the model; beyond this the oldest is dropped, never a crash


def emit(event: str, **data) -> None:
    line = json.dumps({"type": event, **data}, ensure_ascii=False)
    with _out_lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


class Session:
    def __init__(self, transcriber: Transcriber):
        self.stt = transcriber
        self.filter = LineFilter()
        self.blocks: queue.Queue[np.ndarray | None] = queue.Queue()
        self.capture: Capture | None = None
        self.worker: threading.Thread | None = None
        self.backlog = 0  # samples queued

    def start(self, device: str, names: list[str]) -> None:
        self.stop()
        self.stt.reset()
        self.filter = LineFilter(names)
        self.blocks = queue.Queue()
        self.backlog = 0
        self.worker = threading.Thread(target=self._work, name="stt", daemon=True)
        self.worker.start()
        self.capture = Capture(device, self._on_block, lambda msg: emit("error", message=msg))
        self.capture.start()
        emit("started", device=device)

    def stop(self) -> None:
        if self.capture:
            self.capture.stop()
            self.capture = None
        if self.worker:
            self.blocks.put(None)
            self.worker.join(timeout=10)
            self.worker = None
            emit("stopped")

    def _on_block(self, samples: np.ndarray) -> None:
        self.blocks.put(samples)
        self.backlog += len(samples)
        if self.backlog > MAX_BACKLOG_S * SAMPLE_RATE:
            try:  # the model fell behind: drop the oldest audio rather than stall the call
                dropped = self.blocks.get_nowait()
                if dropped is not None:
                    self.backlog -= len(dropped)
                    emit("error", message="Speech model fell behind; skipped a moment of audio.")
            except queue.Empty:
                pass

    def _work(self) -> None:
        last_level = 0.0
        while True:
            try:
                samples = self.blocks.get(timeout=0.2)
            except queue.Empty:
                self._flush_held()
                continue
            if samples is None:
                break
            self.backlog -= len(samples)
            now = time.monotonic()
            if now - last_level >= 0.1:
                emit("level", rms=round(float(np.sqrt(np.mean(samples ** 2))), 4))
                last_level = now
            try:
                started, chunks = self.stt.feed(samples)
            except Exception as exc:
                emit("error", message=f"Speech-to-text failed on a chunk: {exc}")
                continue
            if started:
                emit("speech")
            for c in chunks:
                self._handle(c.text, c.audio_end, c.stt_ms)
            self._flush_held()
        for c in self.stt.flush():
            self._handle(c.text, c.audio_end, c.stt_ms)
        if self.filter.held:
            self._send(self.filter.held, "flushed", 0.0, 0.0, 0.0)
            self.filter.held = ""

    def _handle(self, raw: str, audio_end: float, stt_ms: float) -> None:
        emit("heard", text=self.filter.fix_names(raw), audio_end=round(audio_end, 2))
        t = time.perf_counter()
        r = self.filter.process(raw)
        filter_us = (time.perf_counter() - t) * 1e6
        if r.text:
            self._send(r.text, r.rule, audio_end, stt_ms, filter_us)

    def _flush_held(self) -> None:
        r = self.filter.flush_due()
        if r:
            self._send(r.text, r.rule, 0.0, 0.0, 0.0)

    def _send(self, text: str, rule: str, audio_end: float, stt_ms: float, filter_us: float) -> None:
        emit("line", text=text, rule=rule, audio_end=round(audio_end, 2), stt_ms=round(stt_ms),
             filter_us=round(filter_us))


def main() -> None:
    t = time.perf_counter()
    try:
        session = Session(Transcriber())
    except Exception as exc:
        emit("error", message=f"Could not load the speech model: {exc}", fatal=True)
        return
    emit("ready", load_ms=round((time.perf_counter() - t) * 1000))
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
            cmd = msg.get("cmd")
            if cmd == "devices":
                emit("devices", devices=list_outputs())
            elif cmd == "start":
                session.start(msg["device"], msg.get("names", []))
            elif cmd == "names":
                session.filter.set_names(msg.get("names", []))
            elif cmd == "stop":
                session.stop()
            elif cmd == "quit":
                break
            else:
                emit("error", message=f"Unknown command: {cmd}")
        except Exception as exc:
            emit("error", message=f"{type(exc).__name__}: {exc}")
    session.stop()


if __name__ == "__main__":
    main()
