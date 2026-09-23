"""
Girard agent service: the middle part between the audio helper and the dashboard.

    audio helper (127.0.0.1:8766, HTTP + SSE)  ->  agent (this, :8000/ws)  ->  dashboard (:5173)

- Talks to the dashboard over one WebSocket, following dashboard-protocol.md.
- Starts and stops capture on the audio helper and turns its transcript into cards
  with the fast lane in server.py (hedging, warm cache). Restarts capture if it stops.
- Research lane (Tavily) on unknown vendors, rolling call summary (slow lane),
  metrics and the post-call debrief.

Run:  .venv/Scripts/python agent.py   (serves the WebSocket and the dev portal on :8000)
"""
import asyncio
import json
import os
import re
import time
import uuid
from pathlib import Path

import aiohttp
from fastapi import WebSocket, WebSocketDisconnect

import server
from server import MODEL, S, app, client, warmup

ROOT = Path(__file__).parent
HELPER_URL = os.environ.get("GIRARD_HELPER_URL", "http://127.0.0.1:8766")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
SLOW_MODEL = os.environ.get("GIRARD_SLOW_MODEL", "Qwen/Qwen3-235B-A22B-Instruct-2507")
AGENT_NAME = "girard-agent 0.2.0"
USD_TO_EUR = 0.92  # only for the protocol's cost_eur; the dashboard shows cost_usd
SUMMARY_EVERY_S = 30
MAX_RESEARCH_PER_CALL = 5
HELPER_HEADERS = {"X-Call-Audio": "1", "Content-Type": "application/json"}

FAST_NOTE = "No filler. No articles. Fragments OK. Facts only."


def now_ms():
    return int(time.time() * 1000)


def pct(values, p):
    return server.pct(values, p)


class Hub:
    """Every connected dashboard gets every message."""

    def __init__(self):
        self.sockets = set()

    async def send(self, message):
        dead = []
        for ws in list(self.sockets):
            try:
                await ws.send_text(json.dumps(message))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.sockets.discard(ws)

    def post(self, message):
        """Fire-and-forget send from sync code."""
        asyncio.get_running_loop().create_task(self.send(message))

    async def notice(self, message, level="warning"):
        await self.send({"type": "notice", "level": level, "message": message})


HUB = Hub()
RESEARCH_CACHE = {}  # entity (lowercase) -> finished research message, shared across calls
# Local competitor profiles (competitors.json), used before any web search
PROFILES = {k: v for k, v in json.loads((ROOT / "competitors.json").read_text(encoding="utf-8")).items()
            if not k.startswith("_")} if (ROOT / "competitors.json").exists() else {}


class Call:
    """One call session: transcript, cards, lanes and metrics."""

    def __init__(self, prospect):
        self.id = uuid.uuid4().hex[:12]
        self.prospect = prospect or {}
        self.state = "loading"
        self.started_at = None          # wall clock ms when listening began
        self.segments = {}              # segment_id -> latest transcript event
        self.finals = []                # final lines in order: {segment_id, text, end_ms}
        self.restarts = 0               # capture restarts after a helper error
        self.cards = []
        self.card_seq = 0
        self.researched = set()
        self.ledger0 = dict(server.LEDGER)  # spend so far; the call's cost is the growth
        self.calls = {"slow": 0, "research": 0}
        self.lat = {"stt": [], "trigger": [], "ttft": [], "total": []}
        self.summary_lines = 0
        self.tasks = set()
        self.stopping = False

    def spawn(self, coro):
        task = asyncio.get_running_loop().create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    def speech_end_wall(self, event):
        """Wall clock (s) when this segment's speech ended, from helper timestamps."""
        if self.started_at is None or event.get("end_ms") is None:
            return time.time()
        return self.started_at / 1000 + event["end_ms"] / 1000


CALL: Call | None = None


# ---------------------------------------------------------------- model helpers

