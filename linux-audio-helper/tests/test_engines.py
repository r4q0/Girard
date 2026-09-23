"""No audio device, model download, cloud connection, or paid API is used here."""

import json
import queue
import threading
import time
from urllib.parse import parse_qs, urlsplit

import numpy as np
import pytest

from call_audio import engines


class FakeSocket:
    def __init__(self, model="universal-streaming-english", acknowledge=True):
        self.incoming = queue.Queue()
        self.incoming.put(json.dumps({"type": "Begin", "configuration": {"model": model}}))
        self.sent = []
        self.closed = False
        self.acknowledge = acknowledge
        self.error_on_send = None

    def recv(self, timeout=None):
        try:
            item = self.incoming.get(timeout=timeout or 2)
        except queue.Empty:
            raise TimeoutError from None
        if isinstance(item, Exception):
            raise item
        return item

    def send(self, payload):
        if self.error_on_send:
            raise self.error_on_send
        self.sent.append(payload)
        if isinstance(payload, str) and json.loads(payload)["type"] == "Terminate" and self.acknowledge:
            self.incoming.put(json.dumps(turn("last words", final=True)))
            self.incoming.put(json.dumps({"type": "Termination", "session_duration_seconds": 1.3}))

    def close(self):
        if not self.closed:
            self.closed = True
            self.incoming.put(RuntimeError("closed"))


def turn(text, final=False, order=0):
    return {"type": "Turn", "turn_order": order, "transcript": text,
            "end_of_turn": final, "words": [{"start": 123, "end": 765}]}


@pytest.fixture
def cloud(monkeypatch):
    socket = FakeSocket()
    connection = {}
    def connect(url, **kwargs):
        connection.update(url=url, **kwargs)
        return socket
    monkeypatch.setattr(engines, "_connect_websocket", connect)
    monkeypatch.delenv("ASSEMBLYAI_TOKEN", raising=False)
    monkeypatch.delenv("ASSEMBLYAI_API_KEY", raising=False)
    events = []
    engine = engines.AssemblyAIEngine(events.append, api_key="test-key", sample_rate=8000)
    yield engine, socket, events, connection
    engine.close()


def test_cloud_packet_boundaries_pcm_encoding_and_stop_flush(cloud):
    engine, socket, events, connection = cloud
    engine.start()
    samples = np.tile(np.array([-1, -.5, 0, .5, 1], dtype=np.float32), 90)
    engine.process(samples[:137], 8000)
    engine.process(samples[137:337], 8000)
    assert socket.sent == []
    engine.process(samples[337:], 8000)
    assert len(socket.sent) == 1
    assert len(socket.sent[0]) == 800  # Exactly 50ms mono PCM16 at 8kHz.
    engine.finish()
    packets = [x for x in socket.sent if isinstance(x, bytes)]
    assert [len(x) for x in packets] == [800, 800]
    decoded = np.frombuffer(b"".join(packets), dtype="<i2")
    expected = np.tile([-32768, -16384, 0, 16384, 32767], 90)
    np.testing.assert_array_equal(decoded[:450], expected)
    np.testing.assert_array_equal(decoded[450:], 0)
    assert [json.loads(x)["type"] for x in socket.sent if isinstance(x, str)] == ["ForceEndpoint", "Terminate"]
    assert socket.closed
    assert any(e.get("text") == "last words" and e["is_final"] for e in events)
    assert any(e.get("session_duration_seconds") == 1.3 for e in events)
    engine.finish()  # Idempotent; no second termination or binary packet.
    assert len(socket.sent) == 4


def test_cloud_pins_cheap_model_and_protects_credentials(cloud):
    engine, socket, events, connection = cloud
    engine.start()
    query = parse_qs(urlsplit(connection["url"]).query)
    assert query["speech_model"] == ["universal-streaming-english"]
    assert query["format_turns"] == ["false"]
    assert query["include_partial_turns"] == ["true"]
    assert query["min_turn_silence"] == ["160"]
    assert query["max_turn_silence"] == ["800"]
    assert query["sample_rate"] == ["8000"]
    assert "test-key" not in connection["url"]
    assert connection["additional_headers"] == {"Authorization": "test-key"}
    assert connection["logger"].disabled


def test_cloud_prefers_temporary_token(cloud):
    engine, socket, events, connection = cloud
    engine.token = "short-lived-token"
    engine.start()
    assert connection["additional_headers"] is None
    assert parse_qs(urlsplit(connection["url"]).query)["token"] == ["short-lived-token"]
    assert "short-lived-token" not in repr(events)


