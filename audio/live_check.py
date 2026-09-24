"""End-to-end check: run the sidecar, play a test call through the default speakers, print what comes back.
Run: uv run live_check.py [path/to.wav]"""
import json, subprocess, sys, threading, time
from pathlib import Path
import numpy as np, soundcard, soundfile as sf

wav = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parents[1] / "bench/stt/audio/zira.wav")
p = subprocess.Popen([sys.executable, "-m", "girard_audio"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     text=True, encoding="utf-8", cwd=Path(__file__).parent)
events = []
def read():
    for line in p.stdout:
        e = json.loads(line); e["_t"] = time.monotonic(); events.append(e)
        if e["type"] not in ("level",):
            print(f"{e['type']:8}", {k: v for k, v in e.items() if k not in ("type", "_t")}, flush=True)
threading.Thread(target=read, daemon=True).start()
def send(**c): p.stdin.write(json.dumps(c) + "\n"); p.stdin.flush()
while not any(e["type"] in ("ready", "error") for e in events): time.sleep(0.1)
send(cmd="devices"); time.sleep(0.5)
dev = next(d for d in next(e for e in events if e["type"] == "devices")["devices"] if d["default"])
send(cmd="start", device=dev["id"], names=["Zapier", "Flowbase", "Exact", "Koref"]); time.sleep(1)
audio, sr = sf.read(wav, dtype="float32")
t0 = time.monotonic()
soundcard.default_speaker().play(audio, samplerate=sr)
time.sleep(3)
send(cmd="stop"); time.sleep(2); send(cmd="quit"); p.wait(timeout=10)
lines = [e for e in events if e["type"] == "line"]
levels = [e for e in events if e["type"] == "level"]
print(f"\n{len(lines)} lines, {len(levels)} level events, stt_ms avg {np.mean([l['stt_ms'] for l in lines if l['stt_ms']]):.0f}, "
      f"filter_us max {max(l['filter_us'] for l in lines)}")
