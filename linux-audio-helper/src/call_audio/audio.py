"""Linux playback capture and session-owned PipeWire/PulseAudio routing.

Only sink monitors are accepted. No function selects or opens a microphone.
SoundCard's PulseAudio adapter is used with DONT_MOVE to prevent automatic
fallback to another source when the selected output disappears.
"""

from __future__ import annotations

import importlib
import json
import re
import shlex
import subprocess
import sys
import threading
import time
import warnings
import uuid
from collections.abc import Callable
from typing import Any

import numpy as np


WINDOWS = sys.platform == "win32"


class AudioError(RuntimeError):
    """An actionable capture or routing error."""


def _pactl(*args: str) -> str:
    try:
        result = subprocess.run(
            ["pactl", *args], capture_output=True, text=True, timeout=5, check=True
        )
    except FileNotFoundError as exc:
        raise AudioError("pactl is missing; install the PulseAudio client utilities.") from exc
    except subprocess.TimeoutExpired as exc:
        raise AudioError("The audio server did not respond within five seconds.") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or "No response from the audio server."
        raise AudioError(f"Audio server command failed: {detail}") from exc
    return result.stdout.rstrip("\r\n")


def _json(*args: str) -> Any:
    try:
        return json.loads(_pactl("--format=json", *args))
    except json.JSONDecodeError as exc:
        raise AudioError("pactl returned invalid JSON; a recent pactl is required.") from exc


def _rate(value: str) -> int:
    match = re.search(r"(\d+)\s*Hz\b", str(value))
    if not match:
        raise AudioError(f"Cannot determine the output sample rate from {value!r}.")
    rate = int(match.group(1))
    if not 8000 <= rate <= 384000:
        raise AudioError(f"Unsupported output sample rate: {rate} Hz.")
    return rate


def _windows_outputs() -> list[dict[str, Any]]:
    """Windows: every speaker can be captured through WASAPI loopback."""
    soundcard = importlib.import_module("soundcard")
    default = soundcard.default_speaker()
    return [
        {
            "id": speaker.id,
            "name": speaker.name,
            "monitor": speaker.id,  # the loopback source shares the speaker's id
            "sample_rate": 48000,  # WASAPI converts to the requested rate
            "is_default": speaker.id == default.id,
        }
        for speaker in soundcard.all_speakers()
    ]


def list_outputs() -> list[dict[str, Any]]:
    """List outputs with verified monitors, never physical input sources."""
    if WINDOWS:
        return _windows_outputs()
    sinks = _json("list", "sinks")
    sources = _json("list", "sources")
    default = _json("info").get("default_sink_name")
    monitors = {
        source["name"]
        for source in sources
        if source.get("properties", {}).get("device.class") == "monitor"
    }
    return [
        {
            "id": sink["name"],
            "name": sink.get("description") or sink["name"],
            "monitor": sink["monitor_source"],
            "sample_rate": _rate(sink["sample_specification"]),
            "is_default": sink["name"] == default,
        }
        for sink in sinks
        if isinstance(sink.get("monitor_source"), str)
        and sink["monitor_source"] in monitors
    ]


def list_playback_streams() -> list[dict[str, Any]]:
    if WINDOWS:
        return []  # per-app isolation needs PulseAudio routing; not available on Windows
    sinks = {sink["index"]: sink["name"] for sink in _json("list", "sinks")}
    streams = []
    for stream in _json("list", "sink-inputs"):
        properties = stream.get("properties", {})
        # Internal forwarding streams should not be offered as call apps.
        if properties.get("media.name", "").startswith(("Call Audio Forward", "Call_Audio_Forward")):
            continue
        streams.append(
            {
                "id": stream["index"],
                "name": properties.get("media.name") or "Playback stream",
                "application": properties.get("application.name")
                or properties.get("application.process.binary")
                or "Unknown application",
                "sink_id": sinks.get(stream.get("sink"), ""),
            }
        )
    return streams


class _CaptureStopped(Exception):
    pass


class _InterruptibleEvent:
    """Keep SoundCard's read callback, but make a suspended read cancellable."""

    def __init__(self, stop: threading.Event, check_source: Callable[[], None] | None = None):
        self._event = threading.Event()
        self._stop = stop
        self._check_source = check_source

    def set(self) -> None:
        self._event.set()

    def clear(self) -> None:
        self._event.clear()

    def wait(self, timeout: float = 1) -> bool:
        deadline = time.monotonic() + timeout
        while not self._stop.is_set():
            if self._check_source is not None:
                self._check_source()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            if self._event.wait(min(0.05, remaining)):
                return True
        raise _CaptureStopped()