async def llm_json(call, lane, model, system, user, max_tokens=700):
    """One JSON-mode completion, with usage counted for the metrics."""
    r = await client.chat.completions.create(
        model=model, temperature=0.2, max_tokens=max_tokens,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    if r.usage:
        server.charge_usage(model, r.usage)
    if call is not None:
        call.calls[lane] += 1
    text = r.choices[0].message.content or "{}"
    text = re.sub(r"^```(json)?|```$", "", text.strip()).strip()
    return json.loads(text)


async def tavily(query, max_results=5):
    if not TAVILY_API_KEY:
        raise RuntimeError("TAVILY_API_KEY is not set")
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12)) as session:
        async with session.post("https://api.tavily.com/search",
                                headers={"Authorization": f"Bearer {TAVILY_API_KEY}"},
                                json={"query": query, "max_results": max_results,
                                      "search_depth": "basic"}) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Tavily returned HTTP {resp.status}")
            data = await resp.json()
    return data.get("results", [])


def salesbook_text():
    return (ROOT / S.salesbook_name).read_text(encoding="utf-8")


def sources_from(results, n=4):
    return [{"title": r.get("title") or r.get("url", ""), "url": r.get("url", "")} for r in results[:n]]


def results_text(results):
    return "\n\n".join(f"[{i + 1}] {r.get('title', '')} ({r.get('url', '')})\n{(r.get('content') or '')[:700]}"
                       for i, r in enumerate(results))


# ---------------------------------------------------------------- metrics

def call_spend(call):
    """What this call has cost so far: the ledger's growth since the call started."""
    return {k: server.LEDGER[k] - call.ledger0[k] for k in call.ledger0}


async def send_metrics(call):
    fast = S.metrics
    spend = call_spend(call)
    t_in, t_cached, t_out, usd = spend["input"], spend["cached"], spend["output"], spend["usd"]

    def stat(values):
        if not values:
            return None
        return {"last": round(values[-1]), "p50": round(pct(values, 50)),
                "p95": round(pct(values, 95)), "p99": round(pct(values, 99))}

    latency = {k: s for k, s in ((k, stat(v)) for k, v in call.lat.items()) if s}
    await HUB.send({
        "type": "metrics",
        "tokens": {"input": t_in, "cached": t_cached, "output": t_out},
        "cost_usd": round(usd, 6),  # exact: Token Factory list prices, billed in USD
        "cost_eur": round(usd * USD_TO_EUR, 6),
        "calls": {"fast": len(fast), "slow": call.calls["slow"], "research": call.calls["research"]},
        "cache_hit_rate": round(t_cached / t_in, 4) if t_in else None,
        "latency_ms": latency,
    })


# ---------------------------------------------------------------- transcript -> cards

def log(message):
    print(f"[girard {time.strftime('%H:%M:%S')}] {message}", flush=True)


async def on_transcript(call, event):
    """Every transcript revision from the audio helper: forward it to the dashboard,
    and run the fast lane on each final line."""
    # Segment ids restart when capture restarts, so prefix them per capture run
    seg = f"{call.restarts}-{event['segment_id']}"
    event = {**event, "type": "transcript", "segment_id": seg, "speaker": "customer",
             "session_id": call.id}
    call.segments[seg] = event
    await HUB.send({k: v for k, v in event.items()
                    if k in ("type", "session_id", "segment_id", "start_ms", "end_ms", "text", "is_final", "speaker")})
    if not event["is_final"]:
        return
    text = event["text"].strip()
    if not text:
        return
    log(f"PROSPECT: {text}")
    arrived, arrived_perf = time.time(), time.perf_counter()
    call.finals.append({"segment_id": seg, "text": text, "end_ms": event.get("end_ms")})
    run, reused, head_start = server.begin_line(text)
    if run is None:
        log("  -> filler, no card")
        return
    call.spawn(finish_card(call, seg, text, run, reused, head_start, arrived, arrived_perf,
                           call.speech_end_wall(event)))


