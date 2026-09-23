import json
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from call_audio import audio


class FakePulse:
    def __init__(self):
        self.sinks = [{"index": 1, "name": "speakers", "description": "My speakers",
                       "monitor_source": "speakers.monitor", "sample_specification": "s32le 2ch 48000Hz"}]
        self.sources = [{"name": "speakers.monitor", "properties": {"device.class": "monitor"}},
                        {"name": "microphone", "properties": {"device.class": "sound"}}]
        self.streams = [{"index": 25, "sink": 1, "client": 9, "owner_module": 123,
                         "properties": {"application.name": "Browser", "media.name": "Meeting",
                                        "object.serial": "300", "application.process.id": "55"}}]
        self.modules = []
        self.calls = []
        self.fail_loopback = False

    def __call__(self, *args):
        self.calls.append(args)
        if args == ("--format=json", "info"):
            return json.dumps({"default_sink_name": "speakers"})
        if args[:2] == ("--format=json", "list"):
            return json.dumps({"sinks": self.sinks, "sources": self.sources,
                               "sink-inputs": self.streams, "modules": self.modules}[args[2]])
        if args == ("list", "short", "modules"):
            return "\n".join(f"{module['index']}\t{module['name']}\t{module['argument']}\tn/a"
                             for module in self.modules)
        if args[0] == "load-module":
            if args[1] == "module-loopback" and self.fail_loopback:
                raise audio.AudioError("loopback unavailable")
            index = 100 + len(self.modules)
            self.modules.append({"index": index, "name": args[1], "argument": " ".join(args[2:])})
            if args[1] == "module-null-sink":
                name = audio._module_arguments(" ".join(args[2:]))["sink_name"]
                self.sinks.append({"index": 2, "name": name, "description": "Isolated",
                                   "monitor_source": name + ".monitor", "sample_specification": "float32le 2ch 48000Hz"})
                self.sources.append({"name": name + ".monitor", "properties": {"device.class": "monitor"}})
            return str(index)
        if args[0] == "move-sink-input":
            stream = next(stream for stream in self.streams if stream["index"] == int(args[1]))
            stream["sink"] = next(sink["index"] for sink in self.sinks if sink["name"] == args[2])
            return ""
        if args[0] == "unload-module":
            self.modules[:] = [module for module in self.modules if module["index"] != int(args[1])]
            return ""
        raise AssertionError(f"Unexpected pactl arguments: {args}")


@pytest.fixture
def pulse(monkeypatch):
    pulse = FakePulse()
    monkeypatch.setattr(audio, "_pactl", pulse)
    return pulse


def test_outputs_require_an_explicit_verified_monitor(pulse):
    pulse.sinks.append({"index": 3, "name": "fake", "monitor_source": "microphone",
                        "sample_specification": "s16le 1ch 16000Hz"})
    assert audio.list_outputs() == [{"id": "speakers", "name": "My speakers",
                                     "monitor": "speakers.monitor", "sample_rate": 48000,
                                     "is_default": True}]


def test_streams_resolve_destination_and_hide_internal_forwarder(pulse):
    pulse.streams.append({"index": 26, "sink": 1, "properties": {"media.name": "Call_Audio_Forward"}})
    assert audio.list_playback_streams() == [{"id": 25, "name": "Meeting", "application": "Browser",
                                             "sink_id": "speakers"}]


def test_isolation_restores_previous_sink_and_unloads_only_owned_modules(pulse):
    route = audio.IsolationRoute("speakers", "call_audio_test")
    route.open()
    assert route.monitor_sink == "call_audio_test"
    route.move_stream(25)
    route.move_stream(25)
    assert pulse.streams[0]["sink"] == 2
    pulse.modules.append({"index": 800, "name": "module-null-sink", "argument": "sink_name=unrelated"})
    route.close()
    assert pulse.streams[0]["sink"] == 1
    assert [module["index"] for module in pulse.modules] == [800]
    assert ("unload-module", "101") in pulse.calls
    assert ("unload-module", "100") in pulse.calls
    assert not any("default" in command for command, *rest in pulse.calls)
    route.close()  # Idempotent.


