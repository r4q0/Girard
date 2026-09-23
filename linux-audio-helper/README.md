# Call Audio — headless Linux API

Josef's playback → English speech-to-text → API component. It captures call audio output and runs Moonshine Small Streaming locally on CPU by default. It never captures the microphone. There is no browser UI, automatic recording, LLM invocation, or sales-report generation. Optional minimal “caveman” compression provides a compact copy of final text; the original transcript is always retained.

## Run the helper

Requirements: Linux with PipeWire's PulseAudio compatibility service (or PulseAudio), `pactl`, libpulse, Python 3.12, and `uv`. Audio integration tests also require `pacat`. Keep the existing audio server; do not start a competing PulseAudio daemon.

From this directory:

```bash
uv sync --locked --python 3.12 --extra dev
.venv/bin/call-audio prepare
./launch.sh --port 8766
```

The API binds to `127.0.0.1`. Port 8765 is the default; the example uses 8766 to avoid an older desktop/UI helper that may still occupy 8765. If the health response identifies a legacy UI or a headless instance without compression support, the launcher reports the conflict and leaves it untouched. Choose another port or stop that instance yourself. A compatible headless API already using the requested port is reused; an explicitly requested tokenizer must also match that instance.

The model preloads, but capture stays **off** until an explicit `POST /api/start`. No login autostart or system-wide audio-default change is installed. Ctrl+C stops capture and restores owned temporary routes.

## Capture and retrieve text

In another terminal, inspect health and available playback outputs:

```bash
api_base=http://127.0.0.1:8766
curl --fail-with-body -sS "$api_base/api/health"
curl --fail-with-body -sS "$api_base/api/devices"
```

Health includes `"mode":"headless"`, `"api_version":1`, and `"capabilities":{"compression":["none","minimal"]}`. Devices returns `outputs` and `streams`. Choose the `id` of the output your call uses and substitute it below. Every POST requires `X-Call-Audio: 1`; send JSON with `Content-Type: application/json`.

```bash
curl --fail-with-body -sS "$api_base/api/start" \
  -H 'X-Call-Audio: 1' -H 'Content-Type: application/json' \
  -d '{"sink_id":"PASTE_AN_OUTPUT_ID_FROM_DEVICES","engine":"local","isolate":false}'
```

This captures all playback on that output, including notifications. To isolate a call stream, first make the app produce audio, fetch `/api/devices`, and start with `"isolate":true` and its integer `"stream_id"`. A temporary virtual output forwards that stream to the chosen output. Stop restores its previous destination. Browser tabs may share one playback stream; use a separate call-browser instance when isolation matters.

For live events, run this in a separate consumer terminal:

```bash
curl --fail-with-body -N http://127.0.0.1:8766/api/events
```

Retrieve text or inspect progress without changing capture:

```bash
curl --fail-with-body -sS "$api_base/api/transcript"
curl --fail-with-body -sS "$api_base/api/transcript?final_only=false"
curl --fail-with-body -sS "$api_base/api/state"
```

Stop explicitly, then retrieve the final snapshot:

```bash
curl --fail-with-body -sS "$api_base/api/stop" \
  -H 'X-Call-Audio: 1' -H 'Content-Type: application/json' -d '{}'
curl --fail-with-body -sS "$api_base/api/state"
curl --fail-with-body -sS "$api_base/api/transcript"
```

Stop flushes captured speech. It can return `"state":"stopping"` while work completes; poll `/api/state` until idle or error before treating the transcript as finished. Closing an SSE connection, stopping `curl`, or disconnecting any client **does not stop capture**. Use `/api/stop` or Ctrl+C in the helper's terminal.

## API contract

| Endpoint | Behavior |
| --- | --- |
| `GET /` or `/api/health` | JSON health, including headless mode and API version. |
| `GET /api/devices` | Refresh available output monitors and playback streams. |
| `GET /api/state` | Session state, segments, device lists, model readiness, errors, and metrics. |
| `POST /api/start` | Start with `sink_id`, `engine` (`local` or `cloud`), optional `isolate`/`stream_id`, `compression` (`none` or `minimal`), and `protected_terms`. |
| `GET /api/events` | SSE beginning with a full state snapshot, then transcript/state/metric/error/warning events. |
| `GET /api/transcript` | Raw finalized STT text and segments, plus `compact_text` in minimal mode; `final_only=false` includes provisional text. |
| `POST /api/stop` | Stop capture and flush pending transcription. |
| `POST /api/clear` | Clear the transcript while stopped; active sessions reject this request. |