async def finish_card(call, seg, text, run, reused, head_start, arrived, arrived_perf, speech_end):
    await asyncio.wait([run.task])
    if run.task.cancelled():
        log("  -> request cancelled")
        return
    try:
        card, m = server.complete_line(text, run, reused, head_start)
    except Exception as e:
        log(f"  -> card request failed: {type(e).__name__}: {e}")
        await HUB.notice(f"Card request failed: {type(e).__name__}: {e}")
        return
    sent = time.time()
    if card is None:
        reason = ("timeout" if m.get("timeout") else f"already shown ({m['repeat']})" if m.get("repeat")
                  else m.get("invalid") or "nothing relevant")
        log(f"  -> no card: {reason}")
        await send_metrics(call)
        return
    log(f"  -> CARD {card['id']}: {' / '.join(card.get('say') or [])}  ({round((sent - arrived) * 1000)} ms)")
    call.card_seq += 1
    entry = card.get("entry") or {}
    details = entry.get("details", [])
    proof = next((d.split(":", 1)[1].strip() for d in details if d.startswith("Proof:")), None)
    if proof is None and card["id"].startswith("comp_"):  # competitor cards show how we compare
        proof = next((d.strip() for d in details if d.startswith("We win:")), None)
    title = f"Unknown vendor: {card['q']}" if card["id"] == "comp_unknown" else entry.get("title", card["id"])
    stt = max(0.0, (arrived - speech_end) * 1000)
    # from the final line to the card request; 0 when it already started on partial speech
    trigger = 0.0 if reused else max(0.0, (run.t0 - arrived_perf) * 1000)
    total = max(0.0, (sent - speech_end) * 1000)
    latency = {"stt": round(stt), "trigger": round(trigger), "ttft": round(m.get("ttft_ms") or 0), "total": round(total)}
    for k, v in latency.items():
        call.lat[k].append(v)
    message = {
        "type": "card", "card_id": f"c_{call.card_seq:04d}", "playbook_id": card["id"],
        "kind": card["id"].split("_")[0], "title": title, "say": card.get("say") or [],
        "proof": proof, "q": card.get("q"), "trigger": {"segment_id": seg, "text": text},
        "latency_ms": latency, "created_at": now_ms(),
    }
    call.cards.append(message)
    await HUB.send(message)
    await send_metrics(call)
    # Research the vendor: an unknown one by name (q), or a salesbook competitor with a local profile
    entity = card.get("q") or (entry.get("title") if card["id"].startswith("comp_") else None)
    if entity and (card.get("q") or entity.strip().lower() in PROFILES):
        call.spawn(research(call, entity, origin="live"))


# ---------------------------------------------------------------- research lane

async def research(call, entity, origin="live"):
    key = entity.strip().lower()
    if not key or (call and key in call.researched):
        return
    rid = "r_" + re.sub(r"[^a-z0-9]+", "_", key).strip("_")
    if key in RESEARCH_CACHE:
        cached = {**RESEARCH_CACHE[key], "origin": "cache" if origin == "live" else origin}
        if call:
            call.researched.add(key)
        await HUB.send(cached)
        return
    if call:
        if len(call.researched) >= MAX_RESEARCH_PER_CALL:
            return
        call.researched.add(key)
    profile = PROFILES.get(key)
    if profile:  # known competitor: profile and comparison straight from competitors.json
        log(f"  -> research: {profile['name']} (local profile)")
        await HUB.send({"type": "research", "research_id": rid, "entity": profile["name"], "status": "done",
                        "origin": origin, "bullets": profile.get("about", []) + profile.get("compare", []),
                        "sources": [], "took_ms": 0})
        return
    await HUB.send({"type": "research", "research_id": rid, "entity": entity, "status": "searching", "origin": origin})
    t0 = time.perf_counter()
    try:
        results = await asyncio.wait_for(tavily(f"{entity} company product what they do"), 12)
        out = await asyncio.wait_for(llm_json(call, "research", MODEL,
            "Summarize web results about a vendor a sales prospect mentioned. "
            'Return JSON {"bullets": [1 to 3 short factual bullets, max 15 words each]}. '
            "Only facts from the results. " + FAST_NOTE,
            f"Vendor: {entity}\n\nResults:\n{results_text(results)}", max_tokens=200), 8)
        message = {"type": "research", "research_id": rid, "entity": entity, "status": "done", "origin": origin,
                   "bullets": [str(b) for b in out.get("bullets", [])][:3], "sources": sources_from(results, 3),
                   "took_ms": round((time.perf_counter() - t0) * 1000)}
        RESEARCH_CACHE[key] = message
        await HUB.send(message)
    except Exception as e:
        await HUB.send({"type": "research", "research_id": rid, "entity": entity, "status": "failed", "origin": origin,
                        "took_ms": round((time.perf_counter() - t0) * 1000)})
        if "TAVILY_API_KEY" in str(e):
            await HUB.notice("Research is off: add TAVILY_API_KEY to .env and restart the agent.")
    if call:
        await send_metrics(call)


