"""Inspect the idle control page through an already running, isolated CDP browser.

This check never starts audio capture. Example:
    .venv/bin/python scripts/check_ui.py --debug-port 9777
"""

from __future__ import annotations

import argparse
import base64
import json
import time
import urllib.request
from pathlib import Path

from websockets.sync.client import connect


def read_json(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--debug-port", type=int, default=9777)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--screenshot", default="reports/control-page.png")
    args = parser.parse_args()
    before = read_json(f"{args.url}/api/state")
    if before["state"] != "idle":
        raise RuntimeError("UI verification requires an idle helper; no active call is touched.")
    tabs = read_json(f"http://127.0.0.1:{args.debug_port}/json/list")
    page = next(tab for tab in tabs if tab["type"] == "page")
    errors = []
    capture_requests = []
    serial = 0
    with connect(page["webSocketDebuggerUrl"], open_timeout=5) as ws:
        def command(method, params=None):
            nonlocal serial
            serial += 1
            current = serial
            ws.send(json.dumps({"id": current, "method": method, "params": params or {}}))
            while True:
                message = json.loads(ws.recv(timeout=10))
                event = message.get("method")
                details = message.get("params", {})
                if event == "Runtime.exceptionThrown":
                    errors.append(details)
                elif event == "Runtime.consoleAPICalled" and details.get("type") == "error":
                    errors.append(details)
                elif event == "Log.entryAdded" and details.get("entry", {}).get("level") == "error":
                    errors.append(details)
                elif event == "Network.requestWillBeSent":
                    request = details.get("request", {})
                    if request.get("method") == "POST" and request.get("url", "").endswith("/api/start"):
                        capture_requests.append(request)
                if message.get("id") == current:
                    if "error" in message:
                        raise RuntimeError(message["error"])
                    return message.get("result", {})

        def evaluate(expression):
            result = command("Runtime.evaluate", {
                "expression": expression, "returnByValue": True, "awaitPromise": True,
            })
            if "exceptionDetails" in result:
                raise RuntimeError(result["exceptionDetails"])
            return result.get("result", {}).get("value")

        for domain in ("Page", "Runtime", "Log", "Network"):
            command(f"{domain}.enable")
        command("Emulation.setDeviceMetricsOverride", {
            "width": 1440, "height": 1080, "deviceScaleFactor": 1, "mobile": False,
        })
        command("Page.navigate", {"url": args.url})
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            ready = evaluate("document.readyState === 'complete' && document.getElementById('connection-status')?.textContent === 'Helper connected'")
            if ready:
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("Control page did not connect within 15 seconds.")
        result = evaluate("""(() => {
          const output = document.getElementById('output-device');
          const local = document.querySelector('input[name="engine"][value="local"]');
          const cloud = document.querySelector('input[name="engine"][value="cloud"]');
          const start = document.getElementById('start-button');
          const initial = {title: document.title, state: document.getElementById('state-label').textContent,
            engine: local.checked ? 'local' : 'cloud', startEnabled: !start.disabled,
            outputs: [...output.options].map(option => ({value: option.value, name: option.textContent})),
            selectedOutput: output.value, transcriptSegments: document.getElementById('transcript-list').children.length,
            desktopOverflow: document.documentElement.scrollWidth > innerWidth};
          cloud.checked = true; cloud.dispatchEvent(new Event('change', {bubbles: true}));
          initial.cloudStartDisabled = start.disabled;
          initial.cloudMessage = document.getElementById('engine-help').textContent;
          local.checked = true; local.dispatchEvent(new Event('change', {bubbles: true}));
          return initial;
        })()""")
        assert result["engine"] == "local", result
        assert result["state"] == "Ready", result
        assert result["startEnabled"], result
        assert result["selectedOutput"], result
        assert not result["desktopOverflow"], result
        if not before["cloud_configured"]:
            assert result["cloudStartDisabled"], result
        command("Emulation.setDeviceMetricsOverride", {
            "width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": False,
        })
        evaluate("new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
        result["mobileOverflow"] = evaluate("document.documentElement.scrollWidth > innerWidth")
        assert not result["mobileOverflow"], result
        command("Emulation.setDeviceMetricsOverride", {
            "width": 1440, "height": 1080, "deviceScaleFactor": 1, "mobile": False,
        })
        evaluate("new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
        screenshot = command("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True})
        output_path = Path(args.screenshot)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(base64.b64decode(screenshot["data"]))
        after = read_json(f"{args.url}/api/state")
        assert after["state"] == "idle" and after["session_id"] == before["session_id"], after
        assert not capture_requests, "The page attempted to start audio automatically."
        assert not errors, errors
        result.update({"consoleErrors": errors, "automaticCaptureRequests": len(capture_requests),
                       "screenshot": str(output_path.resolve()), "serverRemainsIdle": True})
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
