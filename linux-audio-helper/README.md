# Call Audio — Linux

A local-first helper for Josef's scope: capture **call playback**, turn it into live English text, and keep capture/processing latency and API cost visible. It does not capture your microphone, send text to an LLM, perform emotion detection, or create sales reports.

## Start using it

Requirements: Linux with PipeWire's PulseAudio compatibility service (or PulseAudio), the `pactl` command, libpulse, Python 3.12, and `uv`. The capture integration tests also need `pacat`; opening the browser uses `xdg-open`. Keep the existing audio server; do not start a competing PulseAudio daemon.

From this directory, install the locked dependencies and download the English model, then start the local page at **http://127.0.0.1:8765**:

```bash
uv sync --locked --python 3.12 --extra dev
.venv/bin/call-audio prepare
./launch.sh
```

1. Start your browser meeting, desktop call app, or softphone. Select the same **Audio output** in Call Audio that your call uses.
2. Leave **On device** selected: English Moonshine Small Streaming is downloaded and preloaded; no STT API charges or cloud upload.
3. Optionally select **Only selected app**. Start playback in that app, press **Refresh**, and choose its playback stream. A temporary virtual output forwards it once to the chosen output; Stop restores its previous destination.
4. Press **Start listening**. The UI revises provisional text and finalizes segments as you speak/hear speech. **Stop listening** stops capture and flushes pending text.
5. **Copy** or **Download** exports the transcript only when you request it. Export important text before starting another session, which clears the prior transcript.

**Closing the browser tab does not stop an active session.** Use Stop, or Ctrl+C in the helper's terminal. Stopping the program closes capture and cleans up its temporary routes. No login autostart, background recording, or system-wide audio-default change is installed.

The helper leaves system mute/volume unchanged. Unmute in your desktop controls when you want to hear a call. A muted output can affect monitor capture depending on the audio-server setup; the playback meter is your check. Isolated capture is taken before the physical output.

## Implementation and cost controls

```text
Selected PipeWire/PulseAudio output monitor
  → 20 ms requested capture buffers, mono float32 at native rate
  → bounded worker queue
  → preloaded Moonshine Small Streaming English on CPU
  → partial/final transcript events → localhost UI
```

- Monitor sources are explicitly validated. The capture stream is pinned so disappearing headphones cannot silently fall back to a microphone.
- The inference worker is separate from capture/UI. A backlog over 1.5 seconds stops with an explicit error instead of silently dropping or transcribing increasingly old speech.
- No extra denoiser, echo canceller, lossy compression, LLM cleanup, or unnecessary resampling is inserted. Call apps already process remote speech; extra processing needs a measured benefit.
- Audio is not recorded to disk. Transcripts remain in process/browser memory unless you export them. Model files live in `~/.cache/moonshine_voice/`; dependencies are isolated in this project's `.venv`.
- The UI binds to `127.0.0.1` only, uses same-origin/Host checks and a required POST header, and displays transcript text without interpreting HTML. Other software/users with access to the same local account remain in the trust boundary.
- Local transcription costs **$0 in API fees**, but uses CPU and battery. Queue and processing metrics are individual-stage measurements, **not** end-to-end word latency.
- English is implemented; other spoken languages are not enabled in this version. Your own voice normally does not appear in remote playback and therefore is absent from this transcript.

## Measured on the development computer

AMD Ryzen 7 250 (8 cores / 16 threads), 30 GiB RAM, Linux/PipeWire, no dedicated GPU. Tests used harmless recorded narration and private virtual audio outputs, never a real call or microphone.

- 24 seconds of English test narration plus a 1-second silent tail processed in **9.07 seconds** when fed as fast as possible: about **2.76× realtime throughput**.
- Real-time replay produced **74 provisional updates / 9 final segments**. Per-20-ms-feed processing time: **91 ms p95**, **243 ms maximum**; decoding is intermittent, not incurred on every chunk.
- Native model loaded in approximately **0.14–0.27 seconds** with files cached. Subsequent sessions reuse the model.
- Direct and app-isolated capture both delivered **20 ms mono 48 kHz chunks**; capture-thread Stop took about **31 ms**. Removing the selected monitor stopped capture with an error, without microphone fallback.
- The full HTTP → private playback capture → recognition → live UI-event test produced **31 partial updates / 5 final segments**. Stop during unfinished speech flushed the final segment and returned idle in **126 ms**, with original audio settings and module inventory preserved.
- These are a short functional benchmark, **not** validated word latency or sales-call accuracy. The test recognized the known opening phrase, with some article substitutions later. Prices, names, accents, interruptions and long calls need a representative acceptance test.

