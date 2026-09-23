import asyncio
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from call_audio import runtime
from call_audio.server import create_app


def setup_controller(monkeypatch):
    monkeypatch.setattr(runtime, "list_outputs", lambda: [])
    monkeypatch.setattr(runtime, "list_playback_streams", lambda: [])
    controller = runtime.Controller()
    return controller, create_app(controller=controller, preload=False)


def test_headless_routes_no_ui_or_automatic_capture(monkeypatch):
    async def check():
        controller, app = setup_controller(monkeypatch)
        async with TestClient(TestServer(app)) as client:
            app["allowed_hosts"].add(f"127.0.0.1:{client.server.port}")
            for path in ("/", "/api/health"):
                response = await client.get(path)
                assert response.content_type == "application/json"
                assert (await response.json())["mode"] == "headless"
                assert (await response.json())["api_version"] == 1
            for path in ("/static/app.js", "/static/style.css", "/index.html", "/anything"):
                response = await client.get(path)
                assert response.status == 404
                assert response.content_type == "application/json"
            response = await client.get("/api/transcript")
            assert await response.json() == {
                "session_id": None, "state": "idle", "error": None,
                "final_only": True, "has_pending": False, "complete": False,
                "text": "", "segments": [],
            }
            assert controller._task is None and controller._local is None
    asyncio.run(check())


def test_raw_transcript_snapshot_and_sse_upserts(monkeypatch):
    async def check():
        controller, app = setup_controller(monkeypatch)
        controller.session_id = "test-session"
        controller.state = "listening"
        original = "Um, we cannot pay more than 500 euros per month."
        final = {"type": "transcript", "segment_id": "1", "start_ms": 0, "end_ms": 500,
                 "text": original, "is_final": True, "endpoint": True}
        partial = {"type": "transcript", "segment_id": "2", "start_ms": 600, "end_ms": 800,
                   "text": "Only if", "is_final": False, "endpoint": False}
        controller._accept("test-session", final)
        controller._accept("test-session", partial)
        async with TestClient(TestServer(app)) as client:
            app["allowed_hosts"].add(f"127.0.0.1:{client.server.port}")
            snapshot = await (await client.get("/api/transcript")).json()
            assert snapshot["text"] == original  # Default mode never rewrites raw text.
            assert len(snapshot["segments"]) == 1
            assert snapshot["has_pending"] and not snapshot["complete"]
            all_segments = await (await client.get("/api/transcript?final_only=false")).json()
            assert all_segments["text"] == original + "\nOnly if"
            assert len(all_segments["segments"]) == 2
            async with client.get("/api/events") as stream:
                assert stream.headers["Content-Type"].startswith("text/event-stream")
                assert stream.headers["Cache-Control"] == "no-store"
                assert "frame-ancestors 'none'" in stream.headers["Content-Security-Policy"]
                import json
                initial = json.loads((await stream.content.readline())[6:])
                assert initial["type"] == "state" and initial["session_id"] == "test-session"
                await stream.content.readline()  # SSE separator.
                controller._accept("test-session", {**partial, "text": "Only if approved.", "is_final": True, "endpoint": True})
                event = json.loads((await asyncio.wait_for(stream.content.readline(), 2))[6:])
                assert event["segment_id"] == "2" and event["is_final"]
                assert event["text"] == "Only if approved."
            controller.state = "idle"
            snapshot = await (await client.get("/api/transcript")).json()
            assert snapshot["complete"] and not snapshot["has_pending"]
            assert len(snapshot["segments"]) == 2
            assert snapshot["text"] == original + "\nOnly if approved."
    asyncio.run(check())


@pytest.mark.parametrize("query", ["final_only=yes", "final_only=1", "compression=minimal"])
def test_bad_transcript_queries_fail_clearly(monkeypatch, query):
    async def check():
        _, app = setup_controller(monkeypatch)
        async with TestClient(TestServer(app)) as client:
            app["allowed_hosts"].add(f"127.0.0.1:{client.server.port}")
            response = await client.get("/api/transcript?" + query)
            assert response.status == 400 and (await response.json())["error"]
    asyncio.run(check())


def test_start_validates_json_and_compression_option(monkeypatch):
    async def check():
        controller, app = setup_controller(monkeypatch)
        controller.start = AsyncMock(return_value=controller.snapshot())
        async with TestClient(TestServer(app)) as client:
            app["allowed_hosts"].add(f"127.0.0.1:{client.server.port}")
            header = {"X-Call-Audio": "1"}
            response = await client.post("/api/start", data="not json", headers=header)
            assert response.status == 400
            response = await client.post("/api/start", data="{", headers={**header, "Content-Type": "application/json"})
            assert response.status == 400
            for body in ([], {}, {"sink_id": 12}, {"sink_id": "speaker", "compression": "aggressive"}):
                response = await client.post("/api/start", json=body, headers=header)
                assert response.status == 400 and (await response.json())["error"]
            controller.start.assert_not_awaited()
            response = await client.post("/api/start", json={"sink_id": "speaker", "engine": "local"}, headers=header)
            assert response.status == 200
            controller.start.assert_awaited_once_with({"sink_id": "speaker", "engine": "local"})
    asyncio.run(check())


def test_snapshot_error_not_mislabeled_complete(monkeypatch):
    controller, _ = setup_controller(monkeypatch)
    controller.session_id = "failed-session"
    controller.state = "error"
    controller.error = "Audio output disconnected."
    assert not controller.transcript()["complete"]
    assert controller.transcript()["error"] == "Audio output disconnected."
    asyncio.run(controller.close())
