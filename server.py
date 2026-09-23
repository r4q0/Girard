"""
Girard demo portal: send transcript lines, get fast lane advice cards.

Runs the fast lane on Nebius Token Factory (serverless, pay per token).

Usage:
    pip install openai fastapi uvicorn python-dotenv
    # put NEBIUS_API_KEY=... in .env
    python server.py            # then open http://localhost:8000
"""
import asyncio
import json
import os
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from openai import AsyncOpenAI
from pydantic import BaseModel

load_dotenv()

ROOT = Path(__file__).parent
BASE_URL = "https://api.tokenfactory.nebius.com/v1"
MODEL = os.environ.get("GIRARD_MODEL", "Qwen/Qwen3-30B-A3B-Instruct-2507")
# Reasoning models (e.g. Nemotron Nano) must have thinking switched off, or they
# spend seconds reasoning before the card
EXTRA_BODY = {"chat_template_kwargs": {"enable_thinking": False}} if "Nemotron" in MODEL else None
# USD per token, from the Token Factory model catalog (/v1/models?verbose=true)
PRICE_IN = 0.10 / 1_000_000
PRICE_OUT = 0.30 / 1_000_000
RECENT_LINES = 10
BACKCHANNELS = {
    "yeah", "yes", "yep", "ok", "okay", "right", "sure", "mm", "mhm", "mmhmm", "mm-hmm",
    "uh-huh", "uh huh", "hmm", "i see", "got it", "true", "exactly", "fine", "cool", "no",
}

client = AsyncOpenAI(base_url=BASE_URL, api_key=os.environ["NEBIUS_API_KEY"])

CARD_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": ["string", "null"]},
        "say": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "q": {"type": ["string", "null"]},
    },
    "required": ["id"],
    "additionalProperties": False,
}


def card_schema(exclude=()):
    """Schema whose id can only be a salesbook id (minus `exclude`) or null.
    Makes invented ids impossible. Excluding shown ids tested worse: the model
    then picks another wrong card instead of null, so repeats are filtered after."""
    ids = [i for i in S.entries if i not in exclude]
    if "comp_unknown" not in ids:
        ids.append("comp_unknown")  # always allowed; repeats are per vendor name
    schema = json.loads(json.dumps(CARD_SCHEMA))
    schema["properties"]["id"] = {"anyOf": [{"type": "string", "enum": ids}, {"type": "null"}]}
    return schema

SYSTEM_TEMPLATE = """You help a sales rep respond live to a prospect on a sales call.
You only hear the prospect (CUSTOMER). The rep's side is not transcribed.
React only to the line under NEW. Lines under EARLIER were already handled;
use them only to understand the NEW line, never react to them again.

Return {{"id":null}} when:
- it is small talk, a greeting, or a filler reply
- the NEW line just answers a question with plain facts
  (numbers, names, who does what) and raises nothing new
- the NEW line is not a question, objection, signal, or mention
- its topic is in CARDS SHOWN (never return an id listed there)
- the playbook has nothing relevant

Otherwise pick the single most useful playbook entry.
Match on Triggers and Mentions. Respect "Not:" lines.
If several apply: risk > obj > ans > comp > sig

RULES
- Use only facts from the playbook. Never invent anything.
- "say": sentence openers the rep starts with and finishes in
  their own words. Usually 2, max 3. Max 10 words each.
- Follow the entry's Say line and the DON'TS. Never put INTERNAL ONLY facts in "say".
- Calm, plain, understated. No hype.
- Write in English.
- The transcript is speech recognition and may contain errors.
  Interpret names and terms generously.
- Unknown vendor or product mentioned: use comp_unknown and put
  its name in "q". Otherwise "q" is null.

OUTPUT: JSON only.
{{"id":"<playbook id>","say":["...","..."],"q":null}}
or
{{"id":null}}

PLAYBOOK
{playbook}

EXAMPLES
{examples}"""

