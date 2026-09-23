"""Commands for local capture, installation checks, and reproducible STT tests."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import wave

import numpy as np


def read_wav(path):
    with wave.open(str(path), "rb") as audio:
        if audio.getsampwidth() != 2 or audio.getcomptype() != "NONE":
            raise ValueError("Use an uncompressed PCM16 WAV file (ffmpeg -i input -c:a pcm_s16le output.wav).")
        channels, rate = audio.getnchannels(), audio.getframerate()
        samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2").astype(np.float32) / 32768
    return samples.reshape(-1, channels).mean(axis=1), rate


def transcribe_file(args):
    from .engines import MoonshineEngine
    audio, rate = read_wav(args.path)
    segments, event_times, process_times = {}, [], []
    start_time = None

    def emit(event):
        if event["type"] == "transcript":
            segments[event["segment_id"]] = event
            if start_time:
                event_times.append(round((time.perf_counter() - start_time) * 1000, 1))
            if args.json:
                print(json.dumps(event), flush=True)
            elif event["is_final"]:
                print(event["text"], flush=True)
        elif event["type"] == "error":
            raise RuntimeError(event["message"])

    engine = MoonshineEngine(emit, model=args.model)
    loading = time.perf_counter()
    try:
        engine.start()
        load_seconds = time.perf_counter() - loading
        start_time = time.perf_counter()
        block = max(1, round(rate * 0.02))
        # A short tail lets VAD endpoint naturally; finish also flushes speech.
        padded = np.concatenate((audio, np.zeros(rate, dtype=np.float32)))
        for offset in range(0, len(padded), block):
            if args.realtime:
                wait = start_time + offset / rate - time.perf_counter()
                if wait > 0:
                    time.sleep(wait)
            tick = time.perf_counter()
            engine.process(padded[offset:offset + block], rate)
            process_times.append((time.perf_counter() - tick) * 1000)
        engine.finish()
        elapsed = time.perf_counter() - start_time
        metrics = {
            "type": "benchmark", "mode": "realtime" if args.realtime else "as-fast-as-possible",
            "audio_seconds": round(len(audio) / rate, 3), "load_seconds": round(load_seconds, 3),
            "processing_wall_seconds": round(elapsed, 3),
            "realtime_factor_including_tail": round(elapsed / (len(padded) / rate), 4),
            "process_call_p95_ms": round(float(np.percentile(process_times, 95)), 2),
            "process_call_max_ms": round(max(process_times), 2),
            "first_transcript_event_ms": event_times[0] if event_times else None,
            "segments": len(segments),
            "note": "Processing-call time is not end-to-end word latency; no word-aligned reference was measured.",
        }
        print(json.dumps(metrics), file=sys.stderr)
    finally:
        engine.close()


def serve(args):
    from aiohttp import web
    from .server import create_app
    url = f"http://127.0.0.1:{args.port}"
    try:
        with urllib.request.urlopen(url + "/api/health", timeout=0.5) as response:
            if json.load(response).get("app") == "call-audio-helper":
                if args.open:
                    subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print(f"Call Audio is already running at {url}")
                return
    except (OSError, ValueError):
        pass
    app = create_app(port=args.port, model=args.model)
    if args.open:
        async def open_browser(app):
            import asyncio
            async def open_later():
                await asyncio.sleep(0.5)
                subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            asyncio.create_task(open_later())
        app.on_startup.append(open_browser)
    print("Local model preloads in the background; capture remains OFF until Start.")
    print("Keep this process running. Ctrl+C stops capture and restores owned routes.")
    web.run_app(app, host="127.0.0.1", port=args.port, access_log=None)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local English transcription of Linux call playback, never the microphone.")
    commands = parser.add_subparsers(dest="command", required=True)
    server = commands.add_parser("serve", help="Run the local UI; no automatic capture")
    server.add_argument("--port", type=int, default=8765)
    server.add_argument("--open", action="store_true", help="Open the local page in your browser")
    server.add_argument("--model", choices=("tiny", "small", "medium"), default="small")
    commands.add_parser("devices", help="List playback outputs and app streams")
    commands.add_parser("doctor", help="Check dependencies and output-only audio discovery")
    prepare = commands.add_parser("prepare", help="Download the local English model; opens no audio device")
    prepare.add_argument("--model", choices=("tiny", "small", "medium"), default="small")
    transcribe = commands.add_parser("transcribe-file", help="Benchmark a supplied PCM16 WAV; opens no live audio device")
    transcribe.add_argument("path")
    transcribe.add_argument("--model", choices=("tiny", "small", "medium"), default="small")
    transcribe.add_argument("--realtime", action="store_true")
    transcribe.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "serve":
            if not 1024 <= args.port <= 65535:
                parser.error("Choose a port between 1024 and 65535.")
            serve(args)
        elif args.command in ("devices", "doctor"):
            from .audio import list_outputs, list_playback_streams
            result = {"outputs": list_outputs(), "streams": list_playback_streams()}
            if args.command == "doctor":
                result.update({"python": sys.version.split()[0], "pactl": shutil.which("pactl"), "microphone_capture": False})
            print(json.dumps(result, indent=2))
        elif args.command == "prepare":
            from .engines import prepare_model
            print(json.dumps(prepare_model(args.model), indent=2))
        elif args.command == "transcribe-file":
            transcribe_file(args)
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"Call Audio: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
