import asyncio
from types import SimpleNamespace

import pytest
from aiohttp import web

from call_audio.server import CONTROLLER, local_only, shutdown


def request(method="GET", host="127.0.0.1:8765", **headers):
    return SimpleNamespace(method=method, host=host, headers=headers, app={"allowed_hosts": {"127.0.0.1:8765", "localhost:8765"}})


async def handler(req):
    return web.json_response({"ok": True})


@pytest.mark.parametrize("req", [
    request(host="attacker.example:8765"),
    request(Origin="https://attacker.example"),
    request(Origin="null"),
    request("POST"),
    request("POST", **{"Origin": "http://evil.example", "X-Call-Audio": "1"}),
])
def test_block_cross_site_and_rebinding(req):
    with pytest.raises(web.HTTPForbidden):
        asyncio.run(local_only(req, handler))


def test_local_post_requires_header_and_has_security_headers():
    response = asyncio.run(local_only(request("POST", **{"Origin": "http://127.0.0.1:8765", "X-Call-Audio": "1"}), handler))
    assert response.status == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_shutdown_stops_capture_before_sse_handler_cleanup():
    import threading
    async def check():
        subscriber = asyncio.Queue(maxsize=1)
        subscriber.put_nowait({"type": "metrics"})
        stopped = []
        async def stop():
            stopped.append(True)
        controller = SimpleNamespace(_closing=False, _stop=threading.Event(), stop=stop, subscribers={subscriber})
        await shutdown({CONTROLLER: controller})
        assert controller._closing and controller._stop.is_set() and stopped
        assert await subscriber.get() == {"type": "reconnect"}
    asyncio.run(check())