def _prepare_recorder(
    recorder: Any, stop: threading.Event, check_source: Callable[[], None] | None = None
) -> None:
    """Pin this one SoundCard recorder, without modifying global library state.

    SoundCard 0.4.x has no public stream flags or cancellation API. These small
    instance adapters use its existing CFFI bindings. DONT_MOVE is specified by
    libpulse as 0x200; it is absent from some SoundCard versions' C declarations.
    """
    backend = importlib.import_module("soundcard.pulseaudio")
    recorder._record_event = _InterruptibleEvent(stop, check_source)

    def connect(buffer_attributes: Any) -> None:
        flags = backend._pa.PA_STREAM_ADJUST_LATENCY | 0x200  # PA_STREAM_DONT_MOVE
        result = backend._pulse._pa_stream_connect_record(
            recorder.stream, recorder._id.encode(), buffer_attributes, flags
        )
        if result < 0:
            raise AudioError("Could not open the selected output monitor.")

        @backend._ffi.callback("pa_stream_request_cb_t")
        def read_callback(stream: Any, nbytes: int, userdata: Any) -> None:
            recorder._record_event.set()

        recorder._callback = read_callback
        backend._pulse._pa_stream_set_read_callback(
            recorder.stream, read_callback, backend._ffi.NULL
        )

    recorder._connect_stream = connect


