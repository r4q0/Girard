import asyncio
import threading
import time

import numpy as np
import pytest

from call_audio import runtime


OUTPUT = {"id": "test_output", "name": "Test", "monitor": "test_output.monitor", "sample_rate": 48000, "is_default": True}
SETTINGS = {"sink_id": "test_output", "engine": "local", "isolate": False}


@pytest.fixture
def fakes(monkeypatch):
    instances = {"engines": [], "sources": [], "routes": []}
    monkeypatch.setattr(runtime, "list_outputs", lambda: [OUTPUT])
    monkeypatch.setattr(runtime, "list_playback_streams", lambda: [{"id": 1, "sink_id": "test_output"}])
    monkeypatch.delenv("ASSEMBLYAI_TOKEN", raising=False)
    monkeypatch.delenv("ASSEMBLYAI_API_KEY", raising=False)

    class Engine:
        gate = None
        def __init__(self, emit, **kwargs):
            self.emit, self.finished, self.closed = emit, 0, False
            self.frames = 0
            instances["engines"].append(self)
        def start(self):
            if self.gate:
                self.gate.wait(3)
        def process(self, samples, rate):
            self.frames += len(samples)
            self.emit({"type": "transcript", "segment_id": "1", "start_ms": 0, "end_ms": 20, "text": "Hello", "is_final": False, "endpoint": False})
        def finish(self):
            self.finished += 1
            if self.frames:
                self.emit({"type": "transcript", "segment_id": "1", "start_ms": 0, "end_ms": 20, "text": "Hello.", "is_final": True, "endpoint": True})
        def close(self):
            self.closed = True

    class Source:
        def __init__(self, sink, receive, error):
            self.sink, self.receive, self.error = sink, receive, error
            self.stopped = False
            instances["sources"].append(self)
        def start(self):
            self.receive(np.zeros(960, dtype=np.float32), 48000)
        def stop(self):
            self.stopped = True

    class Route:
        def __init__(self, target_sink):
            self.monitor_sink = "call_audio_test"
            self.closed = False
            instances["routes"].append(self)
        def open(self):
            pass
        def move_stream(self, stream_id):
            self.stream_id = stream_id
        def close(self):
            self.closed = True

    monkeypatch.setattr(runtime, "MoonshineEngine", Engine)
    monkeypatch.setattr(runtime, "CaptureSource", Source)
    monkeypatch.setattr(runtime, "IsolationRoute", Route)
    return instances, Engine, Source


async def until(predicate, seconds=3):
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("Timed out waiting for controller state")
        await asyncio.sleep(0.01)


def test_explicit_start_stop_flush_and_reuse(fakes):
    instances, _, _ = fakes
    async def check():
        controller = runtime.Controller()
        await controller.preload()
        assert not instances["sources"]
        for _ in range(2):
            await controller.start(SETTINGS)
            await until(lambda: controller.state == "listening" and controller.segments)
            await controller.stop()
            assert controller.state == "idle"
            assert controller.segments["1"]["text"] == "Hello."
            assert controller.segments["1"]["is_final"]
            assert controller.snapshot()["estimated_cost_usd"] == 0
        assert len(instances["engines"]) == 1
        assert all(s.stopped for s in instances["sources"])
        await controller.close()
        assert instances["engines"][0].closed
    asyncio.run(check())


def test_reject_microphone_and_unconfigured_cloud(fakes):
    async def check():
        controller = runtime.Controller()
        with pytest.raises(runtime.SessionError, match="microphones"):
            await controller.start({**SETTINGS, "sink_id": "microphone"})
        with pytest.raises(runtime.SessionError, match="not configured"):
            await controller.start({**SETTINGS, "engine": "cloud"})
        with pytest.raises(runtime.SessionError, match="select its playback"):
            await controller.start({**SETTINGS, "isolate": True, "stream_id": 999})
        await controller.close()
    asyncio.run(check())


