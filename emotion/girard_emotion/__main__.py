"""Girard emotion engine: the prospect's mood from the largest face on screen plus what they say. All local.

stdin  (commands): {"cmd": "start"} | {"cmd": "text", "text": "..."} | {"cmd": "stop"} | {"cmd": "quit"}
stdout (events):   ready, mood, error
Runs at below-normal priority with one thread per model, so speech-to-text always wins the CPU.
"""
from __future__ import annotations

import ctypes
import json
import math
import os
import sys
import threading
import time

os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")  # before cv2 loads: its backend notices are noise here

import mss  # noqa: E402
import numpy as np  # noqa: E402

from .readers import FaceReader, TextReader  # noqa: E402

FPS = 3
FACE_TAU_S = 1.5     # face scores are smoothed over about this long
TEXT_TAU_S = 8.0     # a line's emotion fades over about this long
FACE_WEIGHT = 0.6    # face vs words when both are present
NEUTRAL_DAMP = 0.55  # webcam faces sit on "neutral"; damp it so real expressions show
HOLD_S = 1.2         # a new mood must lead this long before it pops
MOODS = ["positive", "interested", "neutral", "skeptical", "worried", "annoyed"]

FACE_GROUPS = {"happiness": "positive", "surprise": "interested", "neutral": "neutral", "contempt": "skeptical",
               "disgust": "skeptical", "fear": "worried", "sadness": "worried", "anger": "annoyed"}
TEXT_GROUPS = {
    "positive": ["joy", "amusement", "approval", "admiration", "gratitude", "love", "optimism", "relief", "pride",
                 "caring", "excitement"],
    "interested": ["curiosity", "surprise", "desire", "realization"],
    "neutral": ["neutral"],
    "skeptical": ["disapproval", "disgust", "confusion"],
    "worried": ["fear", "nervousness", "sadness", "disappointment", "embarrassment", "grief", "remorse"],
    "annoyed": ["anger", "annoyance"],
}

_out_lock = threading.Lock()


def emit(event: str, **data) -> None:
    with _out_lock:
        sys.stdout.write(json.dumps({"type": event, **data}) + "\n")
        sys.stdout.flush()


def below_normal_priority() -> None:
    if sys.platform == "win32":
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)


class Mood:
    """Blends a smoothed face signal with fading text signals into one mood, with hysteresis."""

    def __init__(self):
        self.face = {m: 0.0 for m in MOODS}
        self.face_at = 0.0
        self.valence = 0.0
        self.arousal = 0.0
        self.texts: list[tuple[float, dict[str, float]]] = []
        self.current = "neutral"
        self.candidate, self.candidate_since = "neutral", 0.0

    def add_face(self, r: dict, now: float) -> None:
        a = 1 - math.exp(-(now - self.face_at) / FACE_TAU_S) if self.face_at else 1.0
        grouped = {m: 0.0 for m in MOODS}
        for cls, p in r["probs"].items():
            grouped[FACE_GROUPS[cls]] += p
        for m in MOODS:
            self.face[m] += a * (grouped[m] - self.face[m])
        self.valence += a * (r["valence"] - self.valence)
        self.arousal += a * (r["arousal"] - self.arousal)
        self.face_at = now

    def add_text(self, probs: dict[str, float], now: float) -> None:
        grouped = {m: max(probs[l] for l in labels) for m, labels in TEXT_GROUPS.items()}
        total = sum(grouped.values()) or 1.0
        self.texts = [t for t in self.texts if now - t[0] < 4 * TEXT_TAU_S] + [(now, {m: v / total for m, v in grouped.items()})]

    def blend(self, now: float) -> dict[str, float]:
        face_live = now - self.face_at < 3.0
        text = {m: 0.0 for m in MOODS}
        weight = 0.0
        for at, g in self.texts:
            w = math.exp(-(now - at) / TEXT_TAU_S)
            weight += w
            for m in MOODS:
                text[m] += w * g[m]
        if weight:
            text = {m: v / weight for m, v in text.items()}
        fw = FACE_WEIGHT if face_live and weight else (1.0 if face_live else 0.0)
        tw = (1 - fw) if weight else 0.0
        scores = {m: fw * self.face[m] + tw * text[m] for m in MOODS}
        scores["neutral"] *= NEUTRAL_DAMP
        return scores

    def update(self, now: float) -> dict | None:
        scores = self.blend(now)
        total = sum(scores.values())
        if not total:
            return None
        top = max(scores, key=scores.get)
        if top != self.candidate:
            self.candidate, self.candidate_since = top, now
        changed = False
        if self.candidate != self.current and now - self.candidate_since >= HOLD_S:
            self.current, changed = self.candidate, True
        text_valence = scores["positive"] + 0.5 * scores["interested"] - scores["worried"] - scores["annoyed"] - 0.7 * scores["skeptical"]
        valence = 0.6 * self.valence + 0.4 * np.tanh(2 * text_valence / total) if now - self.face_at < 3 else np.tanh(2 * text_valence / total)
        return {
            "mood": self.current,
            "intensity": round(scores[self.current] / total, 2),
            "valence": round(float(valence), 2),
            "engagement": round((self.arousal + 1) / 2, 2),
            "face": now - self.face_at < 3.0,
            "changed": changed,
        }


class Engine:
    def __init__(self):
        self.faces = FaceReader()
        self.words = TextReader()
        self.mood = Mood()
        self.lock = threading.Lock()
        self.stop_flag = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        self.stop()
        self.mood = Mood()
        self.stop_flag.clear()
        self.thread = threading.Thread(target=self._watch, name="screen", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_flag.set()
        if self.thread:
            self.thread.join(timeout=3)
            self.thread = None

    def text(self, text: str) -> None:
        try:
            probs = self.words.read(text)
        except Exception as exc:
            emit("error", message=f"Mood from text failed: {exc}")
            return
        with self.lock:
            self.mood.add_text(probs, time.monotonic())
        self._publish()

    def _publish(self) -> None:
        with self.lock:
            m = self.mood.update(time.monotonic())
        if m:
            emit("mood", **m)

    def _watch(self) -> None:
        """Screenshot the whole screen a few times a second and read the largest face."""
        slow_logged = False
        with mss.MSS() as screen:
            monitor = screen.monitors[0]  # every monitor together
            while not self.stop_flag.is_set():
                t0 = time.perf_counter()
                try:
                    frame = np.asarray(screen.grab(monitor))
                    r = self.faces.read(frame)
                    if r:
                        with self.lock:
                            self.mood.add_face(r, time.monotonic())
                    self._publish()
                except Exception as exc:
                    emit("error", message=f"Mood from face failed: {exc}")
                    self.stop_flag.wait(2)
                spent = time.perf_counter() - t0
                if spent > 1 / FPS and not slow_logged:
                    print(f"emotion frame took {spent * 1000:.0f} ms", file=sys.stderr, flush=True)
                    slow_logged = True
                self.stop_flag.wait(max(0.0, 1 / FPS - spent))


def main() -> None:
    below_normal_priority()
    try:
        engine = Engine()
    except Exception as exc:
        emit("error", message=f"Could not load the mood models: {exc}", fatal=True)
        return
    emit("ready")
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
            cmd = msg.get("cmd")
            if cmd == "start":
                engine.start()
            elif cmd == "text":
                engine.text(msg.get("text", ""))
            elif cmd == "stop":
                engine.stop()
            elif cmd == "quit":
                break
        except Exception as exc:
            emit("error", message=f"{type(exc).__name__}: {exc}")
    engine.stop()


if __name__ == "__main__":
    main()