Static/browser routes return 404. The API checks Host and any supplied Origin; cross-origin access is not enabled. Local software with access to this account remains within the trust boundary.

Transcript SSE events contain `session_id`, `segment_id`, `start_ms`, `end_ms`, `text`, `is_final`, and `endpoint`. **Upsert by `(session_id, segment_id)`**; replace provisional text as it changes instead of appending every event. Discard events from previous sessions. After a disconnect, reconnect for a fresh state snapshot; SSE is not a durable event log. State and error events tell the consumer whether capture is still running or ended unsuccessfully. Surface warnings, including a missing cloud termination acknowledgement, to the caller.

`/api/transcript` returns `session_id`, `state`, `error`, `final_only`, `has_pending`, `complete`, `text`, and `segments`. Its `text` joins selected segments in timestamp order with newlines, preserving the recognizer's words. `has_pending` describes all segments, even when provisional ones are excluded. `complete` is true only for an existing session that is idle, has no error, and has no pending segments; it does not certify recognition accuracy. A fresh, never-started helper is not a completed session.

There is one in-memory session, with no audio files, transcript database, or server-side export. The caller saves any text it needs. Starting the next session clears the previous transcript; process exit also loses it. GET polling and SSE subscriptions never start capture.

## Processing and cost

```text
Validated playback monitor
  → requested 20 ms mono buffers at the output's native sample rate
  → bounded worker queue
  → preloaded English Moonshine on CPU
  → unchanged partial revisions / optional local compaction of final segments
  → raw text + optional compact copy over localhost HTTP/SSE
```

The capture stream is pinned: disappearing headphones cannot silently fall back to a microphone. Capture and inference run separately. A backlog exceeding 1.5 seconds stops with an error instead of silently dropping speech. Additional denoising, echo cancellation, lossy compression, and LLM cleanup are absent.

Local mode costs **$0 in STT API fees** and uses CPU/battery. Models are cached in `~/.cache/moonshine_voice/`; dependencies live in this project's `.venv`. Queue and processing times measure individual audio chunks, not end-to-end word latency. In cloud mode, processing time measures client packet handling/sending, not the provider's inference latency. Your own voice normally is not present in remote playback and is therefore absent from this transcript. English is the only language enabled here.

Cloud is optional. Set `ASSEMBLYAI_TOKEN` or `ASSEMBLYAI_API_KEY` in the server environment and explicitly start with `"engine":"cloud"`; no credential field is accepted in `/api/start`. Prefer a short-lived backend-issued token for a team deployment. A single-use temporary token needs replacement for a subsequent session.

The cloud adapter uses AssemblyAI's EU endpoint, explicitly selects `universal-streaming-english`, sends 50 ms mono PCM16 packets, and requests partials. Stop requests finalization and termination, then closes the connection with bounded waits. Cloud transport has mock coverage; it has not been verified with a paid live session. The estimate uses **$0.15 per connected hour**, including silence; it is not an invoice. Verify [current provider pricing](https://www.assemblyai.com/pricing) before opting in. No paid account or API credential was created.

## Verification and measurements

From this component directory:

```bash
.venv/bin/call-audio doctor
.venv/bin/call-audio devices
.venv/bin/python -m pytest -q
.venv/bin/python scripts/check_transcription.py
.venv/bin/python scripts/check_capture.py
.venv/bin/python scripts/check_session.py --report reports/headless-session-check.json
```

Integration checks use recorded narration from the installed Moonshine test fixture and private virtual audio outputs, never a real call or microphone. They restore owned routes and check original audio settings.

The [current headless integration report](reports/headless-session-check.json) verifies HTTP → private output capture → STT → SSE and finalized transcript JSON. Its recorded run produced 36 partial events and 5 final segments. Stop flushed the pending segment and returned idle in approximately 177 ms; no cloud or physical playback was used, and temporary audio resources were removed. This is a short functional check, not a word-latency or full-call accuracy benchmark.