def test_loopback_has_explicit_destination_and_cannot_follow_to_another_sink(pulse):
    route = audio.IsolationRoute("speakers", "call_audio_test")
    route.open()
    args = audio._module_arguments(pulse.modules[1]["argument"])
    assert args["source"] == "call_audio_test.monitor"
    assert args["sink"] == "speakers"
    assert args["latency_msec"] == "20"
    assert args["source_dont_move"] == args["sink_dont_move"] == "true"


def test_partial_start_rolls_back_its_sink(pulse):
    pulse.fail_loopback = True
    route = audio.IsolationRoute("speakers", "call_audio_test")
    with pytest.raises(audio.AudioError, match="loopback unavailable"):
        route.open()
    assert not pulse.modules
    assert ("unload-module", "100") in pulse.calls


def test_cleanup_respects_user_move_and_disappearing_stream(pulse):
    route = audio.IsolationRoute("speakers", "call_audio_test")
    route.open()
    route.move_stream(25)
    pulse.streams[0]["sink"] = 1
    moves_before = sum(call[0] == "move-sink-input" for call in pulse.calls)
    route.close()
    assert sum(call[0] == "move-sink-input" for call in pulse.calls) == moves_before


def test_cleanup_does_not_restore_a_reused_stream_id(pulse):
    route = audio.IsolationRoute("speakers", "call_audio_test")
    route.open()
    route.move_stream(25)
    pulse.streams[0]["properties"]["object.serial"] = "replacement"
    moves_before = sum(call[0] == "move-sink-input" for call in pulse.calls)
    route.close()
    assert sum(call[0] == "move-sink-input" for call in pulse.calls) == moves_before


def test_cleanup_does_not_unload_reused_module_id(pulse):
    route = audio.IsolationRoute("speakers", "call_audio_test")
    route.open()
    pulse.modules[1]["argument"] = "source=another.monitor sink=speakers"
    with pytest.raises(audio.AudioError, match="changed ownership"):
        route.close()
    assert not any(call == ("unload-module", "101") for call in pulse.calls)
    assert any(module["index"] == 101 for module in pulse.modules)


def test_modules_are_read_from_short_listing_because_json_can_omit_ids(pulse):
    pulse.modules = [{"index": 500, "name": "module-null-sink", "argument": "sink_name=call_audio_test"}]
    assert audio._list_modules() == pulse.modules
    assert ("--format=json", "list", "modules") not in pulse.calls


def test_malformed_module_listing_fails_closed(monkeypatch):
    monkeypatch.setattr(audio, "_pactl", lambda *args: "not an identifiable module")
    with pytest.raises(audio.AudioError, match="safely identify"):
        audio._list_modules()


def test_module_listing_handles_native_multiline_arguments_and_empty_last_module(monkeypatch):
    output = ('1\tlibpipewire-module-rt\t{\n  nice.level = -11\n\t}\t\n'
              '500\tmodule-null-sink\tsink_name=call_audio_test rate=48000\t\n'
              '501\tmodule-always-sink\t\t\n')
    monkeypatch.setattr(audio, "_pactl", lambda *args: output)
    assert audio._list_modules() == [
        {"index": 1, "name": "libpipewire-module-rt", "argument": "{\n  nice.level = -11\n\t}"},
        {"index": 500, "name": "module-null-sink", "argument": "sink_name=call_audio_test rate=48000"},
        {"index": 501, "name": "module-always-sink", "argument": ""},
    ]


def test_forwarding_stream_cannot_be_moved_into_itself(pulse):
    route = audio.IsolationRoute("speakers", "call_audio_test")
    route.open()
    pulse.streams[0]["owner_module"] = 101
    with pytest.raises(audio.AudioError, match="forwarding stream"):
        route.move_stream(25)


@pytest.mark.parametrize("target,name", [("call_audio_test", "call_audio_test"),
                                        ("speakers", "existing"),
                                        ("speakers other=bad", "call_audio_test")])
def test_invalid_and_feedback_routes_are_rejected(target, name):
    with pytest.raises(audio.AudioError):
        audio.IsolationRoute(target, name)


