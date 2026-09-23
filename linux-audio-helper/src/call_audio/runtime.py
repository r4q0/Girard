"""Explicit, output-only capture sessions with bounded audio queues."""
from __future__ import annotations

import asyncio
import os
import queue
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from .audio import CaptureSource, IsolationRoute, list_outputs, list_playback_streams
from .engines import AssemblyAIEngine, MoonshineEngine
from .compression import MinimalCompressor


class SessionError(ValueError):
    pass


def validate_compression_settings(settings):
    mode = settings.get("compression", "none")
    if mode not in ("none", "minimal"):
        raise ValueError("compression must be none or minimal.")
    terms = settings.get("protected_terms", [])
    if not isinstance(terms, list) or len(terms) > 64:
        raise ValueError("protected_terms must be a list of at most 64 strings.")
    if any(not isinstance(term, str) or not term.strip() or len(term) > 128 for term in terms):
        raise ValueError("Each protected term must be non-empty and at most 128 characters.")
    if mode == "none" and terms:
        raise ValueError("protected_terms requires compression=minimal.")
    return mode, tuple(dict.fromkeys(term.strip() for term in terms))


class Controller:
    MAX_QUEUE_SECONDS = 1.5
    CLOUD_USD_PER_HOUR = 0.15  # Estimate only; not a provider billing receipt.

    def __init__(self, model="small", token_counter=None, tokenizer_name=None):
        self.model = model
        self.state = "idle"
        self.error = None
        self.session_id = None
        self.engine = "local"
        self.model_ready = False
        self.model_error = None
        self.outputs = []
        self.streams = []
        self.segments = {}
        self.compression_mode = "none"
        self._token_counter = token_counter
        self.tokenizer_name = tokenizer_name if token_counter is not None else None
        self._compressor = None
        self._finalized_ids = set()
        self.subscribers = set()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="inference")
        self._local = None
        self._task = None
        self._stop = threading.Event()
        self._loop = None
        self._started_at = None
        self._ended_at = None
        self._bill_started = None
        self._bill_ended = None
        self._queue_ms = 0.0
        self._processing_ms = 0.0
        self._level = 0.0
        self._closing = False

    @property
    def cloud_configured(self):
        return bool(os.environ.get("ASSEMBLYAI_TOKEN") or os.environ.get("ASSEMBLYAI_API_KEY"))

    def metrics(self):
        now = time.monotonic()
        elapsed = max(0, (self._ended_at or now) - self._started_at) if self._started_at else 0
        bill_seconds = max(0, (self._bill_ended or now) - self._bill_started) if self._bill_started else 0
        return {
            "elapsed_seconds": round(elapsed, 1),
            "estimated_cost_usd": round(bill_seconds * self.CLOUD_USD_PER_HOUR / 3600, 6),
            "queue_ms": round(self._queue_ms, 1),
            "processing_ms": round(self._processing_ms, 1),
            "level": round(self._level, 4),
        }

    def snapshot(self):
        return {
            "state": self.state, "error": self.error, "session_id": self.session_id,
            "engine": self.engine, "cloud_configured": self.cloud_configured,
            "compression_mode": self.compression_mode,
            "compression_tokenizer": self.tokenizer_name,
            "model_ready": self.model_ready, "model_error": self.model_error,
            "segments": sorted(self.segments.values(), key=lambda item: item["start_ms"]),
            "outputs": self.outputs, "streams": self.streams, **self.metrics(),
        }

    def transcript(self, final_only=True):
        """Raw text for API consumers; revisions replace the same segment ID."""
        ordered = sorted(self.segments.values(), key=lambda item: item["start_ms"])
        pending = any(not item["is_final"] for item in ordered)
        selected = [dict(item) for item in ordered if item["is_final"] or not final_only]
        result = {
            "session_id": self.session_id, "state": self.state, "error": self.error,
            "final_only": final_only, "has_pending": pending,
            "complete": bool(self.session_id and self.state == "idle" and not self.error and not pending),
            "text": "\n".join(item["text"] for item in selected),
            "segments": selected,
        }
        if self.compression_mode == "minimal":
            result["compact_text"] = "\n".join(item.get("compact_text", item["text"]) for item in selected)
            result["compression"] = {"mode": "minimal", "tokenizer": self.tokenizer_name}
        return result

    def publish(self, event):
        for subscriber in tuple(self.subscribers):
            try:
                subscriber.put_nowait(event)
            except asyncio.QueueFull:
                # Force a slow API consumer to reconnect for a full snapshot.
                self.subscribers.discard(subscriber)
                while not subscriber.empty():
                    subscriber.get_nowait()
                subscriber.put_nowait({"type": "reconnect"})

    def _state(self, state):
        self.state = state
        self.publish({"type": "state", **self.snapshot()})

    async def devices(self):
        outputs, streams = await asyncio.gather(
            asyncio.to_thread(list_outputs), asyncio.to_thread(list_playback_streams)
        )
        self.outputs, self.streams = outputs, streams
        return {"outputs": outputs, "streams": streams}

    async def preload(self):
        self._loop = asyncio.get_running_loop()

        def load():
            self._local = MoonshineEngine(lambda event: None, model=self.model)
            try:
                self._local.start()  # Includes a silent native-path warmup.
                self._local.finish()
            except Exception:
                self._local.close()
                self._local = None
                raise

        try:
            await self._loop.run_in_executor(self._pool, load)
            self.model_ready = True
        except Exception as exc:
            self.model_error = f"Local model preload failed: {exc}"
        self.publish({"type": "state", **self.snapshot()})

    async def start(self, settings):
        if self._closing or (self._task and not self._task.done()):
            raise SessionError("A session is already active; stop it before starting another.")
        if not isinstance(settings, dict):
            raise SessionError("Expected a JSON object.")
        engine = settings.get("engine", "local")
        if engine not in ("local", "cloud"):
            raise SessionError("Choose local or cloud transcription.")
        if engine == "cloud" and not self.cloud_configured:
            raise SessionError("Cloud is not configured; use local or set a server-side AssemblyAI credential.")
        if not isinstance(settings.get("isolate", False), bool):
            raise SessionError("isolate must be true or false.")
        try:
            compression_mode, protected_terms = validate_compression_settings(settings)
        except ValueError as exc:
            raise SessionError(str(exc)) from None
        await self.devices()
        # Recheck after await: two simultaneous POSTs must not open two sessions.
        if self._closing or (self._task and not self._task.done()):
            raise SessionError("A session is already active.")
        output = next((s for s in self.outputs if s["id"] == settings.get("sink_id")), None)
        if not output:
            raise SessionError("Select an available playback output; microphones are not accepted.")
        if settings.get("isolate"):
            stream_id = settings.get("stream_id")
            if type(stream_id) is not int or not any(s["id"] == stream_id for s in self.streams):
                raise SessionError("Play audio in the call app, refresh, and select its playback stream.")
        self._loop = asyncio.get_running_loop()
        self.session_id = uuid.uuid4().hex
        self.engine = engine
        self.error = None
        self.segments = {}
        self._finalized_ids.clear()
        self.compression_mode = compression_mode
        self._compressor = MinimalCompressor(
            protected_terms=protected_terms,
            token_counter=self._token_counter, tokenizer_name=self.tokenizer_name,
        ) if compression_mode == "minimal" else None
        self._started_at = self._ended_at = None
        self._bill_started = self._bill_ended = None
        self._queue_ms = self._processing_ms = self._level = 0.0
        self._stop = threading.Event()
        self._state("loading")
        self._task = asyncio.create_task(self._run({**settings, "engine": engine}, output, self.session_id))
        return self.snapshot()

    def _accept(self, session_id, event):
        if session_id != self.session_id:
            return
        event = {**event, "session_id": session_id}
        if event["type"] == "transcript":
            key = event["segment_id"]
            if key in self._finalized_ids:
                return
            previous = self.segments.get(key)
            if previous and previous["is_final"] and not event["is_final"]:
                return
            if event["is_final"]:
                self._finalized_ids.add(key)
                if self._compressor is not None:
                    started = time.perf_counter()
                    try:
                        event.update(self._compressor.compress(event["text"]))
                    except Exception:
                        # Compaction is optional and must never interrupt audio
                        # capture, discard text, or expose transcript-bearing errors.
                        event.update({"compact_text": event["text"], "compression": {
                            "mode": "minimal", "changed": False, "removed_words": 0,
                            "rules_version": "1", "reason": "compression_failed",
                            "removed_spans": [], "tokens": None,
                        }})
                        self.publish({"type": "warning", "session_id": session_id,
                                      "message": "Compression failed; raw transcript retained."})
                    event["compression_ms"] = round((time.perf_counter() - started) * 1000, 4)
            self.segments[key] = event
        elif event["type"] == "error":
            self.error = event["message"]
            self._stop.set()
        elif event["type"] == "listening":
            if self.state == "loading":
                self._state("listening")
            return
        self.publish(event)

    async def _run(self, settings, output, session_id):
        operation = self._loop.run_in_executor(self._pool, self._work, settings, output, session_id)
        try:
            while not operation.done():
                await asyncio.wait({operation}, timeout=0.2)
                self.publish({"type": "metrics", "session_id": session_id, **self.metrics()})
            await operation
        except Exception as exc:
            self.error = str(exc)
            self.publish({"type": "error", "message": self.error})
        finally:
            self._ended_at = self._ended_at or time.monotonic()
            self._bill_ended = self._bill_ended or time.monotonic()
            self._level = self._queue_ms = 0.0
            self._state("error" if self.error else "idle")

    def _work(self, settings, output, session_id):
        stop_event = self._stop
        pending = queue.Queue(maxsize=100)
        faults = queue.SimpleQueue()
        source = route = engine = None
        queued_seconds = 0.0
        queue_lock = threading.Lock()

        def emit(event):
            if event.get("type") == "error":
                faults.put(RuntimeError(event["message"]))
                stop_event.set()
            self._loop.call_soon_threadsafe(self._accept, session_id, event)

        def capture_error(exc):
            faults.put(exc)
            stop_event.set()

        def receive(samples, rate):
            nonlocal queued_seconds
            if stop_event.is_set():
                return
            duration = len(samples) / rate
            with queue_lock:
                if queued_seconds + duration > self.MAX_QUEUE_SECONDS or pending.full():
                    capture_error(RuntimeError("Audio backlog exceeded 1.5 seconds; capture stopped to avoid stale or missing speech. Try the tiny model or cloud."))
                    return
                queued_seconds += duration
                pending.put_nowait((samples.copy(), rate, time.monotonic(), duration))

        def process_one(item):
            nonlocal queued_seconds
            samples, rate, captured, duration = item
            with queue_lock:
                queued_seconds -= duration
            self._queue_ms = max(0, (time.monotonic() - captured) * 1000)
            self._level = float(np.sqrt(np.mean(samples * samples))) if len(samples) else 0.0
            begin = time.monotonic()
            engine.process(samples, rate)
            self._processing_ms = (time.monotonic() - begin) * 1000

        try:
            if settings["engine"] == "local":
                if self._local is None:
                    self._local = MoonshineEngine(emit, model=self.model)
                engine = self._local
                engine.emit = emit
            else:
                rate = 48000 if settings.get("isolate") else output["sample_rate"]
                engine = AssemblyAIEngine(emit, sample_rate=rate)
                self._bill_started = time.monotonic()
            if stop_event.is_set():
                return
            engine.start()
            if settings["engine"] == "local":
                self.model_ready = True
                self.model_error = None
            if stop_event.is_set():
                return
            sink_id = output["id"]
            if settings.get("isolate"):
                route = IsolationRoute(target_sink=sink_id)
                route.open()
                if stop_event.is_set():
                    return
                route.move_stream(settings["stream_id"])
                sink_id = route.monitor_sink
            if stop_event.is_set():
                return
            source = CaptureSource(sink_id, receive, capture_error)
            source.start()
            self._started_at = time.monotonic()
            emit({"type": "listening"})
            while not stop_event.is_set():
                try:
                    process_one(pending.get(timeout=0.1))
                except queue.Empty:
                    pass
            source.stop()
            source = None
            self._ended_at = time.monotonic()
            # On normal Stop, flush already captured speech. On an error, do not
            # pass a corrupted/gapped stream off as a complete transcript.
            if faults.empty():
                while not pending.empty():
                    process_one(pending.get_nowait())
            if not faults.empty():
                raise faults.get()
        finally:
            # Every teardown runs even when another teardown fails.
            cleanup_errors = []
            for obj, method in ((source, "stop"), (engine, "finish"), (route, "close")):
                if obj is not None:
                    try:
                        getattr(obj, method)()
                    except Exception as exc:
                        cleanup_errors.append(str(exc))
            if engine is not None and settings["engine"] == "cloud":
                try:
                    engine.close()
                except Exception as exc:
                    cleanup_errors.append(str(exc))
                self._bill_ended = time.monotonic()
            if cleanup_errors:
                emit({"type": "error", "message": "; ".join(cleanup_errors)})

    async def stop(self):
        if self._task and not self._task.done():
            self._state("stopping")
            self._stop.set()
            # Keep the request responsive during native model loading; the
            # worker checks Stop before opening any capture device.
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=5)
            except asyncio.TimeoutError:
                pass
        return self.snapshot()

    def clear(self):
        if self._task and not self._task.done():
            raise SessionError("Stop capture before clearing the transcript.")
        self.segments.clear()
        self.publish({"type": "state", **self.snapshot()})
        return self.snapshot()

    async def close(self):
        self._closing = True
        await self.stop()
        if self._task:
            await self._task
        loop = asyncio.get_running_loop()
        if self._local:
            await loop.run_in_executor(self._pool, self._local.close)
        self._pool.shutdown(wait=False)
