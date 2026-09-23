"""Headless loopback-only transcription API; no audio/transcript persistence."""
from __future__ import annotations

import asyncio
import json
from urllib.parse import urlsplit

from aiohttp import web

from . import __version__
from .compression import RULES_VERSION
from .runtime import Controller, SessionError, validate_compression_settings

CONTROLLER = web.AppKey("controller", Controller)
SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
    "Referrer-Policy": "no-referrer",
}


@web.middleware
async def local_only(request, handler):
    # Host check also closes the usual DNS-rebinding route to localhost APIs.
    if request.host not in request.app["allowed_hosts"]:
        return web.json_response({"error": "Localhost access only."}, status=403, headers=SECURITY_HEADERS)
    origin = request.headers.get("Origin")
    if origin:
        try:
            parsed = urlsplit(origin)
        except ValueError:
            return web.json_response({"error": "Invalid Origin header."}, status=403, headers=SECURITY_HEADERS)
        if parsed.scheme != "http" or parsed.netloc != request.host:
            return web.json_response({"error": "Cross-origin requests are not allowed."}, status=403, headers=SECURITY_HEADERS)
    if request.method == "POST" and request.headers.get("X-Call-Audio") != "1":
        return web.json_response({"error": "Missing X-Call-Audio: 1 request header."}, status=403, headers=SECURITY_HEADERS)
    try:
        response = await handler(request)
    except SessionError as exc:
        response = web.json_response({"error": str(exc)}, status=409)
    except (ValueError, json.JSONDecodeError) as exc:
        response = web.json_response({"error": str(exc)}, status=400)
    except RuntimeError as exc:
        response = web.json_response({"error": str(exc)}, status=503)
    except web.HTTPException as exc:
        response = web.json_response({"error": exc.reason}, status=exc.status)
    response.headers.update(SECURITY_HEADERS)
    return response


async def state(request):
    return web.json_response(request.app[CONTROLLER].snapshot())


async def devices(request):
    return web.json_response(await request.app[CONTROLLER].devices())


async def start(request):
    if request.content_type != "application/json":
        raise ValueError("Send the start settings as application/json.")
    settings = await request.json()
    if not isinstance(settings, dict):
        raise ValueError("Expected a JSON object.")
    allowed = {"sink_id", "engine", "isolate", "stream_id", "compression", "protected_terms"}
    unknown = set(settings) - allowed
    if unknown:
        raise ValueError("Unsupported start fields: " + ", ".join(sorted(unknown)))
    if not isinstance(settings.get("sink_id"), str) or not settings["sink_id"]:
        raise ValueError("sink_id must be a non-empty playback output ID.")
    validate_compression_settings(settings)
    return web.json_response(await request.app[CONTROLLER].start(settings))


async def stop(request):
    return web.json_response(await request.app[CONTROLLER].stop())


async def clear(request):
    return web.json_response(request.app[CONTROLLER].clear())


async def health(request):
    return web.json_response({
        "app": "call-audio-helper", "version": __version__,
        "mode": "headless", "api_version": 1,
        "capabilities": {"compression": ["none", "minimal"]},
        "compression_rules_version": RULES_VERSION,
        "compression_tokenizer": request.app[CONTROLLER].tokenizer_name,
    })


async def transcript(request):
    if set(request.query) - {"final_only"}:
        raise ValueError("The only supported transcript query parameter is final_only.")
    value = request.query.get("final_only", "true")
    if value not in ("true", "false"):
        raise ValueError("final_only must be true or false.")
    return web.json_response(request.app[CONTROLLER].transcript(final_only=value == "true"))


async def events(request):
    controller = request.app[CONTROLLER]
    subscriber = asyncio.Queue(maxsize=100)
    controller.subscribers.add(subscriber)
    subscriber.put_nowait({"type": "state", **controller.snapshot()})
    response = web.StreamResponse(headers={
        **SECURITY_HEADERS,
        "Content-Type": "text/event-stream", "Cache-Control": "no-store",
        "X-Accel-Buffering": "no",
    })
    await response.prepare(request)
    try:
        while True:
            try:
                event = await asyncio.wait_for(subscriber.get(), timeout=10)
                if event["type"] == "reconnect":
                    break
                await response.write(("data: " + json.dumps(event) + "\n\n").encode())
            except asyncio.TimeoutError:
                await response.write(b": keepalive\n\n")
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    finally:
        controller.subscribers.discard(subscriber)
    return response


async def lifecycle(app):
    controller = app[CONTROLLER]
    try:
        await controller.devices()
    except RuntimeError as exc:
        controller.error = str(exc)
    preload = asyncio.create_task(controller.preload()) if app["preload"] else None
    yield
    if preload:
        await preload
    await controller.close()


async def shutdown(app):
    controller = app[CONTROLLER]
    controller._closing = True
    controller._stop.set()
    await controller.stop()
    # End SSE before aiohttp waits for active handlers during graceful exit.
    for subscriber in tuple(controller.subscribers):
        while not subscriber.empty():
            subscriber.get_nowait()
        subscriber.put_nowait({"type": "reconnect"})


def create_app(port=8765, model="small", controller=None, preload=True, token_counter=None, tokenizer_name=None):
    app = web.Application(middlewares=[local_only], client_max_size=16 * 1024)
    app[CONTROLLER] = controller or Controller(model, token_counter=token_counter, tokenizer_name=tokenizer_name)
    app["allowed_hosts"] = {f"127.0.0.1:{port}", f"localhost:{port}"}
    app["preload"] = preload
    app.cleanup_ctx.append(lifecycle)
    app.on_shutdown.append(shutdown)
    app.router.add_get("/", health)
    app.router.add_get("/api/health", health)
    app.router.add_get("/api/state", state)
    app.router.add_get("/api/devices", devices)
    app.router.add_get("/api/events", events)
    app.router.add_get("/api/transcript", transcript)
    app.router.add_post("/api/start", start)
    app.router.add_post("/api/stop", stop)
    app.router.add_post("/api/clear", clear)
    return app
