#!/usr/bin/env python3
"""Audit versioned minimal cleanup on synthetic sales text, with warm CPU timings.

No call audio, customer data, hosted model, or paid API is used. The default
needs no tokenizer package. --tokenizer uses an OPTIONAL reference encoding,
not a claim about the as-yet-unselected downstream production model. Install
and cache that encoding first: fetching uncached tiktoken assets is excluded
from all timings. Transcript strings are always encoded as ordinary text.
"""

from __future__ import annotations

import argparse
import datetime
import importlib.metadata
import json
import platform
import statistics
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
PREFIX = "Summarize the customer's needs, constraints, and next steps from this transcript:\n<transcript>\n"
SUFFIX = "\n</transcript>"
NARRATION_V2_EXPECTED = (
    "It was best of times it was worst of times It was age of wisdom "
    "It was age of foolishness It was epoch of belief It was epoch of incredulity "
    "It was a season of light It was a season of darkness It was spring of hope "
    "It was winter of despair We had everything before us we had nothing before us"
)


def prompt(text: str) -> str:
    return PREFIX + text + SUFFIX


def wrapped_counter(encoding):
    """Count the same complete rendered prompt for raw and compact text."""
    def count(text):
        return len(encoding.encode_ordinary(prompt(text)))
    return count


def audit_spans(raw: str, result: dict) -> None:
    spans = result["compression"]["removed_spans"]
    cursor = 0
    pieces = []
    for span in spans:
        assert 0 <= cursor <= span["start"] <= span["end"] <= len(raw)
        assert raw[span["start"]:span["end"]] == span["text"]
        assert span["rule_id"]
        pieces.extend((raw[cursor:span["start"]], span["replacement"]))
        cursor = span["end"]
    pieces.append(raw[cursor:])
    assert "".join(pieces) == result["compact_text"], "An edit was not explained by its original-character audit span."


def audit_case(case: dict, compressor, token_counter=None) -> dict:
    raw = case["text"]
    result = compressor.compress(raw)
    compact = result["compact_text"]
    expected = case["expected_compact"]
    if token_counter and expected != raw and token_counter(expected) >= token_counter(raw):
        expected = raw  # The optional positive-savings guard can reject an approved rule edit.
    assert compact == expected, (
        f"{case['id']}: expected {expected!r}, got {compact!r}; "
        f"reason={result['compression']['reason']}"
    )
    assert result == compressor.compress(raw), "Compression is not deterministic."
    assert compressor.compress(compact)["compact_text"] == compact, "Compression is not idempotent."
    assert bool(result["compression"]["changed"]) == (raw != compact)
    audit_spans(raw, result)
    counted = None
    if token_counter:
        raw_tokens, compact_tokens = token_counter(raw), token_counter(compact)
        assert compact_tokens <= raw_tokens, "The complete prompt grew after cleanup."
        metadata = result["compression"].get("tokens")
        if metadata is not None:
            assert (metadata["raw"], metadata["compact"], metadata["saved"]) == (
                raw_tokens, compact_tokens, raw_tokens - compact_tokens
            )
        # This deliberately shows the cost of forwarding the complete API
        # audit object, instead of selecting one text field for the LLM.
        both = json.dumps({"text": raw, **result}, ensure_ascii=False, separators=(",", ":"))
        counted = {
            "raw_full_prompt": raw_tokens, "compact_full_prompt": compact_tokens,
            "saved": raw_tokens - compact_tokens,
            "api_object_with_both_texts_and_metadata_full_prompt": token_counter(both),
        }
    return {
        "id": case["id"], "category": case["category"], "raw_text": raw,
        "compact_text": compact, "expected_unguarded_compact": case["expected_compact"],
        "protected_terms": case.get("protected_terms", []),
        "compression": result["compression"], "reference_prompt_tokens": counted,
    }


