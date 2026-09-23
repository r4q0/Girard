"""Headless compression contract: no real audio, model loading, or cloud use."""

import asyncio
import json
import time
from contextlib import asynccontextmanager

import pytest
from aiohttp.test_utils import TestClient, TestServer

from call_audio import runtime
from call_audio.server import create_app


OUTPUT = {
    "id": "fake_output", "name": "Fake output", "monitor": "fake_output.monitor",
    "sample_rate": 48000, "is_default": True,
}
SETTINGS = {"sink_id": "fake_output", "engine": "local", "isolate": False}
HEADERS = {"X-Call-Audio": "1"}
RAW = "We, um, cannot pay more than 500 euros per month."


def segment(identifier="one", text=RAW, final=True, start=0):
    return {
        "type": "transcript", "segment_id": identifier, "start_ms": start,
        "end_ms": start + 500, "text": text, "is_final": final, "endpoint": final,
    }


async def until(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("Timed out waiting for fake session state")
        await asyncio.sleep(0.005)


async def next_event(response, predicate):
    async def read():
        while True:
            line = await response.content.readline()
            assert line, "SSE stream closed before the expected event"
            if line.startswith(b"data: "):
                event = json.loads(line[6:])
                if predicate(event):
                    return event
    return await asyncio.wait_for(read(), timeout=2)


@pytest.fixture
def fake_audio(monkeypatch):
    instances = {"engines": [], "sources": []}
    monkeypatch.setattr(runtime, "list_outputs", lambda: [OUTPUT])
    monkeypatch.setattr(runtime, "list_playback_streams", lambda: [])
    monkeypatch.delenv("ASSEMBLYAI_TOKEN", raising=False)
    monkeypatch.delenv("ASSEMBLYAI_API_KEY", raising=False)

    class Engine:
        def __init__(self, emit, **kwargs):
            self.emit = emit
            self.closed = False
            instances["engines"].append(self)

        def start(self):
            pass

        def process(self, samples, rate):
            raise AssertionError("These contract tests never feed or capture real audio")

        def finish(self):
            pass

        def close(self):
            self.closed = True

    class Source:
        def __init__(self, sink, receive, on_error):
            self.stopped = False
            instances["sources"].append(self)

        def start(self):
            pass

        def stop(self):
            self.stopped = True

    monkeypatch.setattr(runtime, "MoonshineEngine", Engine)
    monkeypatch.setattr(runtime, "CaptureSource", Source)
    return instances


@asynccontextmanager
async def api(controller):
    app = create_app(controller=controller, preload=False)
    async with TestClient(TestServer(app)) as client:
        app["allowed_hosts"].add(f"127.0.0.1:{client.server.port}")
        yield client


async def start(client, controller, **extra):
    response = await client.post("/api/start", json={**SETTINGS, **extra}, headers=HEADERS)
    body = await response.json()
    assert response.status == 200, body
    await until(lambda: controller.state == "listening")
    return body


def test_compression_is_off_by_default_and_raw_contract_is_unchanged(fake_audio):
    async def check():
        controller = runtime.Controller()
        assert controller.compression_mode == "none"
        assert controller._compressor is None
        async with api(controller) as client:
            await start(client, controller)
            assert controller.snapshot()["compression_mode"] == "none"
            assert controller.snapshot()["compression_tokenizer"] is None
            assert controller._compressor is None
            final = segment()
            controller._accept(controller.session_id, final)
            saved = controller.segments["one"]
            assert saved == {**final, "session_id": controller.session_id}
            transcript = await (await client.get("/api/transcript")).json()
            assert transcript["text"] == RAW
            assert "compact_text" not in transcript and "compression" not in transcript
            assert "compact_text" not in saved and "compression_ms" not in saved
            response = await client.post("/api/stop", headers=HEADERS)
            assert response.status == 200
        assert all(source.stopped for source in fake_audio["sources"])
        assert all(engine.closed for engine in fake_audio["engines"])
    asyncio.run(check())


def test_minimal_sse_retains_raw_text_and_polling_reuses_final_results(fake_audio, monkeypatch):
    async def check():
        controller = runtime.Controller()
        async with api(controller) as client:
            result = await start(client, controller, compression="minimal", protected_terms=["  Acme CRM  "])
            assert result["compression_mode"] == "minimal"
            assert controller._compressor is not None
            assert controller.snapshot()["compression_tokenizer"] is None
            calls = []
            compressor_type = type(controller._compressor)
            real_compress = compressor_type.compress

            def counted(instance, text):
                calls.append(text)
                return real_compress(instance, text)

            monkeypatch.setattr(compressor_type, "compress", counted)
            async with client.get("/api/events") as stream:
                await next_event(stream, lambda event: event["type"] == "state")
                partial = segment(text="We, um, cannot", final=False)
                fake_audio["engines"][0].emit(partial)
                partial_event = await next_event(stream, lambda event: event.get("segment_id") == "one")
                assert partial_event == {**partial, "session_id": controller.session_id}
                assert calls == []

                final = segment()
                fake_audio["engines"][0].emit(final)
                emitted = await next_event(stream, lambda event: event.get("segment_id") == "one" and event["is_final"])
                assert emitted["text"] == RAW
                assert emitted["compact_text"] != RAW
                assert "cannot pay more than 500 euros per month" in emitted["compact_text"]
                assert emitted["compression_ms"] >= 0
                metadata = emitted["compression"]
                assert {"mode", "changed", "removed_words", "rules_version", "reason", "removed_spans", "tokens"} <= metadata.keys()
                assert metadata["mode"] == "minimal" and metadata["changed"] is True
                assert metadata["removed_words"] >= 1 and metadata["removed_spans"]
                assert "compact_text" not in final  # Original provider event was not mutated.
                assert calls == [RAW]

            # An unrelated pending segment uses its raw provisional text in
            # the optional all-segments compact view.
            pending = segment(identifier="two", text="Only if approved", final=False, start=1000)
            controller._accept(controller.session_id, pending)
            for _ in range(2):
                raw = await (await client.get("/api/transcript")).json()
                assert raw["text"] == RAW
                assert raw["compact_text"] == emitted["compact_text"]
                assert raw["segments"] == [emitted]
                assert raw["compression"] == {"mode": "minimal", "tokenizer": None}
                all_segments = await (await client.get("/api/transcript?final_only=false")).json()
                assert all_segments["text"] == RAW + "\nOnly if approved"
                assert all_segments["compact_text"] == emitted["compact_text"] + "\nOnly if approved"
                assert "compact_text" not in all_segments["segments"][1]
                state = await (await client.get("/api/state")).json()
                assert state["segments"][0] == emitted
            async with client.get("/api/events") as reconnected:
                initial = await next_event(reconnected, lambda event: event["type"] == "state")
                assert initial["segments"][0] == emitted
            assert calls == [RAW]

            controller._accept(controller.session_id, {**final, "text": "A duplicate final must not overwrite raw text"})
            controller._accept(controller.session_id, partial)
            assert controller.segments["one"] == emitted
            assert calls == [RAW]
            await client.post("/api/stop", headers=HEADERS)
    asyncio.run(check())


def test_new_session_resets_compression_and_dedupe_even_after_clear(fake_audio):
    async def check():
        controller = runtime.Controller()
        async with api(controller) as client:
            await start(client, controller, compression="minimal")
            previous_session = controller.session_id
            controller._accept(previous_session, segment())
            await client.post("/api/stop", headers=HEADERS)
            response = await client.post("/api/clear", headers=HEADERS)
            assert response.status == 200 and not controller.segments
            controller._accept(previous_session, segment())
            assert not controller.segments  # Repeated final cannot resurrect a cleared segment.

            await start(client, controller)
            assert controller.session_id != previous_session
            assert controller.compression_mode == "none" and controller._compressor is None
            assert controller.snapshot()["compression_tokenizer"] is None
            controller._accept(controller.session_id, segment())
            assert controller.segments["one"]["text"] == RAW
            assert "compact_text" not in controller.segments["one"]
            await client.post("/api/stop", headers=HEADERS)

            await start(client, controller, compression="minimal")
            controller._accept(controller.session_id, segment())
            assert controller.segments["one"]["compact_text"] != RAW
            await client.post("/api/stop", headers=HEADERS)
    asyncio.run(check())


def test_compressor_failure_falls_back_to_raw_without_breaking_session(fake_audio, monkeypatch):
    async def check():
        controller = runtime.Controller()
        async with api(controller) as client:
            await start(client, controller, compression="minimal")
            calls = []

            def broken(instance, text):
                calls.append(text)
                raise RuntimeError("Synthetic compression failure")

            monkeypatch.setattr(type(controller._compressor), "compress", broken)
            controller._accept(controller.session_id, segment())
            event = controller.segments["one"]
            assert event["text"] == event["compact_text"] == RAW
            assert event["compression"]["mode"] == "minimal"
            assert event["compression"]["changed"] is False
            assert event["compression"]["removed_words"] == 0
            assert event["compression"]["removed_spans"] == []
            assert event["compression"]["reason"]
            assert event["compression_ms"] >= 0
            assert controller.state == "listening" and controller.error is None
            controller._accept(controller.session_id, segment())
            assert calls == [RAW]
            transcript = await (await client.get("/api/transcript")).json()
            assert transcript["text"] == transcript["compact_text"] == RAW
            assert calls == [RAW]
            await client.post("/api/stop", headers=HEADERS)
    asyncio.run(check())


INVALID = [
    {"compression": "aggressive"}, {"compression": None}, {"compression": True},
    {"compression": []}, {"compression": "minimal", "protected_terms": "Acme"},
    {"compression": "minimal", "protected_terms": None},
    {"compression": "minimal", "protected_terms": [2]},
    {"compression": "minimal", "protected_terms": [""]},
    {"compression": "minimal", "protected_terms": ["   "]},
    {"compression": "minimal", "protected_terms": ["x" * 129]},
    {"compression": "minimal", "protected_terms": ["Acme"] * 65},
    {"compression": "none", "protected_terms": ["Acme"]},
    {"protected_terms": ["Acme"]},
]


@pytest.mark.parametrize("invalid", INVALID)
def test_invalid_compression_returns_http_400_without_starting_capture(fake_audio, invalid):
    async def check():
        controller = runtime.Controller()
        async with api(controller) as client:
            response = await client.post("/api/start", json={**SETTINGS, **invalid}, headers=HEADERS)
            assert response.status == 400, await response.text()
            assert (await response.json())["error"]
            assert controller._task is None and controller._compressor is None
            assert not fake_audio["sources"] and not fake_audio["engines"]
    asyncio.run(check())


@pytest.mark.parametrize("invalid", INVALID)
def test_direct_controller_rejects_invalid_compression(fake_audio, invalid):
    async def check():
        controller = runtime.Controller()
        try:
            with pytest.raises(runtime.SessionError):
                await controller.start({**SETTINGS, **invalid})
            assert controller._task is None
            assert not fake_audio["sources"] and not fake_audio["engines"]
        finally:
            await controller.close()
    asyncio.run(check())


def test_explicit_none_and_empty_protected_terms_are_valid(fake_audio):
    async def check():
        controller = runtime.Controller()
        async with api(controller) as client:
            await start(client, controller, compression="none", protected_terms=[])
            assert controller._compressor is None
            await client.post("/api/stop", headers=HEADERS)
    asyncio.run(check())


def test_protected_terms_are_trimmed_and_do_not_leak_into_next_session(fake_audio):
    async def check():
        controller = runtime.Controller()
        async with api(controller) as client:
            await start(client, controller, compression="minimal", protected_terms=["  um  "])
            controller._accept(controller.session_id, segment())
            protected = await (await client.get("/api/transcript")).json()
            assert protected["compact_text"] == protected["text"] == RAW
            assert protected["segments"][0]["compression"]["reason"] == "protected_term"
            await client.post("/api/stop", headers=HEADERS)
            await start(client, controller, compression="minimal")
            controller._accept(controller.session_id, segment())
            unprotected = await (await client.get("/api/transcript")).json()
            assert unprotected["text"] == RAW and unprotected["compact_text"] != RAW
            await client.post("/api/stop", headers=HEADERS)
    asyncio.run(check())


def test_injected_tokenizer_is_exposed_without_enabling_compression_by_default(fake_audio):
    async def check():
        controller = runtime.Controller(token_counter=lambda text: len(text.split()), tokenizer_name="test-word-counter")
        async with api(controller) as client:
            await start(client, controller, compression="minimal")
            assert controller.snapshot()["compression_tokenizer"] == "test-word-counter"
            controller._accept(controller.session_id, segment())
            response = await (await client.get("/api/transcript")).json()
            assert response["compression"] == {"mode": "minimal", "tokenizer": "test-word-counter"}
            tokens = response["segments"][0]["compression"]["tokens"]
            assert tokens["tokenizer"] == "test-word-counter"
            assert tokens["raw"] == len(RAW.split())
            assert tokens["compact"] == len(response["compact_text"].split())
            assert tokens["saved"] == tokens["raw"] - tokens["compact"] > 0
            await client.post("/api/stop", headers=HEADERS)
            await start(client, controller)
            assert controller.snapshot()["compression_mode"] == "none"
            assert controller._compressor is None
            controller._accept(controller.session_id, segment())
            disabled = await (await client.get("/api/transcript")).json()
            assert "compact_text" not in disabled and "compression" not in disabled
            await client.post("/api/stop", headers=HEADERS)
    asyncio.run(check())