EXAMPLES = """CARDS SHOWN: none
EARLIER: (none)
NEW: CUSTOMER: So what's your hourly rate, roughly?
-> {"id":"obj_hourly_01","say":["We don't work by the hour...","You pay a fixed price for the result...","What does this process cost you today..."],"q":null}

CARDS SHOWN: none
EARLIER: (none)
NEW: CUSTOMER: Where would our customer data be stored?
-> {"id":"ans_data_01","say":["Everything stays in the Netherlands...","No outside AI provider sees your documents...","We sign an NDA before we start..."],"q":null}

CARDS SHOWN: none
EARLIER: (none)
NEW: CUSTOMER: We're also talking to a company called Brightflow.
-> {"id":"comp_unknown","say":["What made you look at them...","What's missing for you today..."],"q":"Brightflow"}

CARDS SHOWN: none
EARLIER: (none)
NEW: CUSTOMER: Yeah, that makes sense.
-> {"id":null}

CARDS SHOWN: none
EARLIER: (none)
NEW: CUSTOMER: Around two hundred a week, mostly our office manager.
-> {"id":null}

CARDS SHOWN: obj_hourly_01
EARLIER: CUSTOMER: What's your hourly rate?
NEW: CUSTOMER: But roughly how many hours would it take you?
-> {"id":null}

CARDS SHOWN: sig_inbox_01
EARLIER: CUSTOMER: Our shared inbox gets the same questions all day.
NEW: CUSTOMER: I'd have to run this past my co-owner first.
-> {"id":"risk_partner_01","say":["What will your co-owner want to know...","Shall we do a short call with both of you..."],"q":null}"""

ENTRY_RE = re.compile(r"^\[([a-z0-9_]+)\]\s*([A-Za-z ]+):\s*(.*)$")


def parse_salesbook(text):
    """Return {id: {type, label, title, details}} from bracketed entries."""
    entries, cur = {}, None
    for line in text.splitlines():
        m = ENTRY_RE.match(line.strip())
        if m:
            cur = m.group(1)
            entries[cur] = {"type": cur.split("_")[0], "label": m.group(2).strip(),
                            "title": m.group(3).strip(), "details": []}
        elif cur and line.strip() and not line.startswith("=="):
            entries[cur]["details"].append(line.strip())
        else:
            cur = None
    return entries


class Session:
    def __init__(self):
        self.settings = {"schema": True, "hedge": True, "hedge_ms": 450, "timeout_ms": 3000,
                         "speculate": True, "min_words": 3}
        self.warm = None
        self.last_request = 0.0
        self.load_salesbook("salesbook_koref.txt")

    def load_salesbook(self, name):
        text = (ROOT / name).read_text(encoding="utf-8")
        self.salesbook_name = name
        self.entries = parse_salesbook(text)
        # Built once, never reformatted, so the provider can reuse its prefix cache
        self.system_prompt = SYSTEM_TEMPLATE.format(playbook=text.strip(), examples=EXAMPLES)
        self.reset()

    def reset(self):
        self.summary = ""
        self.cards_shown = []
        self.transcript = []  # {speaker, text}
        self.cards = []       # shown cards, newest last
        self.metrics = []     # one per LLM request
        self.inflight = None  # Run for the latest final line
        self.spec = None      # Run started early on partial speech

    def messages_for(self, text):
        """Prompt for `text` as the NEW line, as if it were appended to the transcript."""
        recent = self.transcript[-(RECENT_LINES - 1):] + [{"speaker": "CUSTOMER", "text": text}]
        return [{"role": "system", "content": self.system_prompt},
                {"role": "user", "content": build_user_message(self.summary, self.cards_shown, recent)}]


def build_user_message(summary, cards_shown, recent):
    """recent: list of {speaker, text}; the last line is the NEW one."""
    earlier = "\n".join(f"{l['speaker']}: {l['text']}" for l in recent[:-1]) or "(none)"
    new = recent[-1]
    return (f"CALL SO FAR:\n{summary.strip() or '(start of call)'}\n\n"
            f"CARDS SHOWN: {', '.join(cards_shown) or 'none'}\n\n"
            f"EARLIER (context only, already handled):\n{earlier}\n\n"
            f"NEW:\n{new['speaker']}: {new['text']}")


S = Session()


def is_backchannel(text):
    t = re.sub(r"[^\w\s'-]", "", text.lower()).strip()
    if not t:
        return True
    if t in BACKCHANNELS:
        return True
    words = t.split()
    return len(words) <= 3 and all(w in BACKCHANNELS for w in words)


