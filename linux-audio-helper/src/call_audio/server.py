"""Loopback-only UI with origin checks; no audio or transcript persistence."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import web

from .runtime import Controller, SessionError

STATIC = Path(__file__).parent / "static"
CONTROLLER = web.AppKey("controller", Controller)


@web.middleware
async def local_only(request, handler):
    # Host check also closes the usual DNS-rebinding route to localhost APIs.
    if request.host not in request.app["allowed_hosts"]:
        raise web.HTTPForbidden(text="Localhost access only.")
    origin = request.headers.get("Origin")
    if origin:
        parsed = urlsplit(origin)
        if parsed.scheme != "http" or parsed.netloc != request.host:
            raise web.HTTPForbidden(text="Cross-origin requests are not allowed.")
    if request.method == "POST" and request.headers.get("X-Call-Audio") != "1":
        raise web.HTTPForbidden(text="Missing local request header.")
    try:
        response = await handler(request)
    except SessionError as exc:
        response = web.json_response({"error": str(exc)}, status=409)
    except (ValueError, json.JSONDecodeError) as exc:
        response = web.json_response({"error": str(exc)}, status=400)
    except RuntimeError as exc:
        response = web.json_response({"error": str(exc)}, status=503)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = "default-src 'self'; connect-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


async def state(request):
    return web.json_response(request.app[CONTROLLER].snapshot())


async def devices(request):
    return web.json_response(await request.app[CONTROLLER].devices())


async def start(request):
    return web.json_response(await request.app[CONTROLLER].start(await request.json()))


async def stop(request):
    return web.json_response(await request.app[CONTROLLER].stop())


async def clear(request):
    return web.json_response(request.app[CONTROLLER].clear())


async def health(request):
    return web.json_response({"app": "call-audio-helper", "version": "0.1.0"})


async def events(request):
    controller = request.app[CONTROLLER]
    subscriber = asyncio.Queue(maxsize=100)
    controller.subscribers.add(subscriber)
    subscriber.put_nowait({"type": "state", **controller.snapshot()})
    response = web.StreamResponse(headers={
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


async def static(request):
    name = request.match_info.get("name", "index.html")
    if name not in ("index.html", "app.js", "style.css"):
        raise web.HTTPNotFound()
    return web.FileResponse(STATIC / name)


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


def create_app(port=8765, model="small", controller=None, preload=True):
    app = web.Application(middlewares=[local_only], client_max_size=16 * 1024)
    app[CONTROLLER] = controller or Controller(model)
    app["allowed_hosts"] = {f"127.0.0.1:{port}", f"localhost:{port}"}
    app["preload"] = preload
    app.cleanup_ctx.append(lifecycle)
    app.on_shutdown.append(shutdown)
    app.router.add_get("/", static)
    app.router.add_get("/api/health", health)
    app.router.add_get("/api/state", state)
    app.router.add_get("/api/devices", devices)
    app.router.add_get("/api/events", events)
    app.router.add_post("/api/start", start)
    app.router.add_post("/api/stop", stop)
    app.router.add_post("/api/clear", clear)
    app.router.add_get("/static/{name}", static)
    app.router.add_get("/{name}", static)
    return app
