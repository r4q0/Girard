"""
Score the fast lane against the labelled test set.

Each case in testset.jsonl has the recent transcript, optional cards_shown and summary,
and the list of acceptable card ids ([null] means no card should be shown).
Prompts are built by server.py, exactly as the portal builds them.

Usage:
    .venv/Scripts/python eval/run_eval.py                 # all cases
    .venv/Scripts/python eval/run_eval.py --only sig      # cases whose id starts with sig
    .venv/Scripts/python eval/run_eval.py --no-schema     # without json_schema enforcement
"""
import argparse
import asyncio
import csv
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
import server  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("--testset", default=str(HERE / "testset.jsonl"))
p.add_argument("--salesbook", default="salesbook_koref.txt")
p.add_argument("--only", default="", help="only run cases whose id starts with this")
p.add_argument("--no-schema", action="store_true")
p.add_argument("--enum", action="store_true", help="schema only allows ids not shown yet")
p.add_argument("--concurrency", type=int, default=4)
args = p.parse_args()

server.S.load_salesbook(args.salesbook)
server.S.settings.update(schema=not args.no_schema, enum=args.enum, hedge=False, timeout_ms=20000)
cases = [json.loads(l) for l in open(args.testset, encoding="utf-8") if l.strip()]
cases = [c for c in cases if c["id"].startswith(args.only)]


def verdict(case, cid, q):
    expect = case["expect"]
    if cid in expect:
        if cid == "comp_unknown" and case.get("expect_q"):
            if not q or case["expect_q"].lower() not in q.lower():
                return "wrong_q"
        return "correct"
    if expect == [None]:
        return "false_card"      # a card where it should stay quiet
    if cid is None:
        return "missed"          # stayed quiet where a card was expected
    return "wrong_card"


async def run_case(case, sem):
    recent = [{"speaker": s, "text": t} for s, t in case["recent"]]
    messages = [{"role": "system", "content": server.S.system_prompt},
                {"role": "user", "content": server.build_user_message(
                    case.get("summary", ""), case.get("cards_shown", []), recent)}]
    async with sem:
        t0 = time.perf_counter()
        try:
            res = await server.fast_lane(messages, exclude=case.get("cards_shown", []))
        except Exception as e:
            return {**case, "got": None, "q": None, "verdict": "error", "verdict_portal": "error",
                "raw": f"{type(e).__name__}: {e}"}
    raw = res.get("text", "")
    try:
        out = json.loads(raw)
        cid, q = out.get("id"), out.get("q")
        v = verdict(case, cid, q)
        if cid and cid not in server.S.entries and cid != "comp_unknown":
            v = "invalid_id"
    except json.JSONDecodeError:
        cid, q, v = None, None, "invalid_json"
    # The portal hides cards already shown; score what the rep would actually see
    shown = None if cid in case.get("cards_shown", []) else cid
    v_portal = verdict(case, shown, q) if v not in ("invalid_json", "invalid_id") else v
    return {**case, "got": cid, "q": q, "verdict": v, "verdict_portal": v_portal, "raw": raw,
            "ttft_ms": res.get("ttft_ms"), "id_ms": res.get("id_ms"),
            "total_ms": res.get("total_ms") or (time.perf_counter() - t0) * 1000}


async def main():
    sem = asyncio.Semaphore(args.concurrency)
    results = await asyncio.gather(*(run_case(c, sem) for c in cases))

    print(f"{'case':9s} {'verdict':12s} {'expected':34s} got")
    for r in results:
        exp = " | ".join("null" if e is None else e for e in r["expect"])
        got = "null" if r["got"] is None else r["got"] + (f" ({r['q']})" if r.get("q") else "")
        mark = "  " if r["verdict"] == "correct" else "X "
        print(f"{r['id']:9s} {mark}{r['verdict']:10s} {exp:34s} {got}")

    counts = Counter(r["verdict"] for r in results)
    n = len(results)
    by_group = defaultdict(lambda: [0, 0])
    for r in results:
        g = r["id"].split("-")[0]
        by_group[g][1] += 1
        by_group[g][0] += r["verdict"] == "correct"

    def pct(vals, q):
        v = sorted(x for x in vals if x is not None)
        return round(v[min(len(v) - 1, round(q / 100 * (len(v) - 1)))]) if v else None

    portal_ok = sum(r.get("verdict_portal") == "correct" for r in results)
    print(f"\nModel accuracy: {counts['correct']}/{n} ({counts['correct'] / n:.0%})")
    print(f"As shown in the portal (repeats hidden): {portal_ok}/{n} ({portal_ok / n:.0%})")
    print("Errors: " + (", ".join(f"{k} {v}" for k, v in counts.items() if k != "correct") or "none"))
    print("By group: " + ", ".join(f"{g} {c}/{t}" for g, (c, t) in sorted(by_group.items())))
    print(f"Card decided: p50 {pct([r.get('id_ms') for r in results], 50)} ms, "
          f"p95 {pct([r.get('id_ms') for r in results], 95)} ms "
          f"(concurrency {args.concurrency}, schema {'off' if args.no_schema else 'on'}"
          f"{', enum' if args.enum else ''})")

    out = HERE / f"results_{time.strftime('%Y%m%d_%H%M%S')}.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "verdict", "expect", "got", "q", "id_ms", "total_ms", "last_line", "raw"])
        for r in results:
            w.writerow([r["id"], r["verdict"], "|".join(str(e) for e in r["expect"]), r["got"], r.get("q"),
                        round(r["id_ms"]) if r.get("id_ms") else "", round(r["total_ms"]) if r.get("total_ms") else "",
                        r["recent"][-1][1], r["raw"]])
    print(f"Saved {out.relative_to(HERE.parent)}")


asyncio.run(main())
