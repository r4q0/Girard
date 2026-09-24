# /// script
# requires-python = ">=3.11"
# dependencies = ["openai>=1.40", "python-dotenv"]
# ///
"""Time style E (one point, <=15 words) on the fastest good models. 10 lines x 3 rounds each."""
import json, os, re, statistics, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
sys.argv = sys.argv[:1]
client = OpenAI(base_url="https://api.tokenfactory.nebius.com/v1", api_key=os.environ["NEBIUS_API_KEY"], timeout=60)
src = (Path(__file__).parent / "examples.py").read_text(encoding="utf-8")
ns = {"__file__": str(Path(__file__).parent / "examples.py")}
exec(src.split("jobs = [")[0], ns)  # reuse STYLES, CALL, system() without running the generation
MODELS = {
    "zai-org/GLM-5.2": {"reasoning_effort": "none"},
    "openai/gpt-oss-120b": {"reasoning_effort": "low"},
    "moonshotai/Kimi-K2.6": {"extra_body": {"chat_template_kwargs": {"thinking": False}}},
    "NousResearch/Hermes-4-405B": {},
    "google/gemma-3-27b-it": {},
    "Qwen/Qwen3-30B-A3B-Instruct-2507": {},
}
SYS = ns["system"](ns["STYLES"]["E"][1])
CALL = ns["CALL"]
def one(model, i):
    user = "RECENT PROSPECT LINES:\n" + "\n".join(f"- {l}" for l in CALL[max(0, i - 6):i]) + f"\n\nNEW: {CALL[i]}"
    t = time.perf_counter(); first = None; out = []
    for ch in client.chat.completions.create(model=model, temperature=0, max_tokens=300, stream=True,
            messages=[{"role": "system", "content": SYS}, {"role": "user", "content": user}], **MODELS[model]):
        if ch.choices and ch.choices[0].delta.content:
            first = first or time.perf_counter() - t
            out.append(ch.choices[0].delta.content)
    return first, time.perf_counter() - t, "".join(out)
def bench(model):
    one(model, 0)  # warm
    runs = [one(model, i) for _ in range(3) for i in range(len(CALL))]
    firsts = [r[0] for r in runs]; totals = [r[1] for r in runs]
    return model, statistics.median(firsts), statistics.median(totals), sorted(totals)[int(len(totals) * 0.9)], runs[:len(CALL)]
with ThreadPoolExecutor(6) as p:
    res = list(p.map(bench, MODELS))
res.sort(key=lambda r: r[2])
print("| Model | First word (ms, median) | Full advice (ms, median) | Full advice (ms, slowest 10%) |")
print("| --- | --- | --- | --- |")
for m, f, t, p90, _ in res:
    print(f"| {m} | {f*1000:.0f} | {t*1000:.0f} | {p90*1000:.0f} |")
json.dump({m: [json.loads(re.search(r"\{.*\}", r[2], re.S).group(0))["bullets"] if re.search(r"\{.*\}", r[2], re.S) else r[2] for r in runs] for m, *_, runs in res}, open(ROOT / "bench/advice/speed_e.json", "w", encoding="utf-8"), indent=1)
