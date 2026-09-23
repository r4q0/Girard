"""Streaming transcription adapters; audio sources are deliberately separate.

Call start/process/finish on the same audio worker. Moonshine keeps its model
loaded between sessions. AssemblyAI delivers callbacks from its reader thread.
Neither adapter accesses the microphone or writes audio/transcripts to disk.
"""

from __future__ import annotations

import json
import logging
import os
import socket as socket_module
import threading
import time
from functools import lru_cache
from typing import Callable
from urllib.parse import urlencode, urlsplit

import numpy as np

Emit = Callable[[dict], None]
LOCAL_MODELS = ("tiny", "small", "medium")


def _mono(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    audio = np.asarray(samples, dtype=np.float32)
    if audio.ndim != 1:
        raise ValueError("Transcription expects a one-dimensional mono audio array.")
    if not isinstance(sample_rate, int) or not 8000 <= sample_rate <= 96000:
        raise ValueError("The sample rate must be an integer between 8000 and 96000.")
    if not np.isfinite(audio).all():
        audio = np.nan_to_num(audio, nan=0.0, posinf=1.0, neginf=-1.0)
    return audio


@lru_cache(maxsize=3)
def _model_files(model: str) -> tuple[str, str]:
    if model not in LOCAL_MODELS:
        raise ValueError(f"Unknown local model; choose one of {', '.join(LOCAL_MODELS)}.")
    from moonshine_voice import ModelArch, get_model_for_language

    architecture = getattr(ModelArch, f"{model.upper()}_STREAMING")
    path, downloaded_arch = get_model_for_language(
        "en", wanted_model_arch=architecture, include_word_timestamps=False
    )
    if downloaded_arch != architecture:
        raise RuntimeError("Moonshine returned an unexpected model architecture.")
    return str(path), architecture.name


def prepare_model(model: str = "small") -> dict:
    """Download/cache the chosen English streaming model, without opening audio."""
    path, architecture = _model_files(model)
    return {"model": model, "language": "en", "path": path, "architecture": architecture}


class MoonshineEngine:
    """CPU transcription using a persistent model and a fresh stream per call."""

    name = "moonshine"

    def __init__(
        self,
        emit: Emit,
        model: str = "small",
        update_interval: float = 0.2,
        keyterms: list[str] | None = None,
    ):
        if model not in LOCAL_MODELS:
            raise ValueError(f"Unknown local model: {model}")
        if not 0.05 <= update_interval <= 2.0:
            raise ValueError("Update interval must be between 0.05 and 2 seconds.")
        self.emit = emit
        self.model = model
        self.update_interval = update_interval
        self.keyterms = list(keyterms or [])
        self.model_info: dict | None = None
        self._transcriber = None
        self._stream = None
        self._seen: dict[str, tuple] = {}
        self._completed: set[str] = set()
        self._error: str | None = None

    def start(self) -> None:
        if self._stream is not None:
            raise RuntimeError("Moonshine transcription is already running.")
        if self._transcriber is None:
            from moonshine_voice import ModelArch, Transcriber

            self.emit({"type": "status", "message": "Loading the local English model…"})
            self.model_info = prepare_model(self.model)
            options = {
                "identify_speakers": "false",
                "word_timestamps": "false",
                "return_audio_data": "false",
                "decode_incomplete_lines": "true",
                "log_output_text": "false",
                "transcription_interval": str(self.update_interval),
            }
            if self.keyterms:
                options["keyterms"] = ",".join(self.keyterms)
            self._transcriber = Transcriber(
                model_path=self.model_info["path"],
                model_arch=ModelArch[self.model_info["architecture"]],
                update_interval=self.update_interval,
                options=options,
            )
            # Exercise the native streaming/VAD path before the capture queue
            # starts. No listeners are installed on this disposable stream.
            # Silence does not claim to warm all speech decoder paths.
            warmup = self._transcriber.create_stream(update_interval=self.update_interval)
            try:
                warmup.start()
                warmup.add_audio(np.zeros(3200, dtype=np.float32), 16000)
                warmup.add_audio(np.zeros(3200, dtype=np.float32), 16000)
                warmup.stop()
            finally:
                warmup.close()
        self._seen.clear()
        self._completed.clear()
        self._error = None
        self._stream = self._transcriber.create_stream(update_interval=self.update_interval)
        self._stream.add_listener(self._on_event)
        try:
            self._stream.start()
        except Exception:
            self._stream.close()
            self._stream = None
            raise
        self.emit({"type": "status", "message": "Local English transcription ready."})

    def _on_event(self, event) -> None:
        from moonshine_voice.transcriber import Error, LineCompleted, LineStarted, LineTextChanged

        if isinstance(event, Error):
            self._error = f"Local transcription failed ({type(event.error).__name__})."
            self.emit({"type": "error", "message": self._error})
            return
        if not isinstance(event, (LineStarted, LineTextChanged, LineCompleted)):
            return
        line = event.line
        text = line.text.strip()
        segment_id = str(line.line_id)
        is_final = bool(line.is_complete or isinstance(event, LineCompleted))
        if not text or segment_id in self._completed:
            return
        start_ms = max(0, round(line.start_time * 1000))
        end_ms = max(start_ms, round((line.start_time + line.duration) * 1000))
        signature = (text, is_final, start_ms, end_ms)
        if self._seen.get(segment_id) == signature:
            return
        self._seen[segment_id] = signature
        if is_final:
            self._completed.add(segment_id)
        self.emit({
            "type": "transcript", "segment_id": segment_id,
            "start_ms": start_ms, "end_ms": end_ms, "text": text,
            "is_final": is_final, "endpoint": is_final,
            "engine_latency_ms": getattr(line, "last_transcription_latency_ms", 0),
        })

    def process(self, samples: np.ndarray, sample_rate: int) -> None:
        if self._stream is None:
            raise RuntimeError("Start local transcription before feeding audio.")
        if self._error:
            raise RuntimeError(self._error)
        audio = _mono(samples, sample_rate)
        if audio.size:
            self._stream.add_audio(audio, sample_rate)
        if self._error:
            raise RuntimeError(self._error)

    def finish(self) -> None:
        if self._stream is None:
            return
        stream, self._stream = self._stream, None
        try:
            stream.stop()  # Native stop decodes and completes pending speech.
            if self._error:
                raise RuntimeError(self._error)
        finally:
            stream.close()

    def close(self) -> None:
        try:
            self.finish()
        finally:
            if self._transcriber is not None:
                self._transcriber.close()
                self._transcriber = None


def _connect_websocket(url: str, **kwargs):
    from websockets.sync.client import connect
    return connect(url, **kwargs)


class AssemblyAIEngine:
    """One direct, explicitly cheap English cloud session, billed while open."""

    name = "assemblyai"
    BEGIN_TIMEOUT = 10.0
    FINISH_TIMEOUT = 3.0
    SEND_TIMEOUT = 2.0
    ALLOWED_ENDPOINTS = {
        "streaming.assemblyai.com", "streaming.eu.assemblyai.com",
        "streaming.us.assemblyai.com",
    }

    def __init__(
        self,
        emit: Emit,
        token: str | None = None,
        api_key: str | None = None,
        endpoint: str = "wss://streaming.eu.assemblyai.com/v3/ws",
        sample_rate: int = 48000,
    ):
        parts = urlsplit(endpoint)
        if (parts.scheme != "wss" or parts.netloc not in self.ALLOWED_ENDPOINTS
                or parts.path != "/v3/ws" or parts.query or parts.fragment):
            raise ValueError("Use an official AssemblyAI wss streaming endpoint without query parameters.")
        _mono(np.empty(0, dtype=np.float32), sample_rate)
        self.emit = emit
        self.token = token or os.environ.get("ASSEMBLYAI_TOKEN")
        self.api_key = api_key or os.environ.get("ASSEMBLYAI_API_KEY")
        self.endpoint = endpoint
        self.sample_rate = sample_rate
        self._packet_bytes = round(sample_rate * 0.05) * 2
        self._socket = None
        self._reader: threading.Thread | None = None
        self._begun = threading.Event()
        self._reader_done = threading.Event()
        self._termination_confirmed = False
        self._stopping = False
        self._failure: str | None = None
        self._buffer = bytearray()
        self._turns: dict[str, tuple] = {}
        self._completed: set[str] = set()
        self._sent_samples = 0
        self._send_started: float | None = None

    def start(self) -> None:
        if self._socket is not None:
            raise RuntimeError("Cloud transcription is already running.")
        if not self.token and not self.api_key:
            raise RuntimeError("Set ASSEMBLYAI_TOKEN or ASSEMBLYAI_API_KEY to use cloud transcription.")
        self._begun.clear()
        self._reader_done.clear()
        self._termination_confirmed = self._stopping = False
        self._failure = None
        self._buffer.clear()
        self._turns.clear()
        self._completed.clear()
        self._sent_samples = 0
        self._send_started = None
        params = {
            "speech_model": "universal-streaming-english",
            "encoding": "pcm_s16le", "sample_rate": self.sample_rate,
            "include_partial_turns": "true", "format_turns": "false",
            "min_turn_silence": 160, "max_turn_silence": 800,
            "end_of_turn_confidence_threshold": 0.4,
            "speaker_labels": "false",
            "inactivity_timeout": 15,
        }
        headers = None
        if self.token:
            params["token"] = self.token
        else:
            headers = {"Authorization": self.api_key}
        # A caller may enable verbose global logging: never log a token URL.
        socket_logger = logging.Logger("call_audio.cloud_socket")
        socket_logger.disabled = True
        try:
            self._socket = _connect_websocket(
                self.endpoint + "?" + urlencode(params), additional_headers=headers,
                open_timeout=self.BEGIN_TIMEOUT, close_timeout=1,
                ping_interval=10, ping_timeout=10, max_size=2**20, max_queue=16,
                logger=socket_logger,
            )
        except Exception as exc:
            raise RuntimeError(
                f"AssemblyAI connection failed ({type(exc).__name__}); check network and credentials."
            ) from None
        self._reader = threading.Thread(target=self._read_loop, name="assemblyai-reader", daemon=True)
        self._reader.start()
        if not self._begun.wait(self.BEGIN_TIMEOUT):
            self._failure = "AssemblyAI did not confirm the session before the connection timeout."
        if self._failure:
            failure = self._failure
            self.close()
            raise RuntimeError(failure)

    def _fail(self, message: str) -> None:
        if not self._failure:
            self._failure = message
            self.emit({"type": "error", "message": message})
        self._begun.set()

    def _read_loop(self) -> None:
        socket = self._socket
        try:
            while True:
                if self._failure:
                    break
                if (self._send_started is not None
                        and time.monotonic() - self._send_started > self.SEND_TIMEOUT):
                    self._fail("AssemblyAI audio upload stalled; the cloud connection was stopped.")
                    # websocket.close() needs the same protocol mutex as a
                    # blocked sendall(). Shutdown the underlying transport to
                    # release that send before asking the library to close.
                    transport = getattr(socket, "socket", None)
                    if transport is not None:
                        try:
                            transport.shutdown(socket_module.SHUT_RDWR)
                        except OSError:
                            pass
                    break
                try:
                    raw_message = socket.recv(timeout=0.1)
                except TimeoutError:
                    continue
                message = json.loads(raw_message)
                self._on_message(message)
                if self._termination_confirmed or self._failure:
                    break
        except Exception as exc:
            if not self._stopping:
                self._fail(f"AssemblyAI stream disconnected ({type(exc).__name__}).")
        finally:
            if not self._begun.is_set():
                self._fail("AssemblyAI closed before confirming the session.")
            self._reader_done.set()
            # Also close on provider errors, so a failed worker cannot leave a
            # billed socket running until the rest of the application notices.
            if self._failure:
                try:
                    socket.close()
                except Exception:
                    pass

    def _on_message(self, message: dict) -> None:
        kind = message.get("type")
        if kind == "Begin":
            model = (message.get("configuration") or {}).get("model")
            if model and model != "universal-streaming-english":
                self._fail("AssemblyAI selected an unexpected model; the cloud session was stopped.")
                return
            self._begun.set()
            self.emit({"type": "status", "message": "Cloud English transcription ready."})
        elif kind == "Termination":
            self._termination_confirmed = True
            self.emit({"type": "status", "message": "Cloud session terminated.",
                       "session_duration_seconds": message.get("session_duration_seconds"),
                       "audio_duration_seconds": message.get("audio_duration_seconds")})
        elif kind == "Error" or message.get("error"):
            # Provider messages and close reasons may echo credentials or URLs.
            self._fail("AssemblyAI reported a streaming error; check credentials, quota, and audio settings.")
        elif kind == "Turn":
            self._on_turn(message)

    def _on_turn(self, message: dict) -> None:
        turn_order = message.get("turn_order")
        if not isinstance(turn_order, int) or turn_order < 0:
            self._fail("AssemblyAI returned a transcript without a valid turn identifier.")
            return
        segment_id = str(turn_order)
        if segment_id in self._completed:
            return
        previous = self._turns.get(segment_id)
        is_final = bool(message.get("end_of_turn", False))
        text = (message.get("transcript") or "").strip()
        if not text and is_final and previous:
            text = previous[0]
        if not text:
            return
        words = message.get("words") or []
        start_ms = round(words[0]["start"]) if words else (previous[2] if previous else 0)
        end_ms = round(words[-1]["end"]) if words else (previous[3] if previous else round(self._sent_samples * 1000 / self.sample_rate))
        start_ms, end_ms = max(0, start_ms), max(start_ms, end_ms)
        signature = (text, is_final, start_ms, end_ms)
        if previous == signature:
            return
        self._turns[segment_id] = signature
        if is_final:
            self._completed.add(segment_id)
        self.emit({"type": "transcript", "segment_id": segment_id,
                   "start_ms": start_ms, "end_ms": end_ms, "text": text,
                   "is_final": is_final, "endpoint": is_final})

    def _send(self, payload: str | bytes) -> None:
        self._send_started = time.monotonic()
        try:
            self._socket.send(payload)
        except Exception as exc:
            self._fail(f"AssemblyAI audio send failed ({type(exc).__name__}).")
            raise RuntimeError(self._failure) from None
        finally:
            self._send_started = None

    def process(self, samples: np.ndarray, sample_rate: int) -> None:
        if self._socket is None or self._stopping:
            raise RuntimeError("Start cloud transcription before feeding audio.")
        if self._failure:
            raise RuntimeError(self._failure)
        if sample_rate != self.sample_rate:
            raise ValueError("Audio sample rate changed; restart the cloud session with the new rate.")
        audio = _mono(samples, sample_rate)
        # 32768 maps -1 exactly to -32768; clipping prevents +1 overflow.
        pcm = np.clip(np.rint(audio * 32768), -32768, 32767).astype("<i2")
        self._buffer.extend(pcm.tobytes())
        while len(self._buffer) >= self._packet_bytes:
            payload = bytes(self._buffer[:self._packet_bytes])
            del self._buffer[:self._packet_bytes]
            self._send(payload)
            self._sent_samples += len(payload) // 2

    def finish(self) -> None:
        if self._socket is None or self._stopping:
            return
        self._stopping = True
        try:
            if not self._reader_done.is_set() and not self._failure:
                if self._buffer:
                    # Preserve the final fragment and respect the 50ms minimum.
                    payload = bytes(self._buffer).ljust(self._packet_bytes, b"\0")
                    self._buffer.clear()
                    self._send(payload)
                    self._sent_samples += len(payload) // 2
                self._send(json.dumps({"type": "ForceEndpoint"}))
                self._send(json.dumps({"type": "Terminate"}))
                self._reader_done.wait(self.FINISH_TIMEOUT)
            if not self._termination_confirmed:
                self.emit({"type": "warning", "message": "Closed cloud connection without a termination acknowledgement; the last words may be incomplete."})
        finally:
            self._close_socket()

    def _close_socket(self) -> None:
        socket, self._socket = self._socket, None
        if socket is not None:
            try:
                socket.close()
            except Exception:
                pass
        if self._reader and self._reader is not threading.current_thread():
            self._reader.join(timeout=1.5)
        self._reader = None

    def close(self) -> None:
        try:
            self.finish()
        finally:
            self._close_socket()