class CaptureSource:
    """Capture mono float32 playback audio on a dedicated thread.

    on_chunk must return quickly, normally by adding to a bounded worker queue.
    A source is pinned for its lifetime; changing devices requires a new start.
    """

    def __init__(
        self,
        sink_id: str,
        on_chunk: Callable[[np.ndarray, int], None],
        on_error: Callable[[Exception], None],
        block_ms: int = 20,
    ):
        if not 5 <= block_ms <= 100:
            raise ValueError("block_ms must be between 5 and 100.")
        self.sink_id = sink_id
        self.on_chunk = on_chunk
        self.on_error = on_error
        self.block_ms = block_ms
        self.sample_rate = 0
        self.name = sink_id
        self.monitor = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            raise AudioError("Capture is already running.")
        output = next((item for item in list_outputs() if item["id"] == self.sink_id), None)
        if not output:
            raise AudioError("The selected output monitor is unavailable; refresh outputs.")
        self.sample_rate = output["sample_rate"]
        self.name = output["name"]
        self.monitor = output["monitor"]
        self._stop.clear()
        self._thread = threading.Thread(target=self._capture, name="call-audio-capture", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
            if self._thread.is_alive():
                raise AudioError("The capture thread has not stopped; the audio server may be unresponsive.")

    def _capture(self) -> None:
        if WINDOWS:
            self._capture_windows()
            return
        try:
            soundcard = importlib.import_module("soundcard")
            source = soundcard.get_microphone(id=self.monitor, include_loopback=True)
            # get_microphone supports fuzzy matching: forbid its fallback here.
            if source.id != self.monitor or not source.isloopback:
                raise AudioError("Refusing capture: selected source is not the exact output monitor.")
            recorder = source.recorder(
                samplerate=self.sample_rate,
                channels=[-1],  # PulseAudio's mono mix, not just the left channel.
                blocksize=max(1, round(self.sample_rate * self.block_ms / 1000)),
            )
            next_source_check = 0.0

            def check_source() -> None:
                nonlocal next_source_check
                now = time.monotonic()
                if now < next_source_check:
                    return
                next_source_check = now + 0.5
                # PipeWire can leave a DONT_MOVE stream suspended after its
                # source disappears instead of marking PA_STREAM_FAILED.
                # Use the existing connection, including during silent reads.
                try:
                    if not source.isloopback:
                        raise AudioError("The selected source is no longer an output monitor.")
                except Exception as exc:
                    raise AudioError("The selected output monitor disconnected; refresh outputs.") from exc

            _prepare_recorder(recorder, self._stop, check_source)
            with recorder:
                while not self._stop.is_set():
                    data = recorder.record(numframes=None)
                    if self._stop.is_set():
                        break
                    check_source()
                    samples = np.asarray(data, dtype=np.float32).reshape(-1)
                    if samples.size:
                        samples = np.clip(np.nan_to_num(samples), -1.0, 1.0)
                        self.on_chunk(samples, self.sample_rate)
        except _CaptureStopped:
            pass
        except Exception as exc:
            if not self._stop.is_set():
                self.on_error(AudioError(f"Playback capture stopped: {exc}"))

    def _capture_windows(self) -> None:
        """WASAPI loopback of one speaker. Windows sends no loopback packets while
        nothing plays, so a silent player keeps the stream flowing and Stop responsive."""
        keepalive = None
        try:
            soundcard = importlib.import_module("soundcard")
            speaker = soundcard.get_speaker(self.sink_id)
            source = soundcard.get_microphone(id=self.monitor, include_loopback=True)
            if source.id != self.monitor or not source.isloopback:
                raise AudioError("Refusing capture: selected source is not the exact output loopback.")
            # Larger reads on Windows: fewer wakeups, so the recorder keeps up while
            # the speech model runs, and WASAPI does not drop audio.
            blocksize = max(1, round(self.sample_rate * max(self.block_ms, 100) / 1000))
            warnings.filterwarnings("ignore", message="data discontinuity in recording")
            keepalive = threading.Thread(target=self._play_silence, args=(speaker,),
                                         name="call-audio-keepalive", daemon=True)
            keepalive.start()
            with source.recorder(samplerate=self.sample_rate, channels=1, blocksize=blocksize) as recorder:
                while not self._stop.is_set():
                    data = recorder.record(numframes=blocksize)
                    if self._stop.is_set():
                        break
                    samples = np.asarray(data, dtype=np.float32).reshape(-1)
                    if samples.size:
                        samples = np.clip(np.nan_to_num(samples), -1.0, 1.0)
                        self.on_chunk(samples, self.sample_rate)
        except Exception as exc:
            if not self._stop.is_set():
                self.on_error(AudioError(f"Playback capture stopped: {exc}"))
        finally:
            self._stop.set()
            if keepalive is not None:
                keepalive.join(timeout=1)

    def _play_silence(self, speaker: Any) -> None:
        try:
            with speaker.player(samplerate=self.sample_rate, channels=1) as player:
                silence = np.zeros(self.sample_rate // 20, dtype=np.float32)
                while not self._stop.is_set():
                    player.play(silence)
        except Exception:
            pass  # capture still works while the call itself plays audio


def _module_arguments(value: str) -> dict[str, str]:
    try:
        return dict(part.split("=", 1) for part in shlex.split(value) if "=" in part)
    except ValueError:
        return {}


def _list_modules() -> list[dict[str, Any]]:
    """Read IDs from the short format; some pactl JSON versions omit them."""
    output = _pactl("list", "short", "modules")
    # Native PipeWire modules can have multiline configuration arguments.
    # Every actual record begins with numeric ID, tab, name, tab.
    headers = list(re.finditer(r"(?m)^(\d+)\t([^\t\r\n]+)\t", output))
    if output.strip() and not headers:
        raise AudioError("Cannot safely identify audio modules from pactl output.")
    modules = []
    for position, header in enumerate(headers):
        end = headers[position + 1].start() if position + 1 < len(headers) else len(output)
        remainder = output[header.end():end].rstrip("\r\n")
        argument = remainder.rsplit("\t", 1)[0] if "\t" in remainder else remainder
        modules.append({"index": int(header.group(1)), "name": header.group(2), "argument": argument})
    return modules


def _stream_identity(stream: dict[str, Any]) -> tuple[Any, ...]:
    props = stream.get("properties", {})
    return (stream.get("client"), props.get("object.serial"), props.get("application.process.id"))


class IsolationRoute:
    """Temporary call-only sink, forwarded once to an explicit output.

    This never changes the system default. close() restores only streams still
    on this sink and unloads only modules whose current identity matches ours.
    """

    def __init__(self, target_sink: str, sink_name: str | None = None):
        self.target_sink = target_sink
        self.monitor_sink = sink_name or f"call_audio_{uuid.uuid4().hex[:12]}"
        for name in (self.target_sink, self.monitor_sink):
            if not re.fullmatch(r"[A-Za-z0-9_.:-]+", name):
                raise AudioError("An audio sink name contains unsupported characters.")
        if not self.monitor_sink.startswith("call_audio_"):
            raise AudioError("Temporary sink names must start with call_audio_.")
        if self.target_sink == self.monitor_sink or self.target_sink.startswith("call_audio_"):
            raise AudioError("Forwarding into a capture sink could create feedback.")
        self._modules: list[tuple[int, str, dict[str, str]]] = []
        self._moved: dict[int, tuple[str, tuple[Any, ...]]] = {}
        self._opened = False
        self.warnings: list[str] = []

    def _load(self, name: str, **arguments: str) -> None:
        result = _pactl("load-module", name, *(f"{key}={value}" for key, value in arguments.items()))
        try:
            module_id = int(result)
        except ValueError as exc:
            raise AudioError(f"Audio server returned an invalid module ID: {result!r}") from exc
        self._modules.append((module_id, name, arguments))

    def open(self) -> None:
        if self._opened or self._modules:
            raise AudioError("This call route is already open or still needs cleanup.")
        outputs = list_outputs()
        if any(item["id"] == self.monitor_sink for item in outputs):
            raise AudioError("That temporary sink already exists; choose a different name.")
        if not any(item["id"] == self.target_sink for item in outputs):
            raise AudioError("The playback destination is unavailable; refresh outputs.")
        try:
            self._load(
                "module-null-sink",
                sink_name=self.monitor_sink,
                sink_properties="device.description=Call_Audio_Isolated",
                rate="48000",
                channels="2",
            )
            self._load(
                "module-loopback",
                source=f"{self.monitor_sink}.monitor",
                sink=self.target_sink,
                latency_msec="20",
                source_dont_move="true",
                sink_dont_move="true",
                sink_input_properties="media.name=Call_Audio_Forward",
            )
            self._opened = True
        except Exception as exc:
            try:
                self.close()
            except AudioError as cleanup_error:
                raise AudioError(f"Route setup failed: {exc}. Cleanup also failed: {cleanup_error}") from exc
            raise

    def move_stream(self, stream_id: int) -> None:
        if not self._opened:
            raise AudioError("Open the isolated route before moving a call stream.")
        stream_id = int(stream_id)
        raw = next((s for s in _json("list", "sink-inputs") if s["index"] == stream_id), None)
        if raw is None:
            raise AudioError("That playback stream ended; refresh the application list.")
        sinks = {sink["index"]: sink["name"] for sink in _json("list", "sinks")}
        original = sinks.get(raw.get("sink"))
        if original == self.monitor_sink:
            return
        if not original:
            raise AudioError("Could not determine the stream's previous output.")
        owners = {module_id for module_id, _, _ in self._modules}
        if raw.get("owner_module") in owners:
            raise AudioError("Cannot move the forwarding stream into its own capture sink.")
        _pactl("move-sink-input", str(stream_id), self.monitor_sink)
        self._moved.setdefault(stream_id, (original, _stream_identity(raw)))

    def close(self) -> None:
        if not self._modules and not self._moved:
            self._opened = False
            return
        errors = []
        try:
            sinks = {sink["index"]: sink["name"] for sink in _json("list", "sinks")}
            streams = {stream["index"]: stream for stream in _json("list", "sink-inputs")}
            for stream_id, (previous, identity) in list(self._moved.items()):
                current = streams.get(stream_id)
                if not current or _stream_identity(current) != identity:
                    self._moved.pop(stream_id)
                    continue
                if sinks.get(current.get("sink")) != self.monitor_sink:
                    self._moved.pop(stream_id)  # Respect a user's subsequent routing change.
                    continue
                destination = previous if previous in sinks.values() else self.target_sink
                if destination not in sinks.values():
                    errors.append(f"The original output for stream {stream_id} disappeared.")
                    continue
                try:
                    _pactl("move-sink-input", str(stream_id), destination)
                    self._moved.pop(stream_id)
                    if destination != previous:
                        self.warnings.append(f"Previous output {previous} disappeared; restored to {destination}.")
                except AudioError as exc:
                    # The stream can disappear between listing it and moving it.
                    if any(s["index"] == stream_id for s in _json("list", "sink-inputs")):
                        errors.append(str(exc))
                    else:
                        self._moved.pop(stream_id)
            modules = {module["index"]: module for module in _list_modules()}
            for owned in list(reversed(self._modules)):
                module_id, name, expected = owned
                current = modules.get(module_id)
                if not current:
                    self._modules.remove(owned)
                    continue
                actual = _module_arguments(current.get("argument", ""))
                if current.get("name") != name or any(actual.get(k) != v for k, v in expected.items()):
                    errors.append(f"Module {module_id} changed ownership; left it untouched.")
                    self._modules.remove(owned)
                    continue
                try:
                    _pactl("unload-module", str(module_id))
                    self._modules.remove(owned)
                except AudioError as exc:
                    errors.append(str(exc))
        except AudioError as exc:
            errors.append(str(exc))
        self._opened = False
        if errors:
            raise AudioError("Routing cleanup incomplete: " + "; ".join(errors))

    def __enter__(self) -> IsolationRoute:
        self.open()
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