async def attempt(idx, messages, t0, race, on_text=None, schema=None):
    """One streaming request. Loses the race if another attempt produced a token first."""
    kwargs = dict(model=MODEL, messages=messages, temperature=0, max_tokens=120,
                  stream=True, stream_options={"include_usage": True}, extra_body=EXTRA_BODY)
    if S.settings["schema"]:
        kwargs["response_format"] = {"type": "json_schema",
                                     "json_schema": {"name": "card", "schema": schema or CARD_SCHEMA, "strict": True}}
    text, ttft, id_ms, usage = "", None, None, None
    stream = await client.chat.completions.create(**kwargs)
    try:
        async for ch in stream:
            if ch.choices and ch.choices[0].delta.content:
                if ttft is None:
                    ttft = (time.perf_counter() - t0) * 1000
                    if race["winner"] is None:
                        race["winner"] = idx
                        race["event"].set()
                    elif race["winner"] != idx:
                        return None
                text += ch.choices[0].delta.content
                if on_text and race["winner"] == idx:
                    on_text(text)
                if id_ms is None and re.search(r'"id"\s*:\s*(null|"[^"]*")', text):
                    id_ms = (time.perf_counter() - t0) * 1000
            if ch.usage:
                usage = ch.usage
    finally:
        await stream.close()
    return {"text": text, "ttft_ms": ttft, "id_ms": id_ms,
            "total_ms": (time.perf_counter() - t0) * 1000, "usage": usage}


async def fast_lane(messages, on_text=None, exclude=()):
    """Race one request (plus a hedge if enabled) against the hard timeout."""
    st = S.settings
    # id is always limited to real salesbook ids; "enum" also removes ids already shown
    schema = card_schema(exclude if st.get("enum") else ())
    t0 = time.perf_counter()
    deadline = t0 + st["timeout_ms"] / 1000
    hedge_at = t0 + st["hedge_ms"] / 1000 if st["hedge"] else None
    race = {"winner": None, "event": asyncio.Event()}
    tasks = [asyncio.create_task(attempt(0, messages, t0, race, on_text, schema))]
    evt = asyncio.create_task(race["event"].wait())
    try:
        while not evt.done():
            now = time.perf_counter()
            if now >= deadline:
                return {"timeout": True, "hedged": len(tasks) > 1, "total_ms": (now - t0) * 1000}
            live = [t for t in tasks if not t.done()]
            if not live:
                for t in tasks:
                    if t.exception():
                        raise t.exception()
                return {"error": "no output", "total_ms": (now - t0) * 1000}
            wait_until = min(deadline, hedge_at) if hedge_at and len(tasks) == 1 else deadline
            await asyncio.wait([evt, *live], timeout=max(0, wait_until - now),
                               return_when=asyncio.FIRST_COMPLETED)
            if hedge_at and len(tasks) == 1 and not evt.done() and time.perf_counter() >= hedge_at:
                tasks.append(asyncio.create_task(attempt(1, messages, t0, race, on_text, schema)))
        winner = tasks[race["winner"]]
        try:
            res = await asyncio.wait_for(winner, max(0.05, deadline - time.perf_counter()))
        except asyncio.TimeoutError:
            return {"timeout": True, "hedged": len(tasks) > 1,
                    "total_ms": (time.perf_counter() - t0) * 1000}
        res["hedged"] = len(tasks) > 1
        res["winner"] = race["winner"]
        return res
    finally:
        evt.cancel()
        for t in tasks:
            if not t.done():
                t.cancel()


def _read_string(s, i):
    """Read a JSON string body starting after its opening quote. Returns (value, end, closed)."""
    out, j = [], i
    while j < len(s):
        c = s[j]
        if c == "\\":
            if j + 1 >= len(s):
                break
            try:
                out.append(json.loads('"' + s[j:j + 2] + '"'))
            except json.JSONDecodeError:
                out.append(s[j + 1])
            j += 2
            continue
        if c == '"':
            return "".join(out), j + 1, True
        out.append(c)
        j += 1
    return "".join(out), j, False


def partial_card(text):
    """Best-effort parse of a card JSON that is still streaming in."""
    card = {}
    m = re.search(r'"id"\s*:\s*(null|")', text)
    if m:
        if m.group(1) == "null":
            card["id"] = None
        else:
            val, _, closed = _read_string(text, m.end())
            if closed:
                card["id"] = val
    m = re.search(r'"say"\s*:\s*\[', text)
    if m:
        say, j = [], m.end()
        while j < len(text) and text[j] != "]":
            if text[j] == '"':
                val, j, closed = _read_string(text, j + 1)
                say.append(val)
                if not closed:
                    break
            else:
                j += 1
        card["say"] = say
    m = re.search(r'"q"\s*:\s*"', text)
    if m:
        val, _, closed = _read_string(text, m.end())
        if closed:
            card["q"] = val
    return card