def test_duplicate_start_and_stale_events(fakes):
    async def check():
        controller = runtime.Controller()
        results = await asyncio.gather(controller.start(SETTINGS), controller.start(SETTINGS), return_exceptions=True)
        assert sum(isinstance(r, runtime.SessionError) for r in results) == 1
        await until(lambda: controller.state == "listening")
        controller._accept("old-session", {"type": "transcript", "text": "WRONG"})
        assert all(e["text"] != "WRONG" for e in controller.segments.values())
        with pytest.raises(runtime.SessionError):
            controller.clear()
        await controller.stop()
        controller.clear()
        assert not controller.segments
        await controller.close()
    asyncio.run(check())


def test_isolation_cleanup_on_capture_error(fakes):
    instances, _, _ = fakes
    async def check():
        controller = runtime.Controller()
        await controller.start({**SETTINGS, "isolate": True, "stream_id": 1})
        await until(lambda: controller.state == "listening")
        assert instances["sources"][0].sink == "call_audio_test"
        instances["sources"][0].error(RuntimeError("output removed"))
        await until(lambda: controller.state == "error")
        assert controller.error == "output removed"
        assert instances["routes"][0].closed
        assert instances["sources"][0].stopped
        await controller.close()
    asyncio.run(check())


def test_stop_while_loading_opens_no_capture(fakes):
    instances, engine, _ = fakes
    engine.gate = threading.Event()
    async def check():
        controller = runtime.Controller()
        await controller.start(SETTINGS)
        await until(lambda: instances["engines"])
        stop = asyncio.create_task(controller.stop())
        await asyncio.sleep(0.01)
        engine.gate.set()
        await stop
        assert controller.state == "idle"
        assert not instances["sources"]
        await controller.close()
    asyncio.run(check())


def test_backlog_is_explicit_error_not_silent_drop(fakes, monkeypatch):
    instances, _, source = fakes
    monkeypatch.setattr(source, "start", lambda self: self.receive(np.zeros(96000, dtype=np.float32), 48000))
    async def check():
        controller = runtime.Controller()
        await controller.start(SETTINGS)
        await until(lambda: controller.state == "error")
        assert "backlog" in controller.error
        assert instances["sources"][0].stopped
        await controller.close()
    asyncio.run(check())


def test_slow_browser_resynchronizes(fakes):
    async def check():
        controller = runtime.Controller()
        subscriber = asyncio.Queue(maxsize=1)
        controller.subscribers.add(subscriber)
        controller.publish({"type": "metrics"})
        controller.publish({"type": "metrics"})
        assert await subscriber.get() == {"type": "reconnect"}
        assert subscriber not in controller.subscribers
        await controller.close()
    asyncio.run(check())


def test_previous_capture_callback_cannot_stop_next_session(fakes):
    instances, _, _ = fakes
    async def check():
        controller = runtime.Controller()
        try:
            await controller.start(SETTINGS)
            await until(lambda: controller.state == "listening")
            previous = instances["sources"][0]
            await controller.stop()
            await controller.start(SETTINGS)
            await until(lambda: controller.state == "listening")
            previous.error(RuntimeError("late old source failure"))
            await asyncio.sleep(0.05)
            assert not controller._stop.is_set()
            assert controller.state == "listening"
            assert controller.error is None
        finally:
            await controller.close()
    asyncio.run(check())


def test_stop_during_route_setup_never_opens_capture(fakes, monkeypatch):
    instances, _, _ = fakes
    opened, release = threading.Event(), threading.Event()
    def open_route(self):
        opened.set()
        release.wait(3)
    monkeypatch.setattr(runtime.IsolationRoute, "open", open_route)
    async def check():
        controller = runtime.Controller()
        try:
            await controller.start({**SETTINGS, "isolate": True, "stream_id": 1})
            await until(opened.is_set)
            stop = asyncio.create_task(controller.stop())
            await asyncio.sleep(0.01)
            release.set()
            await stop
            assert not instances["sources"]
            assert instances["routes"][0].closed
        finally:
            release.set()
            await controller.close()
    asyncio.run(check())
