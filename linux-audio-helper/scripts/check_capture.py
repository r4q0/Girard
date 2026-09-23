#!/usr/bin/env python3
"""Exercise capture and routing using only this script's silent virtual outputs.

Run from the project: .venv/bin/python scripts/check_capture.py
No microphone or physical output is opened. A generated tone is played only
into private null sinks. The original mute, volume, and defaults are preserved.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import threading
import time
import uuid

import numpy as np

from call_audio.audio import CaptureSource, IsolationRoute, _json, _list_modules, _module_arguments, _pactl


def wait_until(predicate, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("Timed out waiting for the audio server.")


def protected_state():
    info = _json("info")
    return {
        "defaults": (info["default_sink_name"], info["default_source_name"]),
        "sinks": {item["name"]: (item["mute"], item["volume"]) for item in _json("list", "sinks")},
        "sources": {item["name"]: (item["mute"], item["volume"]) for item in _json("list", "sources")},
    }


def main():
    identifier = uuid.uuid4().hex[:12]
    base_sink = f"helper_capture_check_{identifier}"
    application = f"CallAudioCaptureCheck_{identifier}"
    before = protected_state()
    before_sources = {item["index"] for item in _json("list", "source-outputs")}
    module_id = None
    route = None
    capture = None
    player = None
    feeder = None
    feed_stop = threading.Event()
    report = {}

    def stop_player():
        feed_stop.set()
        if player is not None and player.poll() is None:
            player.terminate()
            try:
                player.wait(timeout=2)
            except subprocess.TimeoutExpired:
                player.kill()
                player.wait(timeout=2)
        if feeder is not None:
            feeder.join(timeout=1)

    def remove_base():
        nonlocal module_id
        if module_id is not None:
            current = next((m for m in _list_modules() if m["index"] == module_id), None)
            if current:
                assert current["name"] == "module-null-sink"
                assert _module_arguments(current.get("argument", "")).get("sink_name") == base_sink
                _pactl("unload-module", str(module_id))
            module_id = None

    try:
        module_id = int(_pactl("load-module", "module-null-sink", f"sink_name={base_sink}",
                               "rate=48000", "channels=2", "sink_properties=device.description=Capture_Check_Private"))
        player = subprocess.Popen(
            ["pacat", "--playback", "--raw", "--format=float32le", "--rate=48000", "--channels=2",
             f"--device={base_sink}", f"--property=application.name={application}"],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        tone = (0.2 * np.sin(2 * np.pi * 440 * np.arange(4800) / 48000)).astype("<f4")
        stereo = np.column_stack((tone, tone)).tobytes()

        def feed():
            try:
                while not feed_stop.is_set():
                    player.stdin.write(stereo)
                    player.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                pass

        feeder = threading.Thread(target=feed, name="synthetic-audio", daemon=True)
        feeder.start()
        stream = wait_until(lambda: next((s for s in _json("list", "sink-inputs")
                                           if s.get("properties", {}).get("application.name") == application), None))
        stream_id = stream["index"]

        def collect(sink):
            nonlocal capture
            chunks = []
            errors = []
            captured = threading.Event()

            def on_chunk(samples, rate):
                assert samples.ndim == 1 and samples.dtype == np.float32
                assert rate == 48000
                chunks.append(samples)
                if sum(chunk.size for chunk in chunks) >= 48000:
                    captured.set()

            capture = CaptureSource(sink, on_chunk, errors.append)
            capture.start()
            assert captured.wait(5), f"No audio from private sink: {errors}"
            assert not errors, errors
            started = time.monotonic()
            capture.stop()
            stop_ms = (time.monotonic() - started) * 1000
            assert not capture._thread.is_alive()
            samples = np.concatenate(chunks)[4800:]
            rms = float(np.sqrt(np.mean(samples ** 2)))
            assert 0.11 < rms < 0.16, f"Tone RMS mismatch: {rms}"
            metrics = {"sample_rate": 48000, "channels": 1, "rms": round(rms, 5),
                       "chunks": len(chunks), "mean_chunk_ms": round(np.mean([c.size for c in chunks]) / 48, 2),
                       "stop_ms": round(stop_ms, 2)}
            capture = None
            return metrics

        report["direct_private_output"] = collect(base_sink)
        route = IsolationRoute(base_sink)
        route.open()
        route.move_stream(stream_id)
        route_index = next(s["index"] for s in _json("list", "sinks") if s["name"] == route.monitor_sink)
        assert next(s["sink"] for s in _json("list", "sink-inputs") if s["index"] == stream_id) == route_index
        report["isolated_private_output"] = collect(route.monitor_sink)
        route.close()
        route = None
        base_index = next(s["index"] for s in _json("list", "sinks") if s["name"] == base_sink)
        assert next(s["sink"] for s in _json("list", "sink-inputs") if s["index"] == stream_id) == base_index
        report["original_playback_destination_restored"] = True

        # Stop our player before removing its sink so playback cannot migrate
        # to the user's real speakers. Only the pinned monitor remains open.
        removal_error = threading.Event()
        errors = []

        def on_error(error):
            errors.append(str(error))
            removal_error.set()

        capture = CaptureSource(base_sink, lambda *_: None, on_error)
        capture.start()
        wait_until(lambda: any(s["index"] not in before_sources for s in _json("list", "source-outputs")))
        stop_player()
        remove_base()
        assert removal_error.wait(4), "Removing a pinned monitor did not report an error."
        capture.stop()
        assert not capture._thread.is_alive()
        report["removed_monitor_stops_without_source_fallback"] = errors
        capture = None
    finally:
        # Stop own playback before removing any sinks, even on assertion errors.
        stop_player()
        try:
            if capture is not None:
                capture.stop()
        finally:
            try:
                if route is not None:
                    route.close()
            finally:
                remove_base()

    after = protected_state()
    assert before == after, "Original audio defaults, sinks, mute, or volume changed."
    remaining = [s for s in _json("list", "source-outputs") if s["index"] not in before_sources]
    assert not remaining, f"Capture streams were left open: {remaining}"
    assert not any(identifier in m.get("argument", "") for m in _list_modules())
    report["original_audio_state_preserved"] = True
    report["all_temporary_resources_removed"] = True
    print(json.dumps(report, indent=2))
    report_path = Path(__file__).resolve().parents[1] / "reports" / "capture-check.json"
    report_path.parent.mkdir(exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
