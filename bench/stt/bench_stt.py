# /// script
# requires-python = ">=3.11"
# dependencies = ["sherpa-onnx>=1.13", "numpy", "soundfile", "jiwer"]
# ///
"""Benchmark local STT models on this machine, simulating a live call.

Chunk models: silero VAD cuts at each pause, or at 5 s max; we time each decode.
Streaming models: 100 ms chunks in; we time compute per chunk and read the text at each endpoint.
Usage: uv run bench/stt/bench_stt.py   (writes bench/stt/results.json and bench/stt-results.md)
"""
import json
import re
import statistics
import time
from pathlib import Path

import jiwer
import numpy as np
import sherpa_onnx
import soundfile as sf

HERE = Path(__file__).resolve().parent
MODELS = HERE / "models"
AUDIO = HERE / "audio"
SR = 16000
THREADS = 4
MAX_CHUNK_S = 5.0


def one(d, pattern):
    hits = sorted(d.glob(pattern))
    if not hits:
        raise FileNotFoundError(f"{pattern} in {d}")
    int8 = [h for h in hits if "int8" in h.name]
    return str((int8 or hits)[0])


def offline(name):
    d = MODELS / name
    tok = str(d / "tokens.txt")
    if "moonshine" in name:
        return sherpa_onnx.OfflineRecognizer.from_moonshine_v2(
            encoder=one(d, "encoder*"), decoder=one(d, "decoder*"), tokens=tok, num_threads=THREADS)
    if "whisper" in name:
        return sherpa_onnx.OfflineRecognizer.from_whisper(
            encoder=one(d, "*encoder*.onnx"), decoder=one(d, "*decoder*.onnx"), tokens=one(d, "*tokens.txt"),
            language="en", task="transcribe", num_threads=THREADS)
    return sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=one(d, "encoder*.onnx"), decoder=one(d, "decoder*.onnx"), joiner=one(d, "joiner*.onnx"),
        tokens=tok, num_threads=THREADS, model_type="nemo_transducer")


def online(name):
    d = MODELS / name
    return sherpa_onnx.OnlineRecognizer.from_transducer(
        tokens=str(d / "tokens.txt"), encoder=one(d, "encoder*.onnx"), decoder=one(d, "decoder*.onnx"),
        joiner=one(d, "joiner*.onnx"), num_threads=THREADS, enable_endpoint_detection=True,
        rule1_min_trailing_silence=1.0, rule2_min_trailing_silence=0.5, rule3_min_utterance_length=MAX_CHUNK_S)


def vad():
    cfg = sherpa_onnx.VadModelConfig()
    cfg.silero_vad.model = str(MODELS / "silero_vad.onnx")
    cfg.silero_vad.min_silence_duration = 0.5
    cfg.silero_vad.max_speech_duration = MAX_CHUNK_S
    cfg.sample_rate = SR
    return sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=60)


def run_offline(rec, samples):
    v = vad()
    texts, decode = [], []
    def drain():
        while not v.empty():
            seg = np.array(v.front.samples, dtype=np.float32)
            v.pop()
            t = time.perf_counter()
            s = rec.create_stream()
            s.accept_waveform(SR, seg)
            rec.decode_stream(s)
            decode.append(time.perf_counter() - t)
            texts.append(s.result.text.strip())
    for i in range(0, len(samples), 512):
        v.accept_waveform(samples[i:i + 512])
        drain()
    v.flush()
    drain()
    return texts, decode


def run_online(rec, samples):
    s = rec.create_stream()
    texts, per_chunk, finals = [], [], []
    step = int(0.1 * SR)
    for i in range(0, len(samples) + SR, step):
        chunk = samples[i:i + step] if i < len(samples) else np.zeros(step, dtype=np.float32)
        t = time.perf_counter()
        s.accept_waveform(SR, chunk)
        while rec.is_ready(s):
            rec.decode_stream(s)
        endpoint = rec.is_endpoint(s)
        if endpoint:
            text = rec.get_result(s).strip()
            if text:
                texts.append(text)
            rec.reset(s)
        dt = time.perf_counter() - t
        per_chunk.append(dt)
        if endpoint:
            finals.append(dt)
    return texts, per_chunk, finals


NUMBERS = {"three": "3", "twenty": "20", "forty": "40", "sixty": "60", "two": "2"}


def norm(t):
    t = t.lower().replace("-", " ").replace("’", "'").replace("web shop", "webshop").replace("flow base", "flowbase")
    t = re.sub(r"[^a-z0-9' ]", " ", t)
    return " ".join(NUMBERS.get(w, w) for w in t.split())


def size_mb(name):
    return round(sum(f.stat().st_size for f in (MODELS / name).rglob("*") if f.is_file() and "test_wav" not in str(f)) / 1e6)


def main():
    reference = norm(" ".join(json.loads((AUDIO / "reference.json").read_text(encoding="utf-8-sig"))))
    voices = sorted(AUDIO.glob("*.wav"))
    names = sorted(p.name for p in MODELS.iterdir() if p.is_dir())
    results = []
    for name in names:
        streaming = "streaming" in name and "non-streaming" not in name
        t = time.perf_counter()
        rec = online(name) if streaming else offline(name)
        load = time.perf_counter() - t
        wers, lat, worst, rtf, hyps = [], [], [], [], {}
        for wav in voices:
            samples, sr = sf.read(wav, dtype="float32")
            assert sr == SR
            t = time.perf_counter()
            if streaming:
                texts, per_chunk, finals = run_online(rec, samples)
                lat += finals or per_chunk
            else:
                texts, decode = run_offline(rec, samples)
                lat += decode
            rtf.append((time.perf_counter() - t) / (len(samples) / SR))
            hyp = norm(" ".join(texts))
            hyps[wav.stem] = " | ".join(texts)
            wers.append(jiwer.wer(reference, hyp))
        results.append({
            "model": name, "streaming": streaming, "size_mb": size_mb(name), "load_s": round(load, 2),
            "wer": round(statistics.mean(wers) * 100, 1), "wer_by_voice": dict(zip([v.stem for v in voices], [round(w * 100, 1) for w in wers])),
            "latency_ms_avg": round(statistics.mean(lat) * 1000), "latency_ms_max": round(max(lat) * 1000),
            "rtf": round(statistics.mean(rtf), 3), "hyps": hyps,
        })
        print(json.dumps({k: v for k, v in results[-1].items() if k != "hyps"}), flush=True)
    (HERE / "results.json").write_text(json.dumps(results, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
