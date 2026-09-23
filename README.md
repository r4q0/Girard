# Girard

Sales-call copilot project. Existing product context is in [context-spec.txt](context-spec.txt).

## Linux audio helper

[linux-audio-helper/](linux-audio-helper/) provides a **headless playback → English transcription → localhost API** pipeline. It captures browser/desktop call output, uses local CPU speech recognition by default, and supports optional app isolation. There is no browser UI.

```bash
cd linux-audio-helper
uv sync --locked --python 3.12 --extra dev
.venv/bin/call-audio prepare
./launch.sh --port 8766
```

Requires Linux with PipeWire's PulseAudio compatibility service (or PulseAudio), `pactl`, and libpulse. Port 8766 avoids a possible older UI instance on the default port, 8765. The launcher refuses to reuse a legacy UI instance and never terminates it. A compatible headless instance on the requested port is reused.

The API starts idle. Polling health, devices, state, transcripts, or SSE does not start capture. Start explicitly with `POST /api/start`, consume revisions through `GET /api/events` or raw text through `GET /api/transcript`, and stop with `POST /api/stop`. POST requests require `X-Call-Audio: 1`; send JSON with `Content-Type: application/json`. See the [component README](linux-audio-helper/README.md) for complete requests, session semantics, tests, and limitations.

Local mode has no STT API fees and never captures the microphone. One session is held in memory; the API consumer saves any transcript it needs before starting another. Disconnecting an API client does not stop capture. LLM triggering, retrieval, and sales reports remain outside this component.

Minimal “caveman” compression is available by adding `"compression":"minimal"` to `/api/start`; it is off by default. It removes only conservative interior `um`/`uh` fillers from finalized segments, preserves raw `text`, and supplies separate `compact_text` plus audit metadata. It makes no model calls. Read [changes, API examples, and measured performance](linux-audio-helper/README_CAVEMAN.md) before integrating: savings depend on the transcript and tokenizer, and downstream prompts should receive only one text version.

[READMEbig.md](READMEbig.md) is preserved historical documentation for the older UI prototype. Its browser instructions do not describe this headless component. Current integration evidence is in [headless-session-check.json](linux-audio-helper/reports/headless-session-check.json).