async def metrics_loop(call):
    """Keep the dashboard's cost counter live, also when no card is being made."""
    last = None
    while call is CALL and not call.stopping:
        await asyncio.sleep(2)
        if server.LEDGER["usd"] != last:
            last = server.LEDGER["usd"]
            await send_metrics(call)


# ---------------------------------------------------------------- slow lane

async def summary_loop(call):
    while call is CALL and not call.stopping:
        await asyncio.sleep(SUMMARY_EVERY_S)
        if call is CALL and len(call.finals) > call.summary_lines:
            await summarize(call)


async def summarize(call):
    call.summary_lines = len(call.finals)
    transcript = "\n".join(f"PROSPECT: {f['text']}" for f in call.finals)
    shown = ", ".join(c["playbook_id"] for c in call.cards) or "none"
    try:
        out = await llm_json(call, "slow", SLOW_MODEL,
            "You track a live sales discovery call. Only the prospect is transcribed; the rep is not. "
            "Return JSON: "
            '{"text": "call so far, max 60 words, terse: prospect, pain, numbers, decision maker, timing", '
            '"stage": "one of Opening, Discovery, Qualification, Objections, Closing", '
            '"ask_next": [up to 3 questions the rep has not covered yet], "risks": [up to 3], '
            '"next_step": "best next step", "sentiment": {"value": -1 to 1, "label": "one word"}}. '
            "Next steps and questions must fit the SALESBOOK and its DON'TS. " + FAST_NOTE,
            f"Prospect context: {json.dumps(call.prospect)}\n"
            f"Cards shown to the rep: {shown}\n\nTranscript:\n{transcript}\n\nSALESBOOK:\n{salesbook_text()}", 400)
    except Exception as e:
        await HUB.notice(f"Summary failed: {type(e).__name__}")
        return
    S.summary = str(out.get("text", ""))[:600]  # the fast lane's CALL SO FAR
    await HUB.send({"type": "summary", "text": S.summary, "stage": out.get("stage"),
                    "ask_next": [str(x) for x in out.get("ask_next", [])][:3],
                    "risks": [str(x) for x in out.get("risks", [])][:3],
                    "next_step": out.get("next_step"), "updated_at": now_ms()})
    sentiment = out.get("sentiment") or {}
    if isinstance(sentiment.get("value"), (int, float)):
        await HUB.send({"type": "sentiment", "value": max(-1, min(1, float(sentiment["value"]))),
                        "label": sentiment.get("label")})
    await send_metrics(call)


async def debrief(call):
    await HUB.send({"type": "debrief", "status": "writing"})
    transcript = "\n".join(f"PROSPECT: {f['text']}" for f in call.finals)
    if not transcript:
        await HUB.send({"type": "debrief", "status": "failed"})
        await HUB.notice("No prospect speech was captured, so there is nothing to debrief.", "info")
        return
    cards = "\n".join(f"- {c['kind']}: {c['title']} (on: \"{c['trigger']['text']}\")" for c in call.cards) or "none"
    try:
        out = await llm_json(call, "slow", SLOW_MODEL,
            "Write the post-call debrief for a sales rep. Only the prospect's side was transcribed; "
            "you also get the advice cards the rep was shown. Do not claim what the rep said. "
            "Only suggest offers, prices, timelines and claims that are in the SALESBOOK below, and "
            "respect its DON'TS: never invent discounts, credits, guarantees or dates. "
            "Plain, direct English for humans. Return JSON: "
            '{"summary": "3 to 4 sentences", "went_well": [..], "improve": [..], "needs": [what the prospect needs], '
            '"objections": [{"objection": "..", "handled": "what the card suggested", "status": "open or resolved"}], '
            '"competitors": [..], "next_steps": [concrete actions], '
            '"email": {"subject": "..", "body": "short follow-up email from the rep to the prospect"}}',
            f"Prospect: {json.dumps(call.prospect)}\n"
            f"Last call summary: {S.summary or '-'}\n\nCards shown:\n{cards}\n\nTranscript:\n{transcript}"
            f"\n\nSALESBOOK:\n{salesbook_text()}", 1400)
        message = {"type": "debrief", "status": "done", "summary": out.get("summary", "")}
        for key in ("went_well", "improve", "needs", "competitors", "next_steps"):
            message[key] = [str(x) for x in out.get(key, [])]
        message["objections"] = [
            {"objection": str(o.get("objection", "")), "handled": str(o.get("handled", "")),
             "status": o.get("status") if o.get("status") in ("open", "resolved") else "open"}
            for o in out.get("objections", []) if isinstance(o, dict)]
        email = out.get("email") or {}
        if email.get("subject") and email.get("body"):
            message["email"] = {"subject": str(email["subject"]), "body": str(email["body"])}
        await HUB.send(message)
    except Exception as e:
        await HUB.send({"type": "debrief", "status": "failed"})
        await HUB.notice(f"Debrief failed: {type(e).__name__}: {e}", "error")
    await send_metrics(call)