def pct(values, p):
    v = sorted(values)
    if not v:
        return None
    k = min(len(v) - 1, max(0, round(p / 100 * (len(v) - 1))))
    return v[k]


def metrics_summary():
    ok = [m for m in S.metrics if m.get("ttft_ms") is not None]
    ttft = [m["ttft_ms"] for m in ok]
    total = [m["total_ms"] for m in ok]
    prompt = sum(m.get("prompt_tokens") or 0 for m in S.metrics)
    cached = sum(m.get("cached_tokens") or 0 for m in S.metrics)
    cost = sum(m.get("cost_usd") or 0 for m in S.metrics)
    n = len(S.metrics)
    return {
        "requests": n,
        "cards": sum(1 for m in S.metrics if m.get("card_id")),
        "timeouts": sum(1 for m in S.metrics if m.get("timeout")),
        "hedged": sum(1 for m in S.metrics if m.get("hedged")),
        "invalid": sum(1 for m in S.metrics if m.get("invalid")),
        "repeats": sum(1 for m in S.metrics if m.get("repeat")),
        "prompt_tokens": prompt,
        "cached_tokens": cached,
        "completion_tokens": sum(m.get("completion_tokens") or 0 for m in S.metrics),
        "cache_hit_rate": cached / prompt if prompt else None,
        "cost_usd": cost,
        # rough projection: ~10 customer lines per minute reach the model
        "cost_per_call_hour_usd": cost / n * 600 if n else None,
        "ttft_p50": pct(ttft, 50), "ttft_p95": pct(ttft, 95), "ttft_p99": pct(ttft, 99),
        "total_p50": pct(total, 50), "total_p95": pct(total, 95),
        "decide_p50": pct([m["id_ms"] for m in ok if m.get("id_ms")], 50),
        "after_speech_p50": pct([m["after_speech_ms"] for m in S.metrics if "after_speech_ms" in m], 50),
        "after_speech_p95": pct([m["after_speech_ms"] for m in S.metrics if "after_speech_ms" in m], 95),
        "early": sum(1 for m in S.metrics if m.get("early")),
        "warm": S.warm,
    }


@asynccontextmanager
async def lifespan(_app):
    try:
        await warmup()
    except Exception:
        pass
    task = asyncio.create_task(keep_warm())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)


class Line(BaseModel):
    text: str


class Text(BaseModel):
    text: str = ""


class Name(BaseModel):
    name: str


class Settings(BaseModel):
    schema_on: bool | None = None
    hedge: bool | None = None
    hedge_ms: int | None = None
    timeout_ms: int | None = None
    speculate: bool | None = None
    min_words: int | None = None


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/config")
def config():
    books = sorted(p.name for p in ROOT.glob("salesbook_*.txt"))
    return {"model": MODEL, "salesbooks": books, "salesbook": S.salesbook_name,
            "entries": S.entries, "settings": S.settings,
            "price_in_per_m": PRICE_IN * 1e6, "price_out_per_m": PRICE_OUT * 1e6,
            "system_prompt_chars": len(S.system_prompt)}


@app.get("/api/state")
def state():
    return {"transcript": S.transcript, "cards": S.cards, "summary": S.summary,
            "cards_shown": S.cards_shown, "metrics": metrics_summary(),
            "requests": S.metrics[-30:]}


@app.get("/api/demo")
def demo():
    p = ROOT / "demo_call.txt"
    lines = []
    for raw in p.read_text(encoding="utf-8").splitlines():
        if ":" in raw and raw.split(":", 1)[0].strip() == "CUSTOMER":
            sp, tx = raw.split(":", 1)
            lines.append({"speaker": sp.strip(), "text": tx.strip()})
    return lines


@app.post("/api/reset")
async def reset():
    """Start a new call. Warms the cache so the first real line is fast."""
    for run in (S.spec, S.inflight):
        if run:
            run.cancel()
    S.reset()
    try:
        warm = await warmup()
    except Exception as e:
        warm = {"error": f"{type(e).__name__}: {e}"}
    return {"ok": True, "warm": warm}


