# /// script
# requires-python = ">=3.11"
# dependencies = ["openai>=1.40", "python-dotenv"]
# ///
"""Generate example advice in several styles so the user can pick one.

Usage: uv run bench/advice/examples.py [model]   (writes bench/advice-examples.md)
"""
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
client = OpenAI(base_url="https://api.tokenfactory.nebius.com/v1", api_key=os.environ["NEBIUS_API_KEY"], timeout=60)
MODEL = sys.argv[1] if len(sys.argv) > 1 else "zai-org/GLM-5.2"
CONTEXT = (ROOT / "bench" / "koref-context.json").read_text(encoding="utf-8")

STYLES = {
    "A": ("Three short bullets", "Exactly 3 bullets, each 8 words or fewer. Telegraphic, no full sentences."),
    "B": ("Two bullets + a question", "2 bullets of 12 words or fewer, then 1 bullet that is a question to ask, in quotes."),
    "C": ("Say this + ask this", "Exactly 2 bullets: first starts with 'Say:' and is one sentence the rep can say out loud; second starts with 'Ask:' and is one question in quotes."),
    "D": ("Headline + two bullets", "First bullet is a headline of what is really going on, 6 words or fewer, ending with a colon-free label like 'Price objection' or 'Buying signal'. Then 2 bullets of 12 words or fewer."),
    "E": ("One point only", "Exactly 1 bullet: the single most useful thing to do or say now, 15 words or fewer."),
    "F": ("Numbers first", "2 or 3 bullets of 14 words or fewer. Whenever the prospect gives or implies numbers, work out the money (yearly cost, payback) and show it; otherwise give the one number they should ask for."),
}

CALL = [
    "So basically we have three people who spend most of their morning typing incoming orders from email into Exact.",
    "What's your hourly rate?",
    "We're also talking to Flowbase, they said it would be about forty cents per document.",
    "We tried an AI pilot last year and honestly it went nowhere.",
    "Can you just send me some information and I'll have a look?",
    "We're only twelve people, is this even for companies our size?",
    "Our planner quit two months ago and we still can't find anyone.",
    "Will this mean I have to let people go?",
    "And what happens if it doesn't actually save us anything?",
    "Sorry, what's your hourly rate again? I still don't get how you price this.",
]


def system(style_rule):
    return f"""You are Girard, a live sales copilot. A sales rep is on a call; you only hear the prospect.
For the NEW prospect line, give the rep advice they can use in the next 10 seconds.

FORMAT: {style_rule}

Rules:
- Tailor to what the prospect actually said: reuse their words, numbers, systems and names.
- Use only facts from COMPANY CONTEXT. Never say anything in never_say. Never invent numbers the prospect did not give (except the documented ~EUR 48/hr average, labelled as an average).
- If a topic comes back, build on the advice already given instead of repeating it; a repeated point means it matters or is still unanswered.

Answer with JSON only: {{"bullets": ["..."]}}

COMPANY CONTEXT:
{CONTEXT}"""


def ask(style_key, i):
    for _ in range(3):  # retry on invalid JSON, like the app will
        b = ask_once(style_key, i)
        if not b[0].startswith("(invalid"):
            return b
    return b


def ask_once(style_key, i):
    user = "RECENT PROSPECT LINES:\n" + "\n".join(f"- {l}" for l in CALL[max(0, i - 6):i]) + f"\n\nNEW: {CALL[i]}"
    r = client.chat.completions.create(
        model=MODEL, temperature=0.3, max_tokens=600, reasoning_effort="none",
        messages=[{"role": "system", "content": system(STYLES[style_key][1])}, {"role": "user", "content": user}],
    )
    text = r.choices[0].message.content or ""
    m = re.search(r"\{.*\}", text, flags=re.S)
    try:
        return json.loads(m.group(0))["bullets"]
    except Exception:
        return [f"(invalid output: {text[:120]})"]


jobs = [(s, i) for i in range(len(CALL)) for s in STYLES]
with ThreadPoolExecutor(12) as pool:
    answers = dict(zip(jobs, pool.map(lambda j: ask(*j), jobs)))

out = [
    "# Advice examples: pick a style",
    "",
    f"The same {len(CALL)} prospect lines (one Koref sales call, in order), each answered in 6 styles by {MODEL}.",
    "Tell me which style(s) you like, per line or overall, and anything you'd change (length, tone, questions, numbers).",
    "",
    "| Style | Shape |",
    "| --- | --- |",
] + [f"| **{k}** | {name}: {rule} |" for k, (name, rule) in STYLES.items()] + [""]
for i, line in enumerate(CALL):
    out += [f"## {i + 1}. “{line}”", ""]
    for k, (name, _) in STYLES.items():
        out.append(f"**{k} · {name}**")
        out += [f"- {b}" for b in answers[(k, i)]]
        out.append("")
(ROOT / "bench" / "advice-examples.md").write_text("\n".join(out), encoding="utf-8")
print("wrote bench/advice-examples.md")