See [the saved local benchmark](reports/local-benchmark.json), [full-session test](reports/session-check.json), [capture/routing test](reports/capture-check.json), and the verification scripts below. Timing varies with load. The UI was also checked in an isolated Brave browser at desktop and mobile widths; [screenshot](reports/control-page.png).

## Optional cloud fallback

Cloud is disabled in the UI unless the server process has an `ASSEMBLYAI_TOKEN` (temporary token) or `ASSEMBLYAI_API_KEY` environment variable. Restart the helper with that environment to enable it; do not paste secrets into the browser or commit them. Prefer a backend-issued short-lived token for a team deployment.

The adapter uses AssemblyAI's EU streaming endpoint, explicitly pins `universal-streaming-english`, sends 50 ms mono PCM16 packets, and requests partial text and short endpointing thresholds. Stop forces a final endpoint, sends Terminate, and closes the connection with bounded waits. Audio leaves the computer **only when you explicitly select Cloud and Start**. This integration is unit-tested with a mock transport, not verified against a paid live session.

The displayed cloud estimate uses the researched **$0.15/session-hour** English rate; connection time including silence matters, not just speaking time. It is not an invoice and excludes taxes or provider changes. Check [AssemblyAI pricing](https://www.assemblyai.com/pricing) before enabling it. No API credentials or paid account were created during installation.

## Diagnostics and repeatable checks

From the `linux-audio-helper` directory:

```bash
.venv/bin/call-audio doctor
.venv/bin/call-audio devices
.venv/bin/python -m pytest -q
.venv/bin/python scripts/check_transcription.py
.venv/bin/python scripts/check_capture.py
.venv/bin/python scripts/check_session.py
```

`check_transcription.py` uses a short excerpt of the test WAV distributed with the installed Moonshine package. The audio tests create and remove private virtual outputs; they do not play to physical speakers or modify microphone/default/mute settings. `check_session.py` tests the real HTTP → capture → recognition → transcript path using that fixture.

To transcribe/benchmark a WAV you intentionally provide, without opening a live audio device:

```bash
.venv/bin/call-audio transcribe-file /path/to/pcm16.wav --realtime
```

To try lower CPU usage at a potential accuracy cost, prepare and select the smaller English model:

```bash
.venv/bin/call-audio prepare --model tiny
.venv/bin/call-audio serve --model tiny --open
```

Stop an already-running server first; a second launch simply opens its existing UI. `medium` is also supported explicitly, but is not the low-latency default.

## Troubleshooting and limits

- **No app listed:** it must be actively creating a playback stream. Play a test sound in the app, then Refresh. Multiple browser tabs can share one stream; use a separate call browser instance if isolation matters.
- **No speech:** verify output selection and the playback meter. This helper captures output, not your mic. Check the call's mute/output controls.
- **Headphones/Bluetooth profile changes:** Stop, Refresh, select the new output, then Start. Automatic mid-call device migration is intentionally not implemented.
- **App restarts/recreates its stream:** refresh/reselect and restart isolation; a newly created stream is not silently moved by this prototype.
- **Browser tab says disconnected:** capture may still be running. Try Stop or reopen the local page. Ctrl+C in the terminal stops the helper.
- **Backlog error:** close heavy apps, try `tiny`, or explicitly opt into cloud. Do not interpret per-chunk decode time as word delay.
- **Forced kill/power loss:** normal Stop/Ctrl+C cleans up routes, but SIGKILL cannot run cleanup. A leftover temporary output is named `call_audio_<random>`. In desktop audio settings move the affected app back to its original output; inspect `pactl list short modules` and remove only the matching helper-owned loopback/null-sink IDs, never all audio modules. Restarting the audio server can disrupt other calls, so is not done automatically.
- Desktop/browser call support uses their output stream, not vendor-specific meeting integrations. Native availability of each call app on Linux varies.
- Confirm participants' consent and your organization's recording/transcription rules before transcribing real calls.

## Project and handoff

Python 3.12 is used because the host's Python 3.14 is outside the selected package support range. `uv.lock` records installed dependency versions. To recreate the environment: `uv sync --python 3.12 --extra dev`, then `.venv/bin/call-audio prepare`.

Modules: `audio.py` (validated monitors and temporary routes), `engines.py` (local/cloud STT), `runtime.py` (session lifecycle and bounded worker), `server.py` (local API/SSE), `static/` (UI), and `cli.py` (launcher/diagnostics).

For the next team's component, `/api/events` emits JSON SSE with `session_id`, `segment_id`, `start_ms`, `end_ms`, `text`, `is_final`, `endpoint`, plus state/error/metric events. Upsert by session and segment; provisional text can change. Deciding when to send transcript text to an LLM remains outside this implementation.

The original installed desktop helper remains separate from this repository checkout; cloning this branch does not install a desktop shortcut or change system audio settings.