@app.post("/api/salesbook")
async def set_salesbook(body: Name):
    if not re.fullmatch(r"salesbook_[\w-]+\.txt", body.name) or not (ROOT / body.name).exists():
        return {"error": "unknown salesbook"}
    S.load_salesbook(body.name)
    try:
        await warmup()  # new salesbook means a new prompt prefix
    except Exception:
        pass
    return {"ok": True}


@app.post("/api/summary")
def set_summary(body: Text):
    S.summary = body.text
    return {"ok": True}


@app.post("/api/settings")
def set_settings(body: Settings):
    if body.schema_on is not None:
        S.settings["schema"] = body.schema_on
    for k in ("hedge", "hedge_ms", "timeout_ms", "speculate", "min_words"):
        v = getattr(body, k)
        if v is not None:
            S.settings[k] = v
    return S.settings


def finalize(text, res):
    """Turn a finished fast lane result into (card, metrics) and update call state."""
    m = {"line": text, "timeout": res.get("timeout", False), "hedged": res.get("hedged", False),
         "ttft_ms": res.get("ttft_ms"), "id_ms": res.get("id_ms"), "total_ms": res.get("total_ms")}
    usage = res.get("usage")
    if usage:
        details = getattr(usage, "prompt_tokens_details", None)
        m["prompt_tokens"] = usage.prompt_tokens
        m["completion_tokens"] = usage.completion_tokens
        m["cached_tokens"] = (getattr(details, "cached_tokens", None) if details else None) or 0
        m["cost_usd"] = usage.prompt_tokens * PRICE_IN + usage.completion_tokens * PRICE_OUT
        if m["hedged"]:  # the losing request is billed too; estimate its prompt cost
            m["cost_usd"] += usage.prompt_tokens * PRICE_IN

    card = None
    if "text" in res:
        m["raw"] = res["text"]
        try:
            out = json.loads(res["text"])
            cid = out.get("id")
            key = f"comp_unknown:{out.get('q')}" if cid == "comp_unknown" else cid
            if cid and key in S.cards_shown:
                # The prompt says to stay silent on shown topics; enforce it here too
                m["repeat"] = cid
            elif cid and (cid in S.entries or cid == "comp_unknown"):
                card = {"id": cid, "say": out.get("say") or [], "q": out.get("q"), "line": text,
                        "entry": S.entries.get(cid)}
                S.cards_shown.append(key)
                S.cards.append(card)
                m["card_id"] = cid
            elif cid:
                m["invalid"] = f"unknown id {cid}"
        except json.JSONDecodeError:
            m["invalid"] = "not valid JSON"
    S.metrics.append(m)
    return card, m


def sse(obj):
    return f"data: {json.dumps(obj)}\n\n"


