# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx", "python-dotenv"]
# ///
"""Render bench/models/results.json into bench/model-comparison.md."""
import json
import os
import statistics
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

data = json.loads((ROOT / "bench" / "models" / "results.json").read_text(encoding="utf-8"))
models = httpx.get(
    "https://api.tokenfactory.nebius.com/v1/models?verbose=true",
    headers={"Authorization": f"Bearer {os.environ['NEBIUS_API_KEY']}"}, timeout=30,
).json()["data"]
price = {m["id"]: (float(m["pricing"]["prompt"]), float(m["pricing"]["completion"])) for m in models}


def cost(r, model):
    if r.get("prompt_tokens") is None:
        return None
    p, c = price.get(model, (0, 0))
    cached = r.get("cached_tokens") or 0
    # Nebius bills cached prompt tokens at a discount; list price is used here as an upper bound.
    return r["prompt_tokens"] * p + (r.get("completion_tokens") or 0) * c


def ms(x):
    return ", " if x is None else f"{x * 1000:.0f}"


rows = []
for res in data["results"]:
    m = res["model"]
    adv = res["advice"]
    ok = [a for a in adv if "error" not in a and a.get("ttft") is not None]
    valid = sum(1 for a in ok if isinstance(a.get("json"), dict) and isinstance(a["json"].get("bullets"), list))
    ttfts = sorted(a["ttft"] for a in ok)
    totals = sorted(a["total"] for a in ok)
    costs = [c for c in (cost(a, m) for a in ok) if c is not None]
    mem = res["memory"]
    rows.append({
        "model": m,
        "ok": len(ok), "valid": valid,
        "ttft_med": statistics.median(ttfts) if ttfts else None,
        "ttft_max": max(ttfts) if ttfts else None,
        "total_med": statistics.median(totals) if totals else None,
        "cost_1k": statistics.mean(costs) * 1000 if costs else None,
        "mem_total": mem.get("total"),
        "mem_valid": isinstance(mem.get("json"), dict),
        "errors": sorted({a["error"][:80] for a in adv if "error" in a}),
    })

rows.sort(key=lambda r: (r["valid"] < 8, r["total_med"] or 99))
n = len(data["call"])
out = [
    "# Model comparison (Nebius Token Factory)",
    "",
    f"Every chat model on Nebius ran the same {n}-line sales call (Koref as the seller) with the same draft advice prompt, plus one call-memory task. "
    "Times are measured from this laptop, one request at a time, after one warm-up request. "
    "Pick one **fast model** for live advice (speed matters most) and one **big model** for call memory and the debrief (quality matters most).",
    "",
    "- **First word**: time until the first visible word of advice (median / slowest).",
    "- **Full advice**: time until the whole answer is done (median).",
    "- **Valid**: answers that were proper JSON with bullets, out of " + str(n) + ".",
    "- **$ per 1,000 advice**: estimated at list price (cached prompt tokens are cheaper, so real cost is lower).",
    "- **Memory**: time for the call-memory task, and whether its JSON was valid.",
    "",
    "## My read",
    "",
    "- **Fast model (live advice): GLM-5.2.** Best advice of the fast group: reuses the prospect's words and numbers, asks sharp questions, noticed the repeated hourly-rate question (\"They keep asking hourly, explain once more\"). Full advice in ~0.8 s.",
    "- **Runner-up: gpt-oss-120b.** Fastest reliable model (~0.5 s full advice), solid but more generic.",
    "- **Avoid for advice:** MiniCPM-V-4.5 and Nemotron-3-Nano are fast but invent facts (\"Exact integration is standard for us\", \"your hourly rate is EUR 150\"); Qwen3-30B (the old model) invents numbers (\"~15 hours/week\").",
    "- **Big model (call memory + debrief): GLM-5.2 or Kimi-K3.** Both produced the most complete call memory (all three companies, all open objections). Kimi-K2.6 and Qwen3.5 wrongly recorded \"40 cents per document\" as the prospect's budget.",
    "- Thinking models only work here with thinking switched off; the table uses the right switch per model.",
    "",
    "| Model | First word (ms) | Full advice (ms) | Valid | $ per 1,000 advice | Memory (s) |",
    "| --- | --- | --- | --- | --- | --- |",
]
for r in rows:
    mem = ", " if r["mem_total"] is None else f"{r['mem_total']:.1f}{'' if r['mem_valid'] else ' (invalid)'}"
    c = ", " if r["cost_1k"] is None else f"{r['cost_1k']:.2f}"
    out.append(f"| {r['model']} | {ms(r['ttft_med'])} / {ms(r['ttft_max'])} | {ms(r['total_med'])} | {r['valid']}/{n} | {c} | {mem} |")

failed = [r for r in rows if r["errors"]]
if failed:
    out += ["", "**Errors:**", ""] + [f"- {r['model']}: {'; '.join(r['errors'])}" for r in failed]

out += ["", "## What each model actually said", "",
        "Read these to judge quality: specific to what the prospect said, short, no invented facts (Koref has no case studies).", ""]
for res in sorted(data["results"], key=lambda r: [x["model"] for x in rows].index(r["model"])):
    out += [f"<details><summary><b>{res['model']}</b></summary>", ""]
    for line, a in zip(data["call"], res["advice"]):
        out.append(f"**Prospect:** {line}  ")
        if "error" in a:
            out.append(f"_error: {a['error'][:120]}_")
        elif isinstance(a.get("json"), dict):
            for b in a["json"].get("bullets") or []:
                out.append(f"- {b}")
            if a["json"].get("company"):
                out.append(f"- _research:_ {a['json']['company']}")
        else:
            out.append(f"_not valid JSON:_ `{(a.get('text') or '')[:200]}`")
        out.append("")
    mj = res["memory"].get("json")
    out += ["**Call memory:**", "", "```json", json.dumps(mj, indent=1) if mj else (res["memory"].get("text") or res["memory"].get("error", ""))[:600], "```", "", "</details>", ""]

(ROOT / "bench" / "model-comparison.md").write_text("\n".join(out), encoding="utf-8")
print("wrote bench/model-comparison.md")