def test_existing_sink_is_never_overwritten(pulse):
    pulse.sinks[0]["name"] = "call_audio_test"
    route = audio.IsolationRoute("speakers", "call_audio_test")
    with pytest.raises(audio.AudioError, match="already exists"):
        route.open()
    assert not pulse.modules


def test_capture_refuses_input_or_fuzzy_fallback(pulse, monkeypatch):
    reported = []
    source = SimpleNamespace(id="microphone", isloopback=False)
    monkeypatch.setattr(audio.importlib, "import_module", lambda name: SimpleNamespace(get_microphone=lambda **kwargs: source))
    capture = audio.CaptureSource("speakers", lambda *_: pytest.fail("Unexpected microphone audio"), reported.append)
    capture.start()
    capture._thread.join(1)
    assert len(reported) == 1
    assert "exact output monitor" in str(reported[0])


def test_capture_unknown_sink_fails_before_opening_soundcard(pulse):
    capture = audio.CaptureSource("microphone", lambda *_: None, lambda *_: None)
    with pytest.raises(audio.AudioError, match="unavailable"):
        capture.start()


def test_capture_requests_mono_low_latency_and_stops_a_suspended_read(pulse, monkeypatch):
    captured = []
    errors = []
    chunk_received = threading.Event()
    requests = {}

    class Recorder:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            requests["closed"] = True

        def record(self, numframes):
            assert numframes is None
            if not captured:
                return np.array([[0.5], [2], [np.nan]], dtype=np.float32)
            self._record_event.wait(10)

    recorder = Recorder()

    def create_recorder(**kwargs):
        requests.update(kwargs)
        return recorder

    source = SimpleNamespace(id="speakers.monitor", isloopback=True, recorder=create_recorder)

    def get_microphone(**kwargs):
        requests["selection"] = kwargs
        return source

    monkeypatch.setattr(audio.importlib, "import_module", lambda name: SimpleNamespace(get_microphone=get_microphone))
    monkeypatch.setattr(audio, "_prepare_recorder", lambda recorder, stop, check_source: setattr(recorder, "_record_event", audio._InterruptibleEvent(stop, check_source)))

    def on_chunk(samples, rate):
        captured.append((samples, rate))
        chunk_received.set()

    capture = audio.CaptureSource("speakers", on_chunk, errors.append)
    capture.start()
    assert chunk_received.wait(1)
    before = time.monotonic()
    capture.stop()
    assert time.monotonic() - before < 0.5
    assert requests["channels"] == [-1]
    assert requests["blocksize"] == 960
    assert requests["selection"] == {"id": "speakers.monitor", "include_loopback": True}
    assert requests["closed"]
    assert captured[0][1] == 48000
    np.testing.assert_array_equal(captured[0][0], [0.5, 1.0, 0.0])
    assert captured[0][0].dtype == np.float32
    assert not errors


def test_recorder_adapter_sets_dont_move_without_changing_global_functions(monkeypatch):
    calls = []
    backend = SimpleNamespace(
        _pa=SimpleNamespace(PA_STREAM_ADJUST_LATENCY=0x2000),
        _pulse=SimpleNamespace(
            _pa_stream_connect_record=lambda *args: calls.append(args) or 0,
            _pa_stream_set_read_callback=lambda *args: None,
        ),
        _ffi=SimpleNamespace(callback=lambda signature: lambda func: func, NULL=None),
    )
    monkeypatch.setattr(audio.importlib, "import_module", lambda name: backend)
    recorder = SimpleNamespace(stream="stream", _id="speakers.monitor")
    audio._prepare_recorder(recorder, threading.Event())
    recorder._connect_stream("buffer")
    assert calls == [("stream", b"speakers.monitor", "buffer", 0x2200)]


def test_source_disconnection_interrupts_a_silent_read():
    def disconnected():
        raise audio.AudioError("Output disconnected")

    event = audio._InterruptibleEvent(threading.Event(), disconnected)
    started = time.monotonic()
    with pytest.raises(audio.AudioError, match="disconnected"):
        event.wait(timeout=10)
    assert time.monotonic() - started < 0.1