def test_cloud_turn_revisions_final_dedup_and_late_partial(cloud):
    engine, socket, events, connection = cloud
    engine._on_message(turn("we cannot"))
    engine._on_message(turn("we cannot"))
    engine._on_message(turn("we cannot commit"))
    engine._on_message(turn("we cannot commit", final=True))
    engine._on_message(turn("we cannot commit", final=True))
    engine._on_message(turn("stale partial"))
    assert [(e["text"], e["is_final"]) for e in events] == [
        ("we cannot", False), ("we cannot commit", False), ("we cannot commit", True)
    ]
    assert {e["segment_id"] for e in events} == {"0"}
    assert all(e["start_ms"] == 123 and e["end_ms"] == 765 for e in events)


def test_cloud_final_without_words_preserves_previous_timing(cloud):
    engine, socket, events, connection = cloud
    engine._on_message(turn("five hundred"))
    engine._on_message({"type": "Turn", "turn_order": 0, "transcript": "", "end_of_turn": True})
    assert events[-1]["text"] == "five hundred"
    assert events[-1]["start_ms"] == 123
    assert events[-1]["end_ms"] == 765
    assert events[-1]["is_final"]


def test_cloud_sample_rate_change_is_rejected(cloud):
    engine, socket, events, connection = cloud
    engine.start()
    with pytest.raises(ValueError, match="sample rate changed"):
        engine.process(np.zeros(400, dtype=np.float32), 16000)
    assert not socket.sent


def test_cloud_rejects_premium_model(cloud):
    engine, socket, events, connection = cloud
    socket.incoming.get_nowait()
    socket.incoming.put(json.dumps({"type": "Begin", "configuration": {"model": "universal-3-5-pro"}}))
    with pytest.raises(RuntimeError, match="unexpected model"):
        engine.start()
    assert socket.closed
    assert not any(isinstance(x, bytes) for x in socket.sent)


def test_cloud_shutdown_timeout_is_bounded(cloud):
    engine, socket, events, connection = cloud
    socket.acknowledge = False
    engine.FINISH_TIMEOUT = .02
    engine.start()
    started = time.monotonic()
    engine.finish()
    assert time.monotonic() - started < 1
    assert socket.closed
    assert any(e["type"] == "warning" for e in events)


def test_cloud_connection_exception_does_not_leak_token(monkeypatch):
    def fail(url, **kwargs):
        raise ValueError(f"failed URL {url} with private-key")
    monkeypatch.setattr(engines, "_connect_websocket", fail)
    engine = engines.AssemblyAIEngine(lambda e: None, token="secret-token")
    with pytest.raises(RuntimeError) as error:
        engine.start()
    assert "secret-token" not in str(error.value)
    assert "private-key" not in str(error.value)


def test_cloud_provider_errors_dont_echo_credentials(cloud):
    engine, socket, events, connection = cloud
    engine._on_message({"type": "Error", "error": "bad credentials: private-key and secret-token"})
    assert events[-1]["type"] == "error"
    assert "private-key" not in repr(events)
    assert "secret-token" not in repr(events)


def test_cloud_send_errors_are_redacted_and_closed(cloud):
    engine, socket, events, connection = cloud
    engine.start()
    socket.error_on_send = RuntimeError("private-key in provider close reason")
    with pytest.raises(RuntimeError) as error:
        engine.process(np.zeros(400), 8000)
    assert "private-key" not in str(error.value)
    # Shutdown must remain possible after a send failure.
    engine.close()
    assert socket.closed


def test_cloud_stalled_send_is_interrupted_by_reader_watchdog(cloud):
    from types import SimpleNamespace
    engine, socket, events, connection = cloud
    released = threading.Event()
    socket.socket = SimpleNamespace(shutdown=lambda how: released.set())
    def stalled_send(payload):
        released.wait(timeout=2)
        raise RuntimeError("private-token in transport failure")
    socket.send = stalled_send
    engine.SEND_TIMEOUT = .02
    engine.start()
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="upload stalled") as error:
        engine.process(np.zeros(400), 8000)
    assert time.monotonic() - started < 1
    assert released.is_set()
    assert "private-token" not in str(error.value)
    engine.close()
    assert socket.closed


@pytest.mark.parametrize("endpoint", [
    "ws://streaming.assemblyai.com/v3/ws", "wss://example.org/v3/ws",
    "wss://streaming.assemblyai.com/v3/ws?token=leak",
])
def test_cloud_rejects_unsafe_endpoint(endpoint):
    with pytest.raises(ValueError, match="official AssemblyAI"):
        engines.AssemblyAIEngine(lambda e: None, endpoint=endpoint)


