"""Replay driver tests use tiny generated PCM16 fixtures, never actual calls."""

import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import sys
import wave

import numpy as np
import pytest


@pytest.fixture
def driver(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "scripts" / "transcribe_eval_audio.py"
    spec = importlib.util.spec_from_file_location("transcribe_eval_audio_tests", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.importlib.metadata, "version", lambda package: "test-only")
    return module


def write_wav(path, samples, *, rate=8000, width=2):
    samples = np.asarray(samples)
    if samples.ndim == 1:
        samples = samples[:, None]
    with wave.open(str(path), "wb") as recording:
        recording.setnchannels(samples.shape[1])
        recording.setsampwidth(width)
        recording.setframerate(rate)
        dtype = "<i2" if width == 2 else "u1"
        recording.writeframes(samples.astype(dtype).tobytes())
    return path


@pytest.fixture
def stereo(tmp_path):
    # Distinct channels make accidental mixing or incorrect selection visible.
    data = np.column_stack((np.full(800, 8192), np.full(800, -16384)))
    return write_wav(tmp_path / "selected.wav", data)


def item(path, **extra):
    return {"recording_id": "fixture-one", "audio_path": str(path), "channel": 1, **extra}


def transcript(identifier="one", *, text="Synthetic fixture result.", final=True, start=0):
    return {"type": "transcript", "segment_id": identifier, "text": text,
            "is_final": final, "endpoint": final, "start_ms": start, "end_ms": start + 20}


class FakeEngine:
    def __init__(self, events, output=None, *, process_failure=False):
        self.events = events
        self.output = [transcript()] if output is None else output
        self.process_failure = process_failure
        self.model = "fake-small"
        self.started = 0
        self.finished = 0
        self.closed = False
        self.chunks = []

    def start(self):
        self.started += 1

    def process(self, samples, rate):
        if self.process_failure:
            raise RuntimeError("Synthetic inference failure")
        self.chunks.append((samples.copy(), rate))

    def finish(self):
        self.finished += 1
        self.events.extend(dict(event) for event in self.output)

    def close(self):
        self.closed = True


@pytest.mark.parametrize(("channel", "expected"), [(0, 0.25), (1, -0.5)])
def test_replay_selects_exact_channel_without_mixing_and_adds_one_silent_second(driver, stereo, channel, expected):
    events = []
    engine = FakeEngine(events)
    result = driver.transcribe_recording(item(stereo, channel=channel), engine, events, realtime=False)
    supplied = np.concatenate([samples for samples, _ in engine.chunks])
    np.testing.assert_array_equal(supplied[:800], np.full(800, expected, dtype=np.float32))
    np.testing.assert_array_equal(supplied[800:], np.zeros(8000, dtype=np.float32))
    assert all(rate == 8000 and samples.ndim == 1 and samples.dtype == np.float32
               for samples, rate in engine.chunks)
    assert max(samples.size for samples, _ in engine.chunks) == 160
    assert result["sample_rate"] == 8000 and result["source_channels"] == 2
    assert result["duration_seconds"] == 0.1
    assert result["source_wav_sha256"] == hashlib.sha256(stereo.read_bytes()).hexdigest()
    assert engine.started == engine.finished == 1
    assert result["transcription"]["replay_mode"] == "as_fast_as_possible"
    assert result["transcription"]["silent_tail_seconds"] == 1


def test_excerpt_selects_only_requested_frames_and_preserves_pcm_extremes(driver, tmp_path):
    values = np.array([-32768, 32767, 10, 20, 30, 40, 50, 60], dtype=np.int16)
    path = write_wav(tmp_path / "mono.wav", values, rate=8000)
    events = []
    engine = FakeEngine(events)
    result = driver.transcribe_recording(item(path, channel=0, start_seconds=0,
                                             duration_seconds=2 / 8000), engine, events, realtime=False)
    supplied = np.concatenate([samples for samples, _ in engine.chunks])
    np.testing.assert_array_equal(supplied[:2], [-1.0, 32767 / 32768])
    assert np.all(supplied[2:] == 0)
    assert result["duration_seconds"] == 2 / 8000


@pytest.mark.parametrize("channel", [-1, 2, True, 1.0, "1", None])
def test_invalid_or_implicit_channel_never_starts_engine(driver, stereo, channel):
    events = []
    engine = FakeEngine(events)
    with pytest.raises(ValueError, match="channel"):
        driver.transcribe_recording(item(stereo, channel=channel), engine, events, realtime=False)
    assert not engine.started and not engine.chunks


def test_missing_channel_is_not_silently_selected(driver, stereo):
    events = []
    engine = FakeEngine(events)
    recording = item(stereo)
    del recording["channel"]
    with pytest.raises((KeyError, ValueError)):
        driver.transcribe_recording(recording, engine, events, realtime=False)
    assert not engine.started


@pytest.mark.parametrize("excerpt", [
    {"start_seconds": -0.1}, {"start_seconds": 0.1},
    {"duration_seconds": 0}, {"duration_seconds": -1},
    {"start_seconds": 0.05, "duration_seconds": 0.1},
    {"duration_seconds": "not-a-number"},
    {"duration_seconds": float("nan")}, {"duration_seconds": float("inf")},
    {"start_seconds": float("nan")}, {"start_seconds": float("inf")},
    {"duration_seconds": 0.000001},
    {"start_seconds": 0.1 - 0.000001, "duration_seconds": 0.000001},
])
def test_invalid_or_zero_frame_excerpt_never_starts_engine(driver, stereo, excerpt):
    events = []
    engine = FakeEngine(events)
    with pytest.raises(ValueError):
        driver.transcribe_recording(item(stereo, **excerpt), engine, events, realtime=False)
    assert not engine.started and not engine.chunks


def test_non_pcm16_input_is_rejected_before_transcription(driver, tmp_path):
    path = write_wav(tmp_path / "eight-bit.wav", np.zeros(80), width=1)
    events = []
    engine = FakeEngine(events)
    with pytest.raises(ValueError, match="PCM16"):
        driver.transcribe_recording(item(path, channel=0), engine, events, realtime=False)
    assert not engine.started


def test_only_sorted_finals_are_saved_and_previous_recording_events_are_cleared(driver, stereo):
    events = [transcript("old-recording", text="Must not leak into this recording")]
    engine = FakeEngine(events, output=[
        transcript("late", final=False, start=40),
        transcript("late", text="Late final.", start=40),
        transcript("early", text="Early final.", start=0),
    ])
    result = driver.transcribe_recording(item(stereo), engine, events, realtime=False)
    assert [segment["segment_id"] for segment in result["segments"]] == ["early", "late"]
    assert all(segment["is_final"] and segment["session_id"] == "fixture-one" for segment in result["segments"])
    assert result["transcription"]["partial_events"] == 1
    assert result["transcription"]["final_segments"] == 2
    assert all(event.get("segment_id") != "old-recording" for event in events)


@pytest.mark.parametrize(("output", "message"), [
    ([], "No finalized"),
    ([transcript(), transcript()], "Duplicate final"),
    ([transcript(), transcript("unfinished", final=False)], "provisional speech unfinished"),
    ([transcript(), {"type": "error", "message": "provider failed"}], "Transcription failed"),
])
def test_incomplete_duplicate_or_failed_transcripts_are_not_accepted(driver, stereo, output, message):
    events = []
    engine = FakeEngine(events, output)
    with pytest.raises(RuntimeError, match=message):
        driver.transcribe_recording(item(stereo), engine, events, realtime=False)
    assert engine.finished == 1


def fake_cli_engine(driver, monkeypatch, *, failure=False):
    instances = []

    def factory(emit, model):
        engine = FakeEngine([], process_failure=failure)
        engine.finish = lambda: emit(transcript())
        instances.append(engine)
        return engine

    monkeypatch.setattr(driver, "MoonshineEngine", factory)
    return instances


def invoke_main(driver, monkeypatch, manifest, output):
    monkeypatch.setattr(sys, "argv", ["transcribe_eval_audio.py", "--manifest", str(manifest), "--output", str(output)])
    driver.main()


def test_cli_reads_only_manifest_named_audio_and_never_opens_network(driver, stereo, tmp_path, monkeypatch):
    private = write_wav(tmp_path / "unlisted-private-call.wav", np.zeros(80))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"recordings": [item(stereo)], "source_note": "Locally generated test"}))
    output = tmp_path / "results" / "transcript.json"
    instances = fake_cli_engine(driver, monkeypatch)
    opened = []
    original_wave_open = wave.open

    def guarded_open(path, mode):
        resolved = Path(path).resolve()
        assert mode == "rb" and resolved == stereo.resolve()
        assert resolved != private.resolve()
        opened.append(resolved)
        return original_wave_open(path, mode)

    def no_network(*args, **kwargs):
        pytest.fail("Replay driver attempted a network connection")

    monkeypatch.setattr(driver.wave, "open", guarded_open)
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    invoke_main(driver, monkeypatch, manifest, output)
    result = json.loads(output.read_text())
    assert opened == [stereo.resolve()]
    assert instances[0].closed
    assert len(result["recordings"]) == 1
    assert result["recordings"][0]["audio_path"] == str(stereo.resolve())
    assert result["recordings"][0]["transcription"]["no_audio_upload_or_hosted_inference"] is True
    assert "not live call capture" in result["limitations"]