def timing_summary(samples_ns: list[int]) -> dict:
    ordered = sorted(samples_ns)
    def percentile(fraction):
        position = fraction * (len(ordered) - 1)
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        return (ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)) / 1e6
    return {
        "samples": len(ordered), "p50_ms": round(statistics.median(ordered) / 1e6, 6),
        "p95_ms": round(percentile(.95), 6), "p99_ms": round(percentile(.99), 6),
        "max_ms": round(max(ordered) / 1e6, 6),
    }


def time_cases(work, iterations: int) -> dict:
    for compressor, text in work:
        for _ in range(20):
            compressor.compress(text)
    elapsed = []
    for _ in range(iterations):
        for compressor, text in work:
            start = time.perf_counter_ns()
            compressor.compress(text)
            elapsed.append(time.perf_counter_ns() - start)
    return timing_summary(elapsed)


def stress_text(length: int) -> str:
    initial = "We, um, need procurement approval. "
    neutral = "The budget and delivery date remain unchanged. "
    return (initial + neutral * (length // len(neutral) + 1))[:length]


def benchmark(iterations: int = 250, tokenizer: str | None = None) -> dict:
    from call_audio.compression import MinimalCompressor, RULES_VERSION

    encoding = None
    token_counter = None
    label = None
    tokenizer_version = None
    if tokenizer:
        import tiktoken
        encoding = tiktoken.get_encoding(tokenizer)
        token_counter = wrapped_counter(encoding)
        label = f"reference:{tokenizer}:fixed_prompt_v1"
        tokenizer_version = importlib.metadata.version("tiktoken")

    def make(terms=()):
        return MinimalCompressor(protected_terms=terms, token_counter=token_counter, tokenizer_name=label)

    fixture = json.loads((PROJECT / "tests/fixtures/compression_cases.json").read_text(encoding="utf-8"))
    assert fixture["rules_version"] == RULES_VERSION, "The fixture must describe the currently tested rules."
    cases = fixture["cases"]
    work = [(make(case.get("protected_terms", ())), case["text"]) for case in cases]
    audits = [audit_case(case, compressor, token_counter)
              for case, (compressor, _) in zip(cases, work, strict=True)]

    # This is the same historical clean-recognizer narration, not new call data.
    # V2 intentionally changes it through article/punctuation deletion even
    # though it contains no eligible interior fillers. Keep a reviewed literal
    # expectation rather than deriving the expected result from the compressor.
    narration_report = json.loads((PROJECT / "reports/local-benchmark.json").read_text(encoding="utf-8"))
    narration = narration_report["runs"][0]["final_text"]
    narration_audit = audit_case({"id": "clean_local_narration", "category": "clean_recognizer_output",
                                 "text": narration, "expected_compact": NARRATION_V2_EXPECTED}, make(), token_counter)

    stress = []
    for length in (2000, 8192, 8193):
        text = stress_text(length)
        compressor = make()
        result = compressor.compress(text)
        audit_spans(text, result)
        if length > 8192:
            assert result["compact_text"] == text
            assert result["compression"]["reason"] == "limit_exceeded"
        if token_counter:
            assert token_counter(result["compact_text"]) <= token_counter(text)
        stress.append({
            "characters": length, "changed": result["compression"]["changed"],
            "reason": result["compression"]["reason"],
            "timings": time_cases([(compressor, text)], iterations),
            "no_token_counter_timings": time_cases([(MinimalCompressor(), text)], iterations) if token_counter else None,
        })

    summary = None
    if token_counter:
        raw_total = sum(item["reference_prompt_tokens"]["raw_full_prompt"] for item in audits)
        compact_total = sum(item["reference_prompt_tokens"]["compact_full_prompt"] for item in audits)
        raw_joined = "\n".join(item["raw_text"] for item in audits)
        compact_joined = "\n".join(item["compact_text"] for item in audits)
        combined_api = json.dumps({"segments": [{"text": item["raw_text"], "compact_text": item["compact_text"],
                                                 "compression": item["compression"]} for item in audits]},
                                  ensure_ascii=False, separators=(",", ":"))
        assert token_counter(compact_joined) <= token_counter(raw_joined)
        summary = {
            "all_cases_including_unchanged_individual_prompts": {
                "raw": raw_total, "compact": compact_total, "saved": raw_total - compact_total,
                "saved_percent": round(100 * (raw_total - compact_total) / raw_total, 3),
            },
            "same_cases_combined_into_one_prompt": {
                "raw": token_counter(raw_joined), "compact": token_counter(compact_joined),
                "saved": token_counter(raw_joined) - token_counter(compact_joined),
                "api_object_with_both_texts_and_metadata": token_counter(combined_api),
            },
        }
    return {
        "rules_version": RULES_VERSION,
        "evidence": {
            "benchmark_revision": "minimal-v2",
            "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "fixture_rules_version": fixture["rules_version"],
            "historical_report": "reports/compression-benchmark.json is version-1 evidence and is not overwritten.",
            "clean_narration": "Historical recognized narration, not a sales call; v2 can remove articles/punctuation without any filler match.",
        },
        "corpus": "Synthetic sales cases, deliberately mixing eligible fillers, article/punctuation cleanup, and protected counterexamples; not a customer-call distribution.",
        "case_count": len(audits), "changed_cases": sum(item["compression"]["changed"] for item in audits),
        "unchanged_cases": sum(not item["compression"]["changed"] for item in audits),
        "unguarded_expected_changed_cases": sum(item["expected_unguarded_compact"] != item["raw_text"] for item in audits),
        "token_guard_rejected_cases": sum(item["compression"]["reason"] == "no_token_savings" for item in audits),
        "tokenizer": {"encoding": tokenizer, "label": label, "package_version": tokenizer_version,
                      "production_downstream_model_selected": False,
                      "literal_special_strings": "encode_ordinary", "prompt_prefix": PREFIX, "prompt_suffix": SUFFIX,
                      "runtime_comparison": "The optional server --tokenizer setting counts standalone segments. This benchmark injects a counter over the complete fixed prompt shown here. Neither is a production billing estimate."},
        "timing_scope": "Warm local pass including the optional full-prompt token-count guard; excludes imports, tokenizer construction/cache downloads, and initial warmup. Cases are equally weighted.",
        "timings": time_cases(work, iterations),
        "no_token_counter_timings": time_cases([
            (MinimalCompressor(protected_terms=case.get("protected_terms", ())), case["text"])
            for case in cases
        ], iterations) if token_counter else None,
        "stress_cases": stress,
        "reference_token_summary": summary,
        "clean_local_narration": narration_audit,
        "audit": audits,
        "platform": platform.platform(), "python": platform.python_version(),
        "iterations_per_case": iterations,
        "live_audio_used": False, "hosted_inference_used": False,
        "limitations": "Synthetic expected outputs validate only requested mechanical rules and listed counterexamples. Deleting articles or sentence punctuation can lose meaning; preserving all occurrences of for is not a semantic guarantee. This is not proof of semantic equivalence, production token savings, or actual API-price savings. Sending both versions and audit metadata can cost more than raw text alone.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tokenizer", choices=("cl100k_base", "o200k_base"))
    parser.add_argument("--iterations", type=int, default=250)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if not 20 <= args.iterations <= 5000:
        parser.error("iterations must be between 20 and 5000")
    if args.report and args.report.resolve() == (PROJECT / "reports/compression-benchmark.json").resolve():
        parser.error("The historical version-1 report is preserved; use reports/minimal-v2-benchmark.json instead.")
    report = benchmark(args.iterations, args.tokenizer)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key not in {"audit", "clean_local_narration"}}, indent=2))
    print("Clean local narration:", json.dumps(report["clean_local_narration"]["reference_prompt_tokens"]))
    if args.report:
        print(f"Saved full case audit: {args.report}")


if __name__ == "__main__":
    main()
