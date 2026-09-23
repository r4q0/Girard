"""
Tests whether Nebius Token Factory silently reuses the KV cache for
identical prompt prefixes, and how much faster cache hits are.

The verdict is based on the `cached_tokens` usage field (direct evidence).
Timing is reported separately, with enough runs and robust statistics
(median, IQR, trimmed mean) to survive server queue spikes.

Usage:
    pip install openai
    export NEBIUS_API_KEY=...
    python cache_test.py [runs_per_group]
"""
import csv
import os
import random
import statistics
import sys
import time
import uuid
from openai import OpenAI

MODEL = "Qwen/Qwen3-30B-A3B-Instruct-2507"
RUNS = int(sys.argv[1]) if len(sys.argv) > 1 else 25
PAUSE_S = 0.3  # small gap between calls so we don't measure our own burst
OUT_CSV = "cache_test_results.csv"

client = OpenAI(
    base_url="https://api.tokenfactory.nebius.com/v1",
    api_key=os.environ["NEBIUS_API_KEY"],
)

entry = (
    "[obj_price_{i}] OBJECTION: too expensive\n"
    "Triggers: too expensive, over budget, cheaper elsewhere\n"
    "Concern: does not see ROI yet\n"
    "Say: Ask what the manual process costs per month. Compare to price.\n"
    "Proof: Client X saved 40 hours a month, paid back in 5 months.\n\n"
)
PLAYBOOK = "".join(entry.format(i=i) for i in range(70))
STATIC = "You help a sales rep respond live to a customer.\n\nPLAYBOOK\n" + PLAYBOOK
USER = 'RECENT:\nCUSTOMER: That sounds expensive.   <- NEW\nReply with {"id":null}.'


def run(system_prompt):
    start = time.perf_counter()
    ttft = None
    usage = None
    stream = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": USER},
        ],
        max_tokens=10,
        temperature=0,
        stream=True,
        stream_options={"include_usage": True},
    )
    for chunk in stream:
        if ttft is None and chunk.choices and chunk.choices[0].delta.content:
            ttft = time.perf_counter() - start
        if chunk.usage:
            usage = chunk.usage
    total = time.perf_counter() - start
    if ttft is None:
        ttft = total
    cached = 0
    prompt_tokens = None
    if usage is not None:
        prompt_tokens = usage.prompt_tokens
        details = getattr(usage, "prompt_tokens_details", None)
        cached = (getattr(details, "cached_tokens", None) if details else None) or 0
    return {"ttft_ms": ttft * 1000, "total_ms": total * 1000,
            "prompt_tokens": prompt_tokens, "cached_tokens": cached}


def stats(values):
    if not values:
        return "n=0"
    v = sorted(values)
    n = len(v)
    q = statistics.quantiles(v, n=4) if n >= 4 else [v[0], statistics.median(v), v[-1]]
    k = int(n * 0.1)
    trimmed = v[k:n - k] if n - 2 * k > 0 else v
    return (f"n={n:3d}  median {statistics.median(v):6.0f}  "
            f"p25 {q[0]:6.0f}  p75 {q[2]:6.0f}  "
            f"trim-mean {statistics.mean(trimmed):6.0f}  min {v[0]:6.0f}  max {v[-1]:6.0f}  (ms)")


rows = []


def record(group, i, r):
    r = {"group": group, "i": i, **r}
    rows.append(r)
    hit = r["cached_tokens"] / r["prompt_tokens"] if r["prompt_tokens"] else 0
    print(f"{group:7s} #{i:2d}: TTFT {r['ttft_ms']:6.0f} ms | prompt {r['prompt_tokens']} "
          f"| cached {r['cached_tokens']:5d} ({hit:4.0%})", flush=True)


print(f"Model {MODEL}, {RUNS} runs per group\n")
print("Warming up the shared prefix (not counted)...")
for _ in range(3):
    run(STATIC)
    time.sleep(PAUSE_S)

# Interleave the two groups in random order so drift / queue spikes hit both equally
print("\nPhase 1: identical prefix vs unique prefix, interleaved")
for i in range(1, RUNS + 1):
    order = ["same", "unique"]
    random.shuffle(order)
    for g in order:
        prompt = STATIC if g == "same" else f"Session {uuid.uuid4()}\n" + STATIC
        record(g, i, run(prompt))
        time.sleep(PAUSE_S)

# How quickly does a brand-new prefix start hitting the cache? (routing across replicas)
print("\nPhase 2: new prefix, repeated, to see how fast it starts hitting")
fresh = f"Session {uuid.uuid4()}\n" + STATIC
for i in range(1, 11):
    record("fresh", i, run(fresh))
    time.sleep(PAUSE_S)

with open(OUT_CSV, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

same = [r for r in rows if r["group"] == "same"]
unique = [r for r in rows if r["group"] == "unique"]
fresh_rows = [r for r in rows if r["group"] == "fresh"]
hits = [r for r in rows if r["prompt_tokens"] and r["cached_tokens"] >= 0.5 * r["prompt_tokens"]]
misses = [r for r in rows if r not in hits]

print("\n=== CACHE HITS (from usage.cached_tokens) ===")
same_hits = sum(1 for r in same if r in hits)
unique_hits = sum(1 for r in unique if r in hits)
print(f"Same prefix:   {same_hits}/{len(same)} calls hit the cache ({same_hits/len(same):.0%})")
print(f"Unique prefix: {unique_hits}/{len(unique)} calls hit the cache ({unique_hits/len(unique):.0%})")
first_hit = next((r["i"] for r in fresh_rows if r in hits), None)
fresh_hits = sum(1 for r in fresh_rows if r in hits)
print(f"Fresh prefix:  first hit on call #{first_hit}, {fresh_hits}/{len(fresh_rows)} hits overall")

print("\n=== TTFT ===")
print(f"Same prefix    {stats([r['ttft_ms'] for r in same])}")
print(f"Unique prefix  {stats([r['ttft_ms'] for r in unique])}")
print(f"All cache hits {stats([r['ttft_ms'] for r in hits])}")
print(f"All misses     {stats([r['ttft_ms'] for r in misses])}")

print("\n=== VERDICT ===")
if same and same_hits / len(same) >= 0.5 and unique_hits == 0:
    print("Prefix caching is ON: identical prefixes are reused automatically.")
elif same_hits == 0:
    print("No prefix caching observed: every call recomputes the full prompt.")
else:
    print("Mixed result: caching seen but inconsistent; inspect the CSV.")
if hits and misses:
    d = statistics.median(r["ttft_ms"] for r in misses) - statistics.median(r["ttft_ms"] for r in hits)
    print(f"Median TTFT saving on a cache hit: {d:.0f} ms")
print(f"\nRaw data written to {OUT_CSV}")