@pytest.fixture
def local(monkeypatch):
    import moonshine_voice
    from moonshine_voice.moonshine_api import TranscriptLine
    from moonshine_voice.transcriber import LineTextChanged, LineCompleted

    instances = []

    class FakeStream:
        def __init__(self):
            self.listeners = []
            self.audio = []
            self.closed = False
        def start(self):
            pass
        def add_listener(self, listener):
            self.listeners.append(listener)
        def add_audio(self, samples, sample_rate):
            self.audio.append((samples.copy(), sample_rate))
            line = TranscriptLine("No commitment yet", .25, .5, 42, False)
            for listener in self.listeners:
                listener(LineTextChanged(line, 0))
        def stop(self):
            line = TranscriptLine("No commitment yet", .25, .6, 42, True)
            for listener in self.listeners:
                listener(LineTextChanged(line, 0))
                listener(LineCompleted(line, 0))
        def close(self):
            self.closed = True

    class FakeTranscriber:
        def __init__(self, **kwargs):
            self.options = kwargs
            self.streams = []
            self.closed = False
            instances.append(self)
        def create_stream(self, **kwargs):
            stream = FakeStream()
            self.streams.append(stream)
            return stream
        def close(self):
            self.closed = True

    monkeypatch.setattr(moonshine_voice, "Transcriber", FakeTranscriber)
    monkeypatch.setattr(engines, "prepare_model", lambda model: {
        "model": model, "language": "en", "path": "/fake/model", "architecture": "SMALL_STREAMING"
    })
    events = []
    engine = engines.MoonshineEngine(events.append)
    yield engine, events, instances
    engine.close()


def test_local_preloads_once_native_sample_rate_and_finalizes(local):
    engine, events, instances = local
    engine.start()
    assert not [e for e in events if e["type"] == "transcript"]
    assert len(instances[0].streams) == 2  # Silent warmup and new call.
    assert instances[0].streams[0].closed
    options = instances[0].options["options"]
    assert options["identify_speakers"] == "false"
    assert options["word_timestamps"] == "false"
    assert options["return_audio_data"] == "false"
    engine.process(np.zeros(960, dtype=np.float32), 48000)
    assert instances[0].streams[1].audio[-1][1] == 48000
    engine.finish()
    transcripts = [e for e in events if e["type"] == "transcript"]
    assert len(transcripts) == 2
    assert transcripts[-1]["is_final"]
    assert transcripts[-1]["start_ms"] == 250
    assert transcripts[-1]["end_ms"] == 850
    assert not instances[0].closed
    engine.start()
    assert len(instances) == 1
    assert len(instances[0].streams) == 3
    engine.process(np.zeros(960, dtype=np.float32), 48000)
    engine.finish()
    assert len([e for e in events if e["type"] == "transcript"]) == 4
    engine.close()
    assert instances[0].closed


def test_local_never_accepts_stereo(local):
    engine, events, instances = local
    engine.start()
    with pytest.raises(ValueError, match="mono"):
        engine.process(np.zeros((960, 2)), 48000)


def test_local_callback_error_reaches_worker(local):
    from moonshine_voice.transcriber import Error
    engine, events, instances = local
    engine.start()
    engine._on_event(Error(ValueError("native failure"), 0))
    with pytest.raises(RuntimeError, match="Local transcription failed"):
        engine.process(np.zeros(960), 48000)
    with pytest.raises(RuntimeError):
        engine.finish()
    assert instances[0].streams[-1].closed
    assert any(e["type"] == "error" for e in events)


def test_prepare_model_pins_small_english_and_reuses_download(monkeypatch):
    import moonshine_voice
    calls = []
    def get_model(language, **kwargs):
        calls.append((language, kwargs))
        return "/fake/cache/small", moonshine_voice.ModelArch.SMALL_STREAMING
    monkeypatch.setattr(moonshine_voice, "get_model_for_language", get_model)
    engines._model_files.cache_clear()
    try:
        assert engines.prepare_model() == {
            "model": "small", "language": "en", "path": "/fake/cache/small",
            "architecture": "SMALL_STREAMING",
        }
        engines.prepare_model()
        assert len(calls) == 1
        assert calls[0][0] == "en"
        assert calls[0][1] == {
            "wanted_model_arch": moonshine_voice.ModelArch.SMALL_STREAMING,
            "include_word_timestamps": False,
        }
    finally:
        engines._model_files.cache_clear()


def test_mono_replaces_nonfinite_without_modifying_input():
    original = np.array([np.nan, np.inf, -np.inf, .3], dtype=np.float32)
    output = engines._mono(original, 48000)
    np.testing.assert_allclose(output, [0, 1, -1, .3])
    assert np.isnan(original[0])