# ---------------------------------------------------------------- audio sources

async def helper_get(path):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
        async with s.get(HELPER_URL + path) as r:
            return await r.json()


async def helper_post(path, body):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
        async with s.post(HELPER_URL + path, headers=HELPER_HEADERS, json=body) as r:
            data = await r.json(content_type=None)
            if r.status >= 400:
                raise RuntimeError(data.get("error") or data.get("message") or f"HTTP {r.status}")
            return data


async def devices_message():
    outputs, streams, helper_ok = [], [], True
    try:
        d = await helper_get("/api/devices")
        outputs, streams = d.get("outputs", []), d.get("streams", [])
    except Exception:
        helper_ok = False
    return {"type": "devices", "outputs": outputs, "streams": streams}, helper_ok


async def set_state(call, state, error=None):
    call.state = state
    if state == "listening" and call.started_at is None:
        call.started_at = now_ms()
    await HUB.send({"type": "state", "session_id": call.id, "state": state,
                    "started_at": call.started_at, "error": error})


async def stop_helper_capture():
    """Stop any capture on the helper and wait until it is idle."""
    state = (await helper_get("/api/state")).get("state")
    if state in ("idle", "error"):
        return
    log(f"stopping a capture that was still running on the helper ({state})")
    await helper_post("/api/stop", {})
    for _ in range(50):
        if (await helper_get("/api/state")).get("state") in ("idle", "error"):
            return
        await asyncio.sleep(0.2)


async def run_helper(call, command):
    """Capture on the helper and consume its events until the call is stopped.
    If capture stops by itself (an error on the helper), it is restarted, so the
    call keeps going instead of ending in the middle."""
    body = {"sink_id": command.get("sink_id"), "engine": "local", "isolate": bool(command.get("isolate"))}
    if body["isolate"] and command.get("stream_id") is not None:
        body["stream_id"] = int(command["stream_id"])
    timeout = aiohttp.ClientTimeout(total=None, sock_read=None)
    while call is CALL and not call.stopping:
        try:
            await stop_helper_capture()  # a capture left over from an earlier agent run blocks a new one
            snap = await helper_post("/api/start", body)
        except Exception as e:
            log(f"capture start failed: {e}")
            if call.restarts == 0:
                await set_state(call, "error", f"Audio helper: {e}")
                await HUB.notice(f"Could not start capture: {e}", "error")
                return
            await asyncio.sleep(1)  # retry a restart
            continue
        helper_session = snap.get("session_id")
        log(f"capture started (run {call.restarts})")
        ended = await consume_helper(call, helper_session, timeout)
        if call is not CALL or call.stopping:
            return
        call.restarts += 1
        log(f"capture stopped ({ended}); restarting")
        await HUB.notice(f"Audio capture stopped ({ended}). Restarting.", "warning")


async def consume_helper(call, helper_session, timeout):
    """Forward one helper session's events. Returns why it ended."""
    while call is CALL and not call.stopping:
        try:
            async with aiohttp.ClientSession(timeout=timeout) as s:
                async with s.get(HELPER_URL + "/api/events") as resp:
                    async for raw in resp.content:
                        line = raw.decode("utf-8", "replace").strip()
                        if not line.startswith("data:"):
                            continue
                        ev = json.loads(line[5:])
                        kind = ev.get("type")
                        if ev.get("session_id") not in (None, helper_session):
                            continue
                        if kind == "transcript":
                            await on_transcript(call, ev)
                        elif kind == "metrics":
                            await HUB.send({"type": "audio", "level": ev.get("level", 0),
                                            "elapsed_seconds": ev.get("elapsed_seconds"),
                                            "queue_ms": ev.get("queue_ms"), "processing_ms": ev.get("processing_ms")})
                        elif kind == "state":
                            st = ev.get("state")
                            if st == "listening" and call.state != "listening":
                                await set_state(call, "listening")
                            elif st == "error":
                                return ev.get("error") or "helper error"
                            elif st == "idle" and ev.get("session_id") == helper_session and call.state == "listening":
                                return "helper went idle"
                        elif kind == "warning":
                            await HUB.notice(ev.get("message", kind), "warning")
                        elif kind == "reconnect":
                            break
        except Exception as e:
            if call is not CALL or call.stopping:
                return "stopped"
            log(f"event stream dropped ({type(e).__name__}); reconnecting")
            await asyncio.sleep(0.5)
    return "stopped"


