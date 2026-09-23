#!/usr/bin/env python3
"""Replay explicitly supplied PCM16 call recordings through the existing STT engine.

Never opens a playback/capture device or uploads audio. The manifest must name
each local WAV and a zero-based remote channel; channels are never mixed. Output
contains transcript text and belongs in an ignored/private evaluation directory.
Models must already be cached for offline operation. This measures file replay,
not live word latency, and does not change the production API.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import platform
import time
import wave
from pathlib import Path

import numpy as np

from call_audio.engines import MoonshineEngine


def transcribe_recording(item: dict, engine: MoonshineEngine, events: list,
                         *, realtime: bool) -> dict:
    source = Path(item["audio_path"]).resolve(strict=True)
    channel = item["channel"]
    if type(channel) is not int or channel < 0:
        raise ValueError("A zero-based channel must be explicitly selected.")
    with wave.open(str(source), "rb") as recording:
        if recording.getsampwidth() != 2 or recording.getcomptype() != "NONE":
            raise ValueError("Supply a PCM16 WAV; decode the source losslessly first.")
        channels, rate = recording.getnchannels(), recording.getframerate()
        if channel >= channels:
            raise ValueError("Selected channel is absent from the recording.")
        start_seconds = float(item.get("start_seconds", 0))
        available = recording.getnframes() / rate
        duration = float(item.get("duration_seconds", available - start_seconds))
        if (not math.isfinite(start_seconds) or not math.isfinite(duration)
                or not 0 <= start_seconds < available or duration <= 0):
            raise ValueError("Choose a nonempty excerpt inside the supplied recording.")
        if start_seconds + duration > available + 1 / rate:
            raise ValueError("Requested excerpt extends beyond the supplied recording.")
        recording.setpos(round(start_seconds * rate))
        raw = recording.readframes(round(duration * rate))
    if not raw:
        raise ValueError("The selected excerpt contains no audio frames after rounding.")
    audio = np.frombuffer(raw, dtype="<i2").reshape(-1, channels)[:, channel]
    audio = audio.astype(np.float32) / 32768
    events.clear()
    tick = time.perf_counter()
    engine.start()
    start_ms = (time.perf_counter() - tick) * 1000
    started = time.perf_counter()
    block = max(1, round(rate * .020))
    padded = np.concatenate((audio, np.zeros(rate, dtype=np.float32)))
    timings = []
    for offset in range(0, len(padded), block):
        if realtime:
            delay = started + offset / rate - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
        tick = time.perf_counter()
        engine.process(padded[offset:offset + block], rate)
        timings.append((time.perf_counter() - tick) * 1000)
    engine.finish()
    elapsed = time.perf_counter() - started
    if any(event.get("type") == "error" for event in events):
        raise RuntimeError("Transcription failed; results were not accepted.")
    transcript_events = [event for event in events if event.get("type") == "transcript"]
    final = [dict(event, session_id=item["recording_id"]) for event in transcript_events if event["is_final"]]
    final.sort(key=lambda segment: segment["start_ms"])
    if not final:
        raise RuntimeError("No finalized speech was recognized.")
    if len({segment["segment_id"] for segment in final}) != len(final):
        raise RuntimeError("Duplicate final segment IDs in the replay.")
    if {event["segment_id"] for event in transcript_events} != {segment["segment_id"] for segment in final}:
        raise RuntimeError("Transcription left provisional speech unfinished.")
    return {
        **item, "audio_path": str(source), "duration_seconds": len(audio) / rate,
        "source_wav_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "sample_rate": rate, "source_channels": channels,
        "transcription": {
            "engine": "moonshine", "model": engine.model, "language": "en",
            "package_version": importlib.metadata.version("moonshine-voice"),
            "replay_mode": "realtime" if realtime else "as_fast_as_possible",
            "requested_feed_ms": 20, "silent_tail_seconds": 1,
            "start_ms": round(start_ms, 3), "replay_wall_seconds": round(elapsed, 3),
            "processing_realtime_factor_including_tail": round(elapsed / (len(padded) / rate), 4),
            "feed_p95_ms": round(float(np.percentile(timings, 95)), 4),
            "partial_events": sum(not event["is_final"] for event in transcript_events),
            "final_segments": len(final), "no_microphone_or_output_device_opened": True,
            "no_audio_upload_or_hosted_inference": True,
        },
        "segments": final,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", choices=("tiny", "small", "medium"), default="small")
    parser.add_argument("--realtime", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; choose a new result filename.")
    data = json.loads(args.manifest.read_text(encoding="utf-8"))
    recordings = data["recordings"]
    if not recordings or len({item["recording_id"] for item in recordings}) != len(recordings):
        parser.error("Manifest must contain uniquely identified recordings.")
    events, completed = [], []
    engine = MoonshineEngine(events.append, model=args.model)
    try:
        for item in recordings:
            print(f"Transcribing {item['recording_id']} locally...", flush=True)
            completed.append(transcribe_recording(item, engine, events, realtime=args.realtime))
            print(json.dumps({"recording_id": item["recording_id"],
                              **completed[-1]["transcription"]}), flush=True)
    finally:
        engine.close()
    result = {**data, "recordings": completed,
              "platform": platform.platform(), "python": platform.python_version(),
              "limitations": "Offline replay of selected channels, not live call capture or word-aligned accuracy evaluation. Transcript errors remain possible."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Saved local transcript data: {args.output}", flush=True)


if __name__ == "__main__":
    main()