Earlier prototype measurements on an AMD Ryzen 7 250, 30 GiB RAM, Linux/PipeWire: 24 seconds of narration plus a silent tail processed in 9.07 seconds when fed as fast as possible. Real-time replay had 91 ms p95 per-feed processing time; cached loading took 0.14–0.27 seconds. These historical results are in [local-benchmark.json](reports/local-benchmark.json), [capture-check.json](reports/capture-check.json), and the older [session-check.json](reports/session-check.json). They are not a new headless latency benchmark. Validate prices, names, accents, interruptions, and long calls on representative audio.

Benchmark a PCM16 WAV you intentionally supply, without opening live capture:

```bash
.venv/bin/call-audio transcribe-file /path/to/pcm16.wav --realtime
```

For lower CPU demand at a potential accuracy cost, prepare `tiny`, then start a new API instance on a free port:

```bash
.venv/bin/call-audio prepare --model tiny
./launch.sh --port 8767 --model tiny
```

Reusing a running API does not change its model. `medium` is available explicitly but is not the latency-focused default.

## Limits and recovery

- No playback stream: make the call app play audio, then query `/api/devices` again.
- No speech: check `level` in `/api/state`, the selected output, and call mute/output settings. The helper does not change system volume or mute. A muted physical output may affect monitor capture; isolated capture occurs before that output.
- Headphone/profile changes or app stream recreation: stop, refresh devices, and start with the new IDs. Automatic migration is not implemented.
- Client disconnected: capture may continue; reconnect for state or call `/api/stop`. Starting a new session before saving the previous transcript loses the previous text.
- Backlog: reduce competing CPU load, try `tiny`, or explicitly choose cloud. Per-chunk processing time is not word delay.
- Forced kill/power loss: cleanup cannot run after SIGKILL. A leftover output is named `call_audio_<random>`. Restore the affected app's output in desktop audio settings; inspect `pactl list short modules` and remove only the matching helper-owned modules, never all audio modules. The helper does not restart the audio server.

Desktop/browser support uses output streams rather than vendor meeting integrations. Participant consent and organizational transcription rules apply to real calls.

## Compression and handoff

Add `"compression":"minimal"` to `/api/start` for rules version 2: remove eligible lowercase, comma-delimited interior `um`/`uh`, standalone `the` (case-insensitive), and sentence periods/commas. `for` is never filtered. Punctuation inside numbers, dates, URLs, and email addresses is preserved; protected/ambiguous input may remain raw. Default `"none"` keeps the raw-only transcript contract. Partial events are never compacted; a final segment is processed once, with cached results used for polling and reconnects. `text` stays raw, while `compact_text`, `compression`, and `compression_ms` are additive final-segment fields. No extra model or paid API is used.

See [README_CAVEMAN.md](README_CAVEMAN.md) for configuration, protected terms, audit fields, optional local token counting, and verification. Older version-1 benchmark figures do not describe the expanded rules. Send only the selected transcript text to your LLM, not both copies and metadata. Health exposes `compression_rules_version`; the launcher refuses to silently reuse an instance running older rules.

Modules: `audio.py` validates monitors and owns temporary routes; `engines.py` implements local/cloud STT; `runtime.py` manages sessions and queues; `compression.py` implements the bounded deterministic pass; `tokens.py` optionally loads a local tokenizer before capture; `server.py` serves JSON/SSE; `cli.py` provides launch and diagnostics. LLM triggering and retrieval belong to the consuming application. `uv.lock` records the dependency versions.

## Real-call compression experiments

The historical [real-call comparison report](reports/caveman-real-call-comparison.md) measures **minimal rules version 1**, before the final article/punctuation change, and three stronger offline variants. Aggregate [CSV](reports/caveman-real-call-metrics.csv) and [JSON](reports/caveman-real-call-summary.json) are retained; source audio and full transcripts remain private and ignored by Git. These are friends/family calls, not a customer-sales validation set. The stronger variants are **not production API options**. Re-running the experiment tool now evaluates the current production minimal implementation, not the historical version-1 control.

The original installed desktop helper is separate from this checkout. This headless component installs no desktop shortcut and does not modify that instance. The repository's `READMEbig.md` describes the historical UI prototype, not this API.
