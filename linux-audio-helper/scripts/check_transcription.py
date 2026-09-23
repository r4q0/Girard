#!/usr/bin/env python3
"""Exercise the real local CLI with a bundled speech fixture, never live audio.

Run from the project root with the project's Python environment:
  .venv/bin/python scripts/check_transcription.py --report reports/local-benchmark.json

Uses the first 24 seconds of moonshine-voice's installed two_cities.wav.
The package's own transcription example uses this fixture. Its distribution is
MIT licensed, copyright Moonshine AI 2025; the spoken source is Charles Dickens'
public-domain A Tale of Two Cities. The recording is not copied into this repo.
Upstream: https://github.com/moonshine-ai/moonshine
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import re
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np
import moonshine_voice

from call_audio.engines import MoonshineEngine


def run_cli(path: Path, realtime: bool, model: str) -> dict:
    command = [sys.executable, "-m", "call_audio.cli", "transcribe-file", str(path), "--model", model, "--json"]
    if realtime:
        command.append("--realtime")
    result = subprocess.run(command, capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError(f"Transcription CLI failed ({result.returncode}): {result.stderr[-4000:]}")
    events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
    reports = [json.loads(line) for line in result.stderr.splitlines() if line.startswith("{")]
    metrics = next(item for item in reversed(reports) if item.get("type") == "benchmark")
    transcripts = [event for event in events if event.get("type") == "transcript"]
    finals = [event for event in transcripts if event["is_final"]]
    partials = [event for event in transcripts if not event["is_final"]]
    assert partials, "No provisional transcription was emitted."
    assert finals, "No finalized transcription was emitted."
    seen_final = set()
    for event in transcripts:
        segment = event["segment_id"]
        assert segment not in seen_final, "A finalized segment was emitted more than once or revised."
        assert event["end_ms"] >= event["start_ms"] >= 0
        if event["is_final"]:
            seen_final.add(segment)
    assert {event["segment_id"] for event in transcripts} == seen_final, "Stop left a provisional segment unfinished."
    combined = " ".join(event["text"] for event in finals)
    normalized = " ".join(re.findall(r"[a-z]+", combined.lower()))
    opening_present = "it was the best of times it was the worst of times" in normalized
    assert opening_present, "The sample's known opening phrase was not transcribed correctly."
    metrics.update({
        "partial_events": len(partials), "final_events": len(finals),
        "final_text": combined, "known_opening_phrase_correct": opening_present,
        "native_inference_event_p95_ms": round(float(np.percentile(
            [e["engine_latency_ms"] for e in transcripts if "engine_latency_ms" in e], 95
        )), 2),
    })
    return metrics


def check_model_reuse(model: str) -> dict:
    events = []
    engine = MoonshineEngine(events.append, model=model)
    first_start = time.perf_counter()
    try:
        engine.start()
        initial_ms = (time.perf_counter() - first_start) * 1000
        transcriber = engine._transcriber
        engine.process(np.zeros(9600, dtype=np.float32), 48000)
        engine.finish()
        restart = time.perf_counter()
        engine.start()
        restart_ms = (time.perf_counter() - restart) * 1000
        assert engine._transcriber is transcriber, "The model was reloaded between calls."
        engine.process(np.zeros(9600, dtype=np.float32), 48000)
        engine.finish()
        assert not [event for event in events if event["type"] == "transcript"], "Silence produced unexpected words."
        return {"initial_load_ms": round(initial_ms, 2), "new_session_with_loaded_model_ms": round(restart_ms, 2),
                "same_model_reused": True, "silent_warmup_transcript_events": 0}
    finally:
        engine.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=24.0)
    parser.add_argument("--model", choices=("tiny", "small", "medium"), default="small")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if not 10 <= args.seconds <= 30:
        parser.error("Choose 10–30 seconds of the known fixture.")
    fixture = Path(moonshine_voice.__file__).parent / "assets" / "two_cities.wav"
    if not fixture.is_file():
        raise FileNotFoundError(f"The installed Moonshine package lacks its expected test fixture: {fixture}")
    with tempfile.TemporaryDirectory(prefix="call-audio-benchmark-") as directory:
        short_wav = Path(directory) / "two_cities_excerpt.wav"
        with wave.open(str(fixture), "rb") as source:
            params = source.getparams()
            frames = source.readframes(min(source.getnframes(), round(args.seconds * source.getframerate())))
        with wave.open(str(short_wav), "wb") as target:
            target.setparams(params)
            target.writeframes(frames)
        fast = run_cli(short_wav, realtime=False, model=args.model)
        print(json.dumps(fast), flush=True)
        realtime = run_cli(short_wav, realtime=True, model=args.model)
        print(json.dumps(realtime), flush=True)
    reuse = check_model_reuse(args.model)
    print(json.dumps(reuse), flush=True)
    report = {
        "model": args.model, "language": "en", "sample_rate": params.framerate,
        "moonshine_voice_version": importlib.metadata.version("moonshine-voice"),
        "python_version": platform.python_version(), "platform": platform.platform(),
        "fixture": str(fixture), "fixture_excerpt_seconds": args.seconds,
        "fixture_source": "Installed moonshine-voice test asset, two_cities.wav (Dickens, A Tale of Two Cities)",
        "source_repository": "https://github.com/moonshine-ai/moonshine",
        "package_license": "MIT, Copyright (c) 2025 Moonshine AI; asset is not redistributed here",
        "capture_opened": False, "cloud_used": False,
        "runs": [fast, realtime], "model_reuse": reuse,
        "limitations": "Clean recorded English narration only. Processing timing is not word latency. No word-aligned reference, call capture, accents, competing app load, or cloud comparison was tested.",
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"Saved benchmark report: {args.report}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
