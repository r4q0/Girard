# /// script
# requires-python = ">=3.11"
# dependencies = ["openai>=1.40", "python-dotenv", "rapidfuzz>=3.9"]
# ///
"""Does the filter keep advice quality? Same messy call, advice from raw lines vs filtered lines.

Usage: uv run bench/advice/filter_check.py   (writes bench/filter-check.md)
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
sys.path.insert(0, str(ROOT / "audio"))
from girard_audio.filter import LineFilter  # noqa: E402

load_dotenv(ROOT / ".env")
client = OpenAI(base_url="https://api.tokenfactory.nebius.com/v1", api_key=os.environ["NEBIUS_API_KEY"], timeout=60)
ns = {"__file__": str(ROOT / "bench/advice/examples.py")}
exec((ROOT / "bench/advice/examples.py").read_text(encoding="utf-8").split("jobs = [")[0], ns)
SYSTEM = ns["system"](ns["STYLES"]["E"][1])

MESSY = [
    "Yeah, yeah, okay.",
    "So um, basically, we we have like three people who, you know, spend most of their morning uh typing orders from email into exact.",
    "Mm-hmm.",
    "And uh what's your, like, hourly rate?",
    "Right.",
    "I mean, we're also sort of talking to flow base and they, uh, they said like forty cents a document.",
    "Okay. Sure.",
    "Honestly the the last IT company we we worked with, uh, went way over budget.",
    "Uh-huh, got it.",
    "Right now we use zap here for, like, some of it but it it keeps, you know, breaking.",
    "Maybe.",
    "I'd, um, I'd need to discuss this with my co-owner first.",
]


def filtered_lines():
    f = LineFilter(["Zapier", "Flowbase", "Exact", "Koref"])
    out = []
    for i, raw in enumerate(MESSY):
        r = f.process(raw, now=float(i))
        if r.text:
            out.append(r.text)
    last = f.flush_due(now=1e9)
    return out + ([last.text] if last else [])


def advise(lines):
    results = []
    for i, line in enumerate(lines):
        user = "RECENT PROSPECT LINES:\n" + "\n".join(f"- {l}" for l in lines[max(0, i - 6):i]) + f"\n\nNEW: {line}"
        t = time.perf_counter()
        r = client.chat.completions.create(model="zai-org/GLM-5.2", temperature=0, max_tokens=300,
                                           reasoning_effort="none",
                                           messages=[{"role": "system", "content": SYSTEM},
                                                     {"role": "user", "content": user}])
        text = r.choices[0].message.content or ""
        m = re.search(r"\{.*\}", text, re.S)
        try:
            bullets = json.loads(m.group(0))["bullets"]
        except Exception:
            bullets = [text[:150]]
        results.append((line, bullets, time.perf_counter() - t, r.usage.prompt_tokens))
    return results


clean = filtered_lines()
with ThreadPoolExecutor(2) as p:
    raw_res, clean_res = p.map(advise, [MESSY, clean])

out = ["# Filter check: advice from raw vs filtered lines", "",
       f"The same messy call ({len(MESSY)} raw chunks) went to GLM-5.2 (style E) twice: every raw chunk, "
       f"and the {len(clean)} lines the filter lets through. Judge whether the filtered advice is as good.", "",
       f"- **Advice requests:** raw {len(raw_res)}, filtered {len(clean_res)}.",
       f"- **Average time per advice:** raw {sum(r[2] for r in raw_res) / len(raw_res):.2f} s, "
       f"filtered {sum(r[2] for r in clean_res) / len(clean_res):.2f} s.", "",
       "## Filtered (what Girard will do)", ""]
for line, bullets, _, _ in clean_res:
    out += [f"**Heard:** {line}  ", f"→ {' / '.join(bullets)}", ""]
out += ["## Raw (no filter)", ""]
for line, bullets, _, _ in raw_res:
    out += [f"**Heard:** {line}  ", f"→ {' / '.join(bullets)}", ""]
(ROOT / "bench" / "filter-check.md").write_text("\n".join(out), encoding="utf-8")
print("\n".join(out))