def event_stream(gen):
    return StreamingResponse(gen, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def single(event):
    yield sse(event)


def norm(text):
    """Compare lines the way speech-to-text partials and finals differ: case and punctuation."""
    return " ".join(re.sub(r"[^\w\s']", " ", text.lower()).split())


class Run:
    """One fast lane request. Its events are kept, so a request started on partial
    speech can be handed to the final line and replayed from the start."""

    def __init__(self, text, messages):
        self.text, self.key = text, norm(text)
        self.t0 = time.perf_counter()
        self.events, self.new, self.last = [], asyncio.Event(), {}
        self.card_ms = None  # when a card id was first known, relative to t0
        S.last_request = time.time()
        self.task = asyncio.create_task(fast_lane(messages, self.on_text))
        self.task.add_done_callback(lambda _t: self.push(None))

    def push(self, event):
        self.events.append(event)
        self.new.set()

    def on_text(self, raw):
        card = partial_card(raw)
        if "id" not in card or card == self.last:
            return
        self.last = card
        cid = card["id"]
        ms = round((time.perf_counter() - self.t0) * 1000)
        event = {"type": "partial", "id": cid, "say": card.get("say", []), "q": card.get("q"), "ms": ms}
        if cid:
            self.card_ms = self.card_ms or ms
            event["entry"] = S.entries.get(cid)
            event["repeat"] = cid != "comp_unknown" and cid in S.cards_shown
        self.push(event)

    async def follow(self):
        """Yield every event from the start, then new ones as they arrive, until done."""
        i = 0
        while True:
            while i < len(self.events):
                event = self.events[i]
                i += 1
                if event is None:
                    return
                yield event
            self.new.clear()
            await self.new.wait()

    def cancel(self):
        if not self.task.done():
            self.task.cancel()


@app.post("/api/partial")
async def add_partial(body: Line):
    """Partial speech (the prospect is still talking). If it looks like a sentence,
    start the fast lane early. Streams the same events as /api/line, ending with
    "ready" (waiting for the final line) or "cancelled" (the prospect kept talking)."""
    text = body.text.strip()
    st = S.settings
    if not st["speculate"] or len(text.split()) < st["min_words"] or is_backchannel(text):
        return event_stream(single({"type": "waiting"}))
    if S.spec and S.spec.key == norm(text):
        return event_stream(single({"type": "same"}))
    if S.spec:
        S.spec.cancel()  # an older guess at this sentence
    run = S.spec = Run(text, S.messages_for(text))

    async def events():
        async for event in run.follow():
            yield sse(event)
        if run.task.cancelled():
            yield sse({"type": "cancelled", "reason": "prospect kept talking"})
        else:
            yield sse({"type": "ready"})

    return event_stream(events())


@app.post("/api/line")
async def add_line(body: Line):
    """Final prospect line (end of speech). Reuses the early request if it was started
    on the same words, otherwise starts one. Streams "partial" events, then "done",
    or a single "skipped" / "cancelled" / "error"."""
    text = body.text.strip()
    if not text:
        return event_stream(single({"type": "error", "error": "text required"}))
    t_final = time.perf_counter()
    spec, S.spec = S.spec, None
    reused = spec is not None and spec.key == norm(text) and not spec.task.cancelled()
    if spec and not reused:
        spec.cancel()
    # A newer line makes any earlier request stale
    if S.inflight and S.inflight is not spec:
        S.inflight.cancel()
    if is_backchannel(text):
        S.transcript.append({"speaker": "CUSTOMER", "text": text})
        return event_stream(single({"type": "skipped", "reason": "backchannel filtered, no model call"}))

    run = spec if reused else Run(text, S.messages_for(text))
    S.transcript.append({"speaker": "CUSTOMER", "text": text})
    S.inflight = run
    head_start = (t_final - run.t0) * 1000 if reused else 0.0

    async def events():
        async for event in run.follow():
            yield sse(event)
        try:
            res = run.task.result()
        except asyncio.CancelledError:
            yield sse({"type": "cancelled", "reason": "a newer prospect line arrived"})
            return
        except Exception as e:  # surface API errors in the portal
            yield sse({"type": "error", "error": f"{type(e).__name__}: {e}"})
            return
        card, m = finalize(text, res)
        m["early"] = reused
        m["head_start_ms"] = round(head_start)
        if run.card_ms is not None:
            # What the rep feels: time from the end of speech until the card is on screen
            m["after_speech_ms"] = max(0, round(run.card_ms - head_start))
        yield sse({"type": "done", "card": card, "metrics": m})

    return event_stream(events())


async def warmup():
    """Prime the provider's prefix cache and our connection before the first real line.
    Several requests in parallel, because the cache lives per server and requests are spread."""
    t0 = time.perf_counter()
    messages = S.messages_for("Hello, thanks for making time.")
    kwargs = dict(model=MODEL, messages=messages, temperature=0, max_tokens=1, extra_body=EXTRA_BODY)
    if S.settings["schema"]:
        kwargs["response_format"] = {"type": "json_schema",
                                     "json_schema": {"name": "card", "schema": card_schema(), "strict": True}}
    results = await asyncio.gather(*(client.chat.completions.create(**kwargs) for _ in range(3)),
                                   return_exceptions=True)
    ok = [r for r in results if not isinstance(r, Exception)]
    cached = []
    for r in ok:
        details = getattr(r.usage, "prompt_tokens_details", None) if r.usage else None
        cached.append((getattr(details, "cached_tokens", None) if details else None) or 0)
    S.warm = {"ms": round((time.perf_counter() - t0) * 1000), "ok": len(ok), "sent": len(results),
              "prompt_tokens": ok[0].usage.prompt_tokens if ok and ok[0].usage else None,
              "cached_tokens": cached, "at": time.time()}
    S.last_request = time.time()
    return S.warm


@app.post("/api/warmup")
async def warmup_route():
    try:
        return await warmup()
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


async def keep_warm():
    """Re-prime the cache when the call has been quiet for a while."""
    while True:
        await asyncio.sleep(20)
        if time.time() - S.last_request > 60:
            try:
                await warmup()
            except Exception:
                pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", 8000)))