@pytest.mark.parametrize("failure", ["inference", "invalid-second-excerpt"])
def test_cli_closes_engine_and_does_not_write_partial_results_after_failure(driver, stereo, tmp_path, monkeypatch, failure):
    recordings = [item(stereo)]
    if failure == "invalid-second-excerpt":
        recordings.append(item(stereo, recording_id="fixture-two", duration_seconds=-1))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"recordings": recordings}))
    output = tmp_path / "failed-result.json"
    instances = fake_cli_engine(driver, monkeypatch, failure=failure == "inference")
    with pytest.raises((RuntimeError, ValueError)):
        invoke_main(driver, monkeypatch, manifest, output)
    assert instances and instances[0].closed
    assert not output.exists()


def test_cli_refuses_to_overwrite_existing_results(driver, stereo, tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"recordings": [item(stereo)]}))
    output = tmp_path / "existing.json"
    output.write_text("Existing private results")
    instances = fake_cli_engine(driver, monkeypatch)
    with pytest.raises(SystemExit) as exc:
        invoke_main(driver, monkeypatch, manifest, output)
    assert exc.value.code == 2
    assert output.read_text() == "Existing private results"
    assert not instances


def test_cli_rejects_duplicate_manifest_recording_ids_before_loading_model(driver, stereo, tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"recordings": [item(stereo), item(stereo)]}))
    output = tmp_path / "result.json"
    instances = fake_cli_engine(driver, monkeypatch)
    with pytest.raises(SystemExit) as exc:
        invoke_main(driver, monkeypatch, manifest, output)
    assert exc.value.code == 2
    assert not instances and not output.exists()
