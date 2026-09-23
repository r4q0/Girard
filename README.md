# Girard

Sales-call copilot project. Existing product context is in [context-spec.txt](context-spec.txt).

## Linux audio helper

[linux-audio-helper/](linux-audio-helper/) implements the playback capture and English transcription component: browser/desktop call output, local CPU speech recognition, optional app isolation, and a localhost control UI.

```bash
cd linux-audio-helper
uv sync --locked --python 3.12 --extra dev
.venv/bin/call-audio prepare
./launch.sh
```

Requires Linux with PipeWire's PulseAudio compatibility service (or PulseAudio), `pactl`, libpulse, and `xdg-open` for browser launching. See the [component README](linux-audio-helper/README.md) for setup, tests, measured performance, cloud fallback, and limitations.

Local mode has no STT API fees and does not capture the microphone. Audio starts only after an explicit Start action. LLM triggering, retrieval, and sales reports are outside this component.