# ---------------------------------------------------------------- commands

async def start_call(command):
    global CALL
    if CALL and CALL.state in ("loading", "listening", "stopping"):
        await HUB.notice("A call is already running. Stop it first.")
        return
    call = CALL = Call(command.get("prospect") or {})
    for run in (S.spec, S.inflight):
        if run:
            run.cancel()
    S.reset()
    await set_state(call, "loading")
    asyncio.get_running_loop().create_task(warmup())
    call.spawn(summary_loop(call))
    call.spawn(metrics_loop(call))
    call.spawn(run_helper(call, command))


async def stop_call():
    call = CALL
    if not call or call.state not in ("loading", "listening"):
        return
    call.stopping = True
    await set_state(call, "stopping")
    try:
        await helper_post("/api/stop", {})
        for _ in range(50):
            st = await helper_get("/api/state")
            if st.get("state") in ("idle", "error"):
                break
            await asyncio.sleep(0.2)
    except Exception as e:
        await HUB.notice(f"Audio helper stop: {e}")
    await asyncio.sleep(0.3)  # let the last final transcript events arrive
    for task in list(call.tasks):
        if not task.done() and task.get_coro().__name__ in ("run_helper", "summary_loop", "metrics_loop"):
            task.cancel()
    await set_state(call, "idle")
    await debrief(call)


async def handle(command):
    kind = command.get("type")
    if kind == "refresh_devices":
        message, ok = await devices_message()
        await HUB.send(message)
        if not ok:
            await HUB.notice("Audio helper not running. Start Girard with start.ps1.", "warning")
    elif kind == "start":
        await start_call(command)
    elif kind == "stop":
        await stop_call()
    elif kind in ("feedback", "dismiss") and CALL:
        for card in CALL.cards:
            if card["card_id"] == command.get("card_id"):
                card[kind] = command.get("useful", True)


@app.post("/api/hear")
async def hear(body: server.Line):
    """Testing without audio: feed one final prospect line into the running call,
    exactly as if the audio helper had transcribed it."""
    if not CALL or CALL.state != "listening":
        return {"error": "start a call first"}
    CALL.hear_seq = getattr(CALL, "hear_seq", 0) + 1
    await on_transcript(CALL, {"segment_id": f"typed{CALL.hear_seq}", "text": body.text, "is_final": True})
    return {"ok": True}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    HUB.sockets.add(ws)
    try:
        await ws.send_text(json.dumps({
            "type": "hello", "protocol": 1, "agent": AGENT_NAME,
            "models": {"fast": MODEL, "slow": SLOW_MODEL},
            "playbook": {"name": S.salesbook_name, "entries": len(S.entries)}}))
        message, ok = await devices_message()
        await ws.send_text(json.dumps(message))
        if CALL:
            await ws.send_text(json.dumps({"type": "state", "session_id": CALL.id, "state": CALL.state,
                                           "started_at": CALL.started_at, "error": None}))
        if not ok:
            await ws.send_text(json.dumps({"type": "notice", "level": "warning", "message":
                "Audio helper not running. Start Girard with start.ps1."}))
        while True:
            raw = await ws.receive_text()
            try:
                command = json.loads(raw)
            except json.JSONDecodeError:
                continue
            try:
                await handle(command)
            except Exception as e:
                await HUB.notice(f"{command.get('type')} failed: {type(e).__name__}: {e}", "error")
    except WebSocketDisconnect:
        pass
    finally:
        HUB.sockets.discard(ws)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", 8000)))
