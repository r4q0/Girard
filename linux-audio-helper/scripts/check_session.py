#!/usr/bin/env python3
"""Test the real HTTP → output capture → local model → SSE → Stop pipeline.

All test speech plays into one uniquely named private null sink. No microphone,
physical playback, cloud API, existing application stream, default, or volume
is changed. The installed Moonshine test asset supplies the recorded speech.
Run: .venv/bin/python scripts/check_session.py --report reports/session-check.json
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import re
import socket
import time
import uuid
import wave
from pathlib import Path

import aiohttp
from aiohttp import web
import moonshine_voice
import numpy as np

from call_audio.audio import _json, _list_modules, _module_arguments, _pactl
from call_audio.server import CONTROLLER, create_app
from call_audio.tokens import load_token_counter
from check_capture import protected_state


async def until(predicate, timeout=10, description="condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        await asyncio.sleep(.05)
    raise AssertionError(f"Timed out waiting for {description}.")


async def check_session(compression="none", tokenizer_name=None) -> dict:
    identifier = uuid.uuid4().hex[:12]
    private_sink = f"helper_session_check_{identifier}"
    application = f"CallAudioSessionCheck_{identifier}"
    fixture = Path(moonshine_voice.__file__).parent / "assets" / "two_cities.wav"
    with wave.open(str(fixture), "rb") as recording:
        assert recording.getnchannels() == 1 and recording.getsampwidth() == 2
        assert recording.getframerate() == 48000
        recorded = recording.readframes(24 * 48000)

    # All diagnostics occur before changing the audio server. A sandbox denial
    # therefore leaves no partial sink, route, or capture behind.
    before = protected_state()
    before_sources = {item["index"] for item in _json("list", "source-outputs")}
    before_modules = {item["index"] for item in _list_modules()}
    bound = socket.socket()
    bound.bind(("127.0.0.1", 0))
    bound.setblocking(False)
    port = bound.getsockname()[1]
    address = f"http://127.0.0.1:{port}"
    module_id = None
    runner = client = player = feeder = event_reader = event_response = None
    app = None
    events, live_segments = [], {}
    report = {}
    cleanup_errors = []

    async def request(method, path, *, expected=200, headers=None, body=None):
        common = {"Origin": address, "X-Call-Audio": "1"}
        if headers:
            common.update(headers)
        async with client.request(method, address + path, headers=common, json=body,
                                  timeout=aiohttp.ClientTimeout(total=8)) as response:
            raw = await response.text()
            assert response.status == expected, f"{method} {path}: {response.status}, {raw}"
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = raw
            return data, dict(response.headers)

    async def read_events():
        async for line in event_response.content:
            if line.startswith(b"data: "):
                event = json.loads(line[6:])
                events.append({**event, "test_received_at": time.monotonic()})
                if event.get("type") == "transcript":
                    live_segments[event["segment_id"]] = event

    async def feed_player():
        try:
            for offset in range(0, len(recorded), 9600):
                player.stdin.write(recorded[offset:offset + 9600])
                await player.stdin.drain()
            player.stdin.close()
            await player.stdin.wait_closed()
        except (BrokenPipeError, ConnectionResetError):
            pass

    try:
        module_id = int(_pactl("load-module", "module-null-sink", f"sink_name={private_sink}",
                               "rate=48000", "channels=2", "sink_properties=device.description=Session_Check_Private"))
        token_counter = load_token_counter(tokenizer_name)
        app = create_app(port=port, model="small", token_counter=token_counter, tokenizer_name=tokenizer_name)
        runner = web.AppRunner(app, access_log=None, shutdown_timeout=3)
        await runner.setup()
        await web.SockSite(runner, bound).start()
        client = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, sock_connect=3))

        health, _ = await request("GET", "/api/health")
        assert health["app"] == "call-audio-helper"
        assert health["mode"] == "headless" and health["api_version"] == 1
        for path in ("/", "/api/health", "/api/transcript"):
            content, headers = await request("GET", path)
            assert content
            assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
            assert headers["X-Content-Type-Options"] == "nosniff"
            assert headers["Cache-Control"] == "no-store"
        for path in ("/static/app.js", "/static/style.css", "/index.html"):
            await request("GET", path, expected=404)
        await request("POST", "/api/start", expected=403,
                      headers={"Origin": "https://unrelated.invalid"}, body={})
        await request("POST", "/api/start", expected=403,
                      headers={"X-Call-Audio": ""}, body={})
        await request("GET", "/api/health", expected=403,
                      headers={"Host": f"unrelated.invalid:{port}"})
        report["headless_api_no_ui_security_headers_and_origin_checks"] = True

        controller = app[CONTROLLER]
        await until(lambda: controller.model_ready or controller.model_error,
                    description="local model preload", timeout=20)
        assert controller.model_ready, controller.model_error
        state, _ = await request("GET", "/api/state")
        assert state["state"] == "idle" and state["model_ready"]
        assert {item["index"] for item in _json("list", "source-outputs")} == before_sources
        report["model_preloads_without_opening_capture"] = True

        devices, _ = await request("GET", "/api/devices")
        assert any(output["id"] == private_sink for output in devices["outputs"])
        event_response = await client.get(address + "/api/events", headers={"Origin": address})
        assert event_response.status == 200
        assert event_response.headers["Content-Type"].startswith("text/event-stream")
        event_reader = asyncio.create_task(read_events())
        await until(lambda: events, description="initial SSE state")

        loaded_model = controller._local._transcriber
        state, _ = await request("POST", "/api/start", body={
            "engine": "local", "sink_id": private_sink, "isolate": False, "compression": compression,
        })
        assert state["state"] in ("loading", "listening")
        session_id = state["session_id"]
        await until(lambda: controller.state in ("listening", "error"), description="capture readiness")
        assert controller.state == "listening", controller.error
        assert controller._local._transcriber is loaded_model
        monitor_index = next(source["index"] for source in _json("list", "sources")
                             if source["name"] == private_sink + ".monitor")
        def capture_streams():
            return [item for item in _json("list", "source-outputs") if item["index"] not in before_sources]
        active_sources = await until(capture_streams, description="native output-monitor stream")
        assert all(item["source"] == monitor_index for item in active_sources)
        report["capture_uses_only_private_output_monitor"] = True

        player = await asyncio.create_subprocess_exec(
            "pacat", "--playback", "--raw", "--format=s16le", "--rate=48000", "--channels=1",
            "--latency-msec=20", f"--device={private_sink}", f"--property=application.name={application}",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        playback_started = time.monotonic()
        feeder = asyncio.create_task(feed_player())
        # Stop during provisional speech after at least twelve seconds so this
        # checks the real Stop flush, not only natural sentence boundaries.
        await until(lambda: time.monotonic() - playback_started >= 12
                    and any(not item["is_final"] for item in live_segments.values()),
                    description="provisional speech after twelve seconds", timeout=24)
        assert player.returncode is None, "The test playback ended before the Stop check."
        stop_started = time.monotonic()
        pending_at_stop = {key for key, event in live_segments.items() if not event["is_final"]}
        stopped, _ = await request("POST", "/api/stop", body={})
        stop_ms = (time.monotonic() - stop_started) * 1000
        await until(lambda: controller.state in ("idle", "error"), description="idle after Stop")
        assert controller.state == "idle", controller.error
        await until(lambda: all(live_segments[key]["is_final"] for key in pending_at_stop),
                    description="final SSE delivery for segments active at Stop")
        stopped, _ = await request("GET", "/api/state")
        assert stopped["state"] == "idle" and stopped["error"] is None
        assert stopped["estimated_cost_usd"] == 0
        assert stopped["segments"] and all(segment["is_final"] for segment in stopped["segments"])
        snapshot, _ = await request("GET", "/api/transcript")
        assert snapshot["session_id"] == session_id
        assert snapshot["complete"] and not snapshot["has_pending"]
        assert snapshot["segments"] == stopped["segments"]
        assert snapshot["text"] == "\n".join(segment["text"] for segment in stopped["segments"])
        transcripts = [event for event in events if event.get("type") == "transcript"]
        partials = [event for event in transcripts if not event["is_final"]]
        finals = [event for event in transcripts if event["is_final"]]
        assert partials and finals
        assert all("compact_text" not in event for event in partials)
        if compression == "minimal":
            assert all(event["compression"]["mode"] == "minimal" for event in finals)
            assert snapshot["compact_text"] == "\n".join(segment["compact_text"] for segment in stopped["segments"])
        assert all(event["session_id"] == session_id for event in transcripts)
        final_ids = [event["segment_id"] for event in finals]
        assert len(set(final_ids)) == len(final_ids), "Duplicate finalized transcript event."
        combined = " ".join(segment["text"] for segment in stopped["segments"])
        normalized = " ".join(re.findall(r"[a-z]+", combined.lower()))
        assert "it was the best of times" in normalized, combined
        metrics = [event for event in events if event.get("type") == "metrics"]
        assert not [event for event in events if event.get("type") == "error"]
        report.update({
            "partial_events": len(partials), "final_events": len(finals),
            "segments_pending_at_stop": len(pending_at_stop),
            "stop_flush_completed_all_segments": True,
            "stop_request_ms": round(stop_ms, 2),
            "playback_seconds_before_stop": round(stop_started - playback_started, 3),
            "observed_processing_ms_p95": round(float(np.percentile([e["processing_ms"] for e in metrics], 95)), 2),
            "observed_queue_ms_max": max(e["queue_ms"] for e in metrics),
            "cost_usd": stopped["estimated_cost_usd"],
            "compression_mode": compression,
            "compression_tokenizer": tokenizer_name,
            "compression_ms_p95": round(float(np.percentile([event.get("compression_ms", 0) for event in finals], 95)), 4),
            "removed_filler_words": sum(event.get("compression", {}).get("removed_words", 0) for event in finals),
            "finalized_transcript_json_verified": True,
            "final_state": stopped["state"], "final_text": combined,
            "fixture": "moonshine_voice/assets/two_cities.wav", "sample_rate": 48000,
            "cloud_used": False, "physical_playback_used": False,
            "note": "Metric snapshots sample the live pipeline; this is not a word-latency benchmark or a full-call accuracy test.",
        })
    finally:
        # Always stop private playback first, so unloading the sink cannot
        # migrate this test's speech onto the user's physical output.
        if player is not None and player.returncode is None:
            player.terminate()
            try:
                await asyncio.wait_for(player.wait(), timeout=2)
            except asyncio.TimeoutError:
                player.kill()
                await player.wait()
        if feeder:
            feeder.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await feeder
        if app is not None:
            try:
                await app[CONTROLLER].stop()
            except Exception as exc:
                cleanup_errors.append(f"Stop: {exc}")
        if event_reader:
            event_reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await event_reader
        if event_response:
            event_response.close()
        if client:
            await client.close()
        if runner:
            try:
                await runner.cleanup()
            except Exception as exc:
                cleanup_errors.append(f"Server cleanup: {exc}")
        bound.close()
        if module_id is not None:
            current = next((item for item in _list_modules() if item["index"] == module_id), None)
            if current:
                assert current["name"] == "module-null-sink"
                assert _module_arguments(current.get("argument", "")).get("sink_name") == private_sink
                _pactl("unload-module", str(module_id))
    assert not cleanup_errors, cleanup_errors
    assert protected_state() == before, "The original audio defaults, mute, or volume changed."
    assert {item["index"] for item in _json("list", "source-outputs")} == before_sources, "A recording stream remained open."
    after_modules = _list_modules()
    assert {item["index"] for item in after_modules} == before_modules, "A temporary audio module remained loaded."
    assert not any(identifier in item.get("argument", "") for item in after_modules)
    report["original_defaults_mute_volume_and_sources_preserved"] = True
    report["all_temporary_audio_resources_removed"] = True
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--compression", choices=("none", "minimal"), default="none")
    parser.add_argument("--tokenizer", choices=("cl100k_base", "o200k_base"))
    args = parser.parse_args()
    report = asyncio.run(check_session(args.compression, args.tokenizer))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
