# /// script
# requires-python = ">=3.11"
# dependencies = ["openai>=1.40", "python-dotenv"]
# ///
"""Run every Nebius chat model on the same advice and memory tasks.

Usage: uv run bench/models/bakeoff.py [model ...]
Writes bench/models/results.json; render with report.py.
"""
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
BASE = "https://api.tokenfactory.nebius.com/v1"
client = OpenAI(base_url=BASE, api_key=os.environ["NEBIUS_API_KEY"], timeout=60)

CONTEXT = (ROOT / "bench" / "koref-context.json").read_text(encoding="utf-8")

ADVICE_SYSTEM = f"""You are Girard, a live sales copilot. A sales rep is on a call; you only hear the prospect.
For the NEW prospect line, give the rep short, specific advice they can use in the next 10 seconds.

Rules:
- 2 or 3 bullets, each 12 words or fewer.
- Tailor to what the prospect actually said: reuse their words, numbers, systems and names.
- At most one bullet is a question to ask, written in quotes.
- Use only facts from COMPANY CONTEXT. Never say anything in never_say.
- If a topic comes back, build on the advice already given instead of repeating it; a repeated point means it matters or is still unanswered.
- If the line needs no advice, return an empty bullets list.
- "company": the name of an outside company or product the prospect just named (competitor, current tool, parent company, past vendor), else null. Never the rep's own company.

Answer with JSON only: {{"bullets": ["..."], "company": null}}

COMPANY CONTEXT:
{CONTEXT}"""

MEMORY = {
    "budget": None,
    "decision_makers": ["Co-owner (not on the call)"],
    "pains": ["3 people type email orders into Exact every morning"],
    "objections": [{"topic": "hourly rate", "status": "open"}],
    "companies": ["Exact", "Flowbase"],
}

CALL = [
    "So basically we have three people who spend most of their morning typing incoming orders from email into Exact.",
    "What's your hourly rate?",
    "We're also talking to Flowbase, they said it would be about forty cents per document.",
    "Honestly the last IT company we worked with went way over budget.",
    "Is our data going to leave the Netherlands?",
    "Right now we use Zapier for some of it but it keeps breaking.",
    "I'd need to discuss this with my co-owner first.",
    "Sorry, what's your hourly rate again? I still don't get how you price this.",
]

MEMORY_SYSTEM = """You maintain the structured memory of a sales call (prospect side only).
Return JSON only with exactly these keys:
{"budget": string|null, "decision_makers": [string], "pains": [string], "objections": [{"topic": string, "status": "open"|"answered"}], "companies": [string], "timeline": string|null}
Only record what was actually said. Keep each item under 15 words."""


def advice_messages(i):
    recent = CALL[max(0, i - 6):i]
    given = [f"line {j + 1}: (advice shown)" for j in range(i)]
    user = (
        f"CALL MEMORY:\n{json.dumps(MEMORY)}\n\n"
        f"ADVICE ALREADY GIVEN: {len(given)} times\n\n"
        "RECENT PROSPECT LINES:\n" + "\n".join(f"- {l}" for l in recent) + "\n\n"
        f"NEW: {CALL[i]}"
    )
    return [{"role": "system", "content": ADVICE_SYSTEM}, {"role": "user", "content": user}]


def memory_messages():
    return [
        {"role": "system", "content": MEMORY_SYSTEM},
        {"role": "user", "content": "TRANSCRIPT:\n" + "\n".join(f"- {l}" for l in CALL)},
    ]


def parse_json(text):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


# Thinking off (or minimal) per model: live advice cannot wait for reasoning.
# Found by probing each option and keeping the one with the fewest tokens before the answer.
NO_THINK_TMPL = {"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}}
THINK_FALSE_TMPL = {"extra_body": {"chat_template_kwargs": {"thinking": False}}}
REASON_NONE = {"reasoning_effort": "none"}
REASON_LOW = {"reasoning_effort": "low"}
THINKING_OFF = {
    "openai/gpt-oss-120b": REASON_LOW,
    "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B": NO_THINK_TMPL,
    "zai-org/GLM-5.1": REASON_NONE,
    "zai-org/GLM-5.2": REASON_NONE,
    "zai-org/GLM-5.3": REASON_LOW,
    "zai-org/GLM-5.3-Flash": REASON_LOW,
    "deepseek-ai/DeepSeek-V4-Flash-0731": THINK_FALSE_TMPL,
    "deepseek-ai/DeepSeek-V4.1-Flash": THINK_FALSE_TMPL,
    "deepseek-ai/DeepSeek-V4-Pro-0813": REASON_NONE,
    "MiniMaxAI/MiniMax-M3": REASON_NONE,
    "moonshotai/Kimi-K2.6": THINK_FALSE_TMPL,
    "moonshotai/Kimi-K3": REASON_NONE,
    "moonshotai/Kimi-K2.7-Code": REASON_LOW,
    "nvidia/nemotron-3-super-120b-a12b": REASON_NONE,
    "nvidia/Nemotron-3_5-Lightning": REASON_NONE,
    "nvidia/Nemotron-3-Ultra-550b-a55b": REASON_NONE,
    "Qwen/Qwen3.5-397B-A17B": REASON_NONE,
}


def extra_for(model):
    return THINKING_OFF.get(model, {})


def run(model, messages, max_tokens):
    t0 = time.perf_counter()
    first = None
    out = []
    usage = None
    try:
        stream = client.chat.completions.create(
            model=model, messages=messages, temperature=0, max_tokens=max_tokens,
            stream=True, stream_options={"include_usage": True}, **extra_for(model),
        )
        for chunk in stream:
            if chunk.usage:
                usage = chunk.usage
            if chunk.choices and chunk.choices[0].delta.content:
                if first is None:
                    first = time.perf_counter() - t0
                out.append(chunk.choices[0].delta.content)
    except Exception as e:  # recorded, never fatal
        return {"error": f"{type(e).__name__}: {str(e)[:200]}"}
    text = "".join(out)
    return {
        "ttft": first,
        "total": time.perf_counter() - t0,
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "cached_tokens": getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", None),
        "text": text,
        "json": parse_json(text),
    }


def bench(model):
    print(f"start {model}", flush=True)
    run(model, advice_messages(0), 1000)  # warm the prompt cache, not counted
    advice = [run(model, advice_messages(i), 1000) for i in range(len(CALL))]
    memory = run(model, memory_messages(), 1500)
    print(f"done  {model}", flush=True)
    return {"model": model, "advice": advice, "memory": memory}


def chat_models():
    models = client.models.list().data
    return [m.id for m in models if "Embedding" not in m.id]


if __name__ == "__main__":
    models = sys.argv[1:] or chat_models()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(bench, models))
    out = ROOT / "bench" / "models" / "results.json"
    if sys.argv[1:] and out.exists():  # re-run of some models: replace just those
        old = json.loads(out.read_text(encoding="utf-8"))["results"]
        fresh = {r["model"] for r in results}
        results = [r for r in old if r["model"] not in fresh] + results
    out.write_text(json.dumps({"call": CALL, "results": results}, indent=1), encoding="utf-8")
    print(f"wrote {out}")
