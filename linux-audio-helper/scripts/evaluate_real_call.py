#!/usr/bin/env python3
"""Compare experimental compressors on the same finalized local call transcript.

Input: {corpus_id, provenance, recordings:[{recording_id, ..., segments:[
{session_id, segment_id, start_ms, end_ms, text, is_final:true}]}]}.
Audio paths and provenance are descriptive only: this script never opens audio,
captures a device, sends transcript data, or downloads a tokenizer vocabulary.

Example (tokenizer vocabularies must already be cached):
  .venv/bin/python scripts/evaluate_real_call.py INPUT.json --output-dir NEW_DIR \
    --tokenizers cl100k_base o200k_base --markdown

Output includes aggregate JSON, complete JSON/CSV segment audits, per-session
CSV comparisons, and optional Markdown. Output contains source text; a new
private directory is required and existing output directories are not reused.
"""

from __future__ import annotations

import argparse
import csv
import html
import importlib.metadata
import json
import math
import os
import platform
import re
import statistics
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from call_audio.experiments import VARIANTS, compress_variant
from call_audio.compression import RULES_VERSION

PREFIX = (
    "Summarize the customer's goals, objections, constraints, commitments, and next steps "
    "from this call. Preserve exact numbers and uncertainty.\n<transcript>\n"
)
SUFFIX = "\n</transcript>"
ENCODINGS = ("cl100k_base", "o200k_base")
WORD = re.compile(r"\b\w+(?:['’]\w+)*\b", re.UNICODE)
NUMERAL = re.compile(r"\d+(?:[.,:/-]\d+)*(?:%)?")
NEGATIONS = frozenset("no not never neither nor none nobody nothing nowhere cannot without unless except".split())
MODALS = frozenset("can could may might must shall should will would ought need needs".split())
UNCERTAINTY = frozenset("maybe probably possibly perhaps approximately around about likely roughly think believe guess".split())
PERSON = frozenset("i me my mine we us our ours you your yours they them their theirs he him his she her hers".split())
CONDITIONS = frozenset("if unless until provided assuming only except without before after while because".split())
NUMBER_WORDS = frozenset((
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy "
    "eighty ninety hundred thousand million billion trillion dozen"
).split())


def full_prompt(text: str) -> str:
    return PREFIX + text + SUFFIX


def validate_corpus(corpus: dict) -> list[dict]:
    """Validate finals and flatten them without consulting descriptive audio paths."""
    if not isinstance(corpus, dict) or not isinstance(corpus.get("corpus_id"), str) or not corpus["corpus_id"]:
        raise ValueError("Input needs a nonempty corpus_id string.")
    if not isinstance(corpus.get("provenance"), dict):
        raise ValueError("Input needs a provenance object describing the recording source.")
    recordings = corpus.get("recordings")
    if not isinstance(recordings, list) or not recordings:
        raise ValueError("Input needs a nonempty recordings list.")
    rows, recording_ids = [], set()
    for recording in recordings:
        if not isinstance(recording, dict):
            raise ValueError("Each recording must be an object.")
        recording_id = recording.get("recording_id")
        if not isinstance(recording_id, str) or not recording_id or recording_id in recording_ids:
            raise ValueError("Each recording needs a unique, nonempty recording_id string.")
        recording_ids.add(recording_id)
        segments = recording.get("segments")
        if not isinstance(segments, list) or not segments:
            raise ValueError(f"Recording {recording_id} has no finalized segments.")
        identities = set()
        validated = []
        for segment in segments:
            if not isinstance(segment, dict) or segment.get("is_final") is not True:
                raise ValueError(f"Recording {recording_id} contains a non-final or invalid segment; supply finalized raw STT only.")
            for key in ("session_id", "segment_id"):
                if not isinstance(segment.get(key), str) or not segment[key]:
                    raise ValueError(f"Recording {recording_id}: {key} must be a nonempty string.")
            identity = (segment["session_id"], segment["segment_id"])
            if identity in identities:
                raise ValueError(f"Recording {recording_id} contains a duplicate finalized segment identity.")
            identities.add(identity)
            if not isinstance(segment.get("text"), str):
                raise ValueError(f"Recording {recording_id} contains a segment without raw text.")
            for key in ("start_ms", "end_ms"):
                value = segment.get(key)
                if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                    raise ValueError(f"Recording {recording_id}: {key} must be a finite nonnegative number.")
            if segment["end_ms"] < segment["start_ms"]:
                raise ValueError(f"Recording {recording_id} contains reversed segment timestamps.")
            validated.append({**segment, "recording_id": recording_id})
        # Stable timestamp ordering preserves source order for simultaneous text.
        validated.sort(key=lambda row: (row["start_ms"], row["end_ms"]))
        rows.extend(validated)
    return rows


def cached_counters(names: list[str]) -> dict:
    """Reuse the project's ordinary-text counter, refusing all cache-miss reads."""
    if any(name not in ENCODINGS for name in names):
        raise ValueError("Only cl100k_base and o200k_base reference encodings are supported.")
    if not names:
        return {}
    try:
        import tiktoken.load  # Import has no vocabulary download side effect.
        from call_audio.tokens import load_token_counter
        # tiktoken calls read_file only after its hash-checked local cache misses.
        # Blocking that function prevents both remote and alternate-file fetches;
        # it does not alter a running service or persist any configuration.
        with patch("tiktoken.load.read_file", side_effect=RuntimeError("Offline evaluation: tokenizer vocabulary is not cached.")):
            return {name: load_token_counter(name) for name in dict.fromkeys(names)}
    except (ImportError, RuntimeError) as exc:
        raise RuntimeError("Reference counting requires the optional tokens dependency and already-cached vocabularies; evaluation did not download them.") from exc


def lexical_counts(text: str) -> dict:
    return {"words": len(WORD.findall(text)), "characters": len(text)}


def _signals(text: str, protected_terms=()) -> dict[str, Counter]:
    words = [word.casefold().replace("’", "'") for word in WORD.findall(text)]
    return {
        "numerals": Counter(NUMERAL.findall(text)),
        "number_words": Counter(word for word in words if word in NUMBER_WORDS),
        "negation": Counter(word for word in words if word in NEGATIONS or word.endswith("n't")),
        "modality": Counter(word for word in words if word in MODALS),
        "uncertainty": Counter(word for word in words if word in UNCERTAINTY),
        "person_references": Counter(word for word in words if word in PERSON),
        "conditions_or_time": Counter(word for word in words if word in CONDITIONS),
        "protected_terms": Counter({term: len(re.findall(re.escape(term), text, flags=re.IGNORECASE))
                                     for term in protected_terms}),
    }


def protection_flags(raw: str, compact: str, protected_terms=()) -> dict:
    """Lexical count differences flag review; they do not prove semantic loss/safety."""
    before, after = _signals(raw, protected_terms), _signals(compact, protected_terms)
    flags = {}
    for category in before:
        removed, added = before[category] - after[category], after[category] - before[category]
        if removed or added:
            flags[category] = {"removed": dict(removed), "added": dict(added)}
    return flags


def validate_result(raw: str, variant: str, result: dict) -> None:
    if not isinstance(result, dict) or not isinstance(result.get("compact_text"), str):
        raise ValueError(f"Variant {variant} returned an invalid result.")
    if not isinstance(result.get("rules"), list) or not isinstance(result.get("risk"), str):
        raise ValueError(f"Variant {variant} did not supply rules and risk metadata.")
    cursor, pieces = 0, []
    for span in result["removed_spans"]:
        start, end = span["start"], span["end"]
        if type(start) is not int or type(end) is not int or not 0 <= cursor <= start <= end <= len(raw):
            raise ValueError(f"Variant {variant} returned overlapping or invalid original-text spans.")
        if raw[start:end] != span["text"] or not isinstance(span["replacement"], str) or not span["rule_id"]:
            raise ValueError(f"Variant {variant} returned an incorrect audit span.")
        pieces.extend((raw[cursor:start], span["replacement"]))
        cursor = end
    pieces.append(raw[cursor:])
    if "".join(pieces) != result["compact_text"]:
        raise ValueError(f"Variant {variant} made a change not accounted for by its original-text spans.")
    if variant == "raw" and result["compact_text"] != raw:
        raise ValueError("The raw control must preserve the source text exactly.")


def _count(counter, text: str) -> int:
    value = counter(text)
    if type(value) is not int or value < 0:
        raise ValueError("A reference token counter returned an invalid count.")
    return value


def positive_guard(raw: str, candidate: str, counter) -> dict:
    """The optional deployed-style guard counts standalone segments, not prompts."""
    raw_tokens = _count(counter, raw)
    candidate_tokens = _count(counter, candidate) if candidate != raw else raw_tokens
    accepted = candidate != raw and candidate_tokens < raw_tokens
    selected = candidate if accepted else raw
    return {
        "compact_text": selected, "accepted_edit": accepted,
        "rejected_edit": candidate != raw and not accepted,
        "raw_tokens": raw_tokens, "candidate_tokens": candidate_tokens,
        "selected_tokens": candidate_tokens if accepted else raw_tokens,
        "saved": raw_tokens - (candidate_tokens if accepted else raw_tokens),
    }


def _percentiles(samples_ns: list[int]) -> dict:
    if not samples_ns:
        return {"samples": 0, "p50_ms": None, "p95_ms": None, "p99_ms": None, "max_ms": None}
    ordered = sorted(samples_ns)
    def at(fraction):
        position = fraction * (len(ordered) - 1)
        low = int(position)
        high = min(low + 1, len(ordered) - 1)
        return round((ordered[low] + (ordered[high] - ordered[low]) * (position - low)) / 1e6, 6)
    return {"samples": len(ordered), "p50_ms": round(statistics.median(ordered) / 1e6, 6),
            "p95_ms": at(.95), "p99_ms": at(.99), "max_ms": round(max(ordered) / 1e6, 6)}


def _measure(operation, iterations: int, warmup: int) -> dict:
    for _ in range(warmup):
        operation()
    wall, cpu = [], []
    for _ in range(iterations):
        cpu_started = time.process_time_ns()
        wall_started = time.perf_counter_ns()
        operation()
        wall.append(time.perf_counter_ns() - wall_started)
        cpu.append(time.process_time_ns() - cpu_started)
    return {"wall": wall, "cpu": cpu}


def _timing_report(samples: dict) -> dict:
    return {"wall_clock": _percentiles(samples["wall"]), "process_cpu": _percentiles(samples["cpu"])}


def _extend_timing(target: dict, addition: dict) -> None:
    target["wall"].extend(addition["wall"])
    target["cpu"].extend(addition["cpu"])


def _change_counts(raw: int, compact: int) -> dict:
    return {"raw": raw, "compact": compact, "saved": raw - compact,
            "saved_percent": round(100 * (raw - compact) / raw, 4) if raw else 0.0}


def _flag_totals(flags: list[dict]) -> dict:
    categories = Counter(category for entry in flags for category in entry)
    return {"flagged_segments": sum(bool(entry) for entry in flags), "segments_by_category": dict(categories)}


def _package_version(name: str):
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def evaluate(corpus: dict, *, counters=None, iterations=200, warmup=20, protected_terms=()) -> dict:
    """Evaluate only supplied finalized text. No output is written by this function."""
    if type(iterations) is not int or iterations < 200:
        raise ValueError("Use at least 200 measured repetitions per segment and variant.")
    if type(warmup) is not int or warmup < 1:
        raise ValueError("Use at least one excluded warmup repetition.")
    terms = tuple(protected_terms)
    if len(terms) > 64 or any(not isinstance(term, str) or not term.strip() or len(term) > 128 for term in terms):
        raise ValueError("Supply at most 64 nonempty protected terms, at most 128 characters each.")
    counters = dict(counters or {})
    source_segments = validate_corpus(corpus)
    timings = defaultdict(lambda: {"wall": [], "cpu": []})
    audits = []
    for segment in source_segments:
        raw = segment["text"]
        audit = {
            "recording_id": segment["recording_id"], "session_id": segment["session_id"],
            "segment_id": segment["segment_id"], "start_ms": segment["start_ms"], "end_ms": segment["end_ms"],
            "raw_text": raw, "raw_counts": lexical_counts(raw), "variants": {},
        }
        for variant in VARIANTS:
            result = compress_variant(raw, variant, protected_terms=terms)
            validate_result(raw, variant, result)
            if result != compress_variant(raw, variant, protected_terms=terms):
                raise ValueError(f"Variant {variant} was not deterministic on a supplied segment.")
            compact = result["compact_text"]
            samples = _measure(lambda: compress_variant(raw, variant, protected_terms=terms), iterations, warmup)
            _extend_timing(timings[(variant, "compression", None)], samples)
            variant_audit = {
                **result, "counts": lexical_counts(compact), "changed": compact != raw,
                "automatic_flags": protection_flags(raw, compact, terms),
                "compression_timing": _timing_report(samples), "reference_tokens": {},
            }
            for encoding, counter in counters.items():
                guarded = positive_guard(raw, compact, counter)
                guard_samples = _measure(lambda: positive_guard(raw, compact, counter), iterations, warmup)
                def compress_and_guard():
                    candidate = compress_variant(raw, variant, protected_terms=terms)["compact_text"]
                    return positive_guard(raw, candidate, counter)
                total_samples = _measure(compress_and_guard, iterations, warmup)
                _extend_timing(timings[(variant, "guard_only", encoding)], guard_samples)
                _extend_timing(timings[(variant, "compression_plus_guard", encoding)], total_samples)
                variant_audit["reference_tokens"][encoding] = {
                    "unguarded_standalone": _change_counts(guarded["raw_tokens"], guarded["candidate_tokens"]),
                    "unguarded_separately_wrapped_prompt": _change_counts(_count(counter, full_prompt(raw)), _count(counter, full_prompt(compact))),
                    "standalone_positive_guard": {
                        **guarded, "counts": lexical_counts(guarded["compact_text"]),
                        "separately_wrapped_prompt": _change_counts(_count(counter, full_prompt(raw)), _count(counter, full_prompt(guarded["compact_text"]))),
                        "automatic_flags": protection_flags(raw, guarded["compact_text"], terms),
                        "guard_only_timing": _timing_report(guard_samples),
                        "compression_plus_guard_timing": _timing_report(total_samples),
                    },
                }
            audit["variants"][variant] = variant_audit
        audits.append(audit)

    groups = defaultdict(list)
    for audit in audits:
        groups[(audit["recording_id"], audit["session_id"])].append(audit)
    sessions = []
    for (recording_id, session_id), segments in groups.items():
        raw_joined = "\n".join(segment["raw_text"] for segment in segments)
        session = {"recording_id": recording_id, "session_id": session_id, "segment_count": len(segments),
                   "start_ms": min(segment["start_ms"] for segment in segments),
                   "end_ms": max(segment["end_ms"] for segment in segments), "variants": {}}
        for variant in VARIANTS:
            rows = [segment["variants"][variant] for segment in segments]
            compact_joined = "\n".join(row["compact_text"] for row in rows)
            item = {
                "words": _change_counts(sum(segment["raw_counts"]["words"] for segment in segments), sum(row["counts"]["words"] for row in rows)),
                "characters": _change_counts(sum(segment["raw_counts"]["characters"] for segment in segments), sum(row["counts"]["characters"] for row in rows)),
                "changed_segments": sum(row["changed"] for row in rows),
                "automatic_flags": _flag_totals([row["automatic_flags"] for row in rows]),
                "reference_tokens": {},
            }
            for encoding, counter in counters.items():
                tokens = [row["reference_tokens"][encoding] for row in rows]
                guarded = [token["standalone_positive_guard"] for token in tokens]
                guarded_joined = "\n".join(entry["compact_text"] for entry in guarded)
                raw_full = _count(counter, full_prompt(raw_joined))
                compact_full = _count(counter, full_prompt(compact_joined))
                guarded_full = _count(counter, full_prompt(guarded_joined))
                raw_standalone = sum(token["unguarded_standalone"]["raw"] for token in tokens)
                compact_standalone = sum(token["unguarded_standalone"]["compact"] for token in tokens)
                item["reference_tokens"][encoding] = {
                    "unguarded": {
                        "standalone_segments_sum": _change_counts(raw_standalone, compact_standalone),
                        "separately_wrapped_segment_prompts_sum": _change_counts(
                            sum(token["unguarded_separately_wrapped_prompt"]["raw"] for token in tokens),
                            sum(token["unguarded_separately_wrapped_prompt"]["compact"] for token in tokens)),
                        "complete_session_prompt": _change_counts(raw_full, compact_full),
                        "raw_prompt_minus_standalone_sum": raw_full - raw_standalone,
                        "compact_prompt_minus_standalone_sum": compact_full - compact_standalone,
                    },
                    "standalone_positive_guard": {
                        "standalone_segments_sum": _change_counts(raw_standalone, sum(entry["selected_tokens"] for entry in guarded)),
                        "separately_wrapped_segment_prompts_sum": _change_counts(
                            sum(entry["separately_wrapped_prompt"]["raw"] for entry in guarded),
                            sum(entry["separately_wrapped_prompt"]["compact"] for entry in guarded)),
                        "complete_session_prompt": _change_counts(raw_full, guarded_full),
                        "complete_prompt_increased": guarded_full > raw_full,
                        "accepted_edits": sum(entry["accepted_edit"] for entry in guarded),
                        "rejected_edits": sum(entry["rejected_edit"] for entry in guarded),
                        "words": _change_counts(item["words"]["raw"], sum(entry["counts"]["words"] for entry in guarded)),
                        "characters": _change_counts(item["characters"]["raw"], sum(entry["counts"]["characters"] for entry in guarded)),
                        "automatic_flags": _flag_totals([entry["automatic_flags"] for entry in guarded]),
                    },
                }
            session["variants"][variant] = item
        sessions.append(session)

    variants = {}
    for variant in VARIANTS:
        rows = [audit["variants"][variant] for audit in audits]
        totals = {
            "words": _change_counts(sum(audit["raw_counts"]["words"] for audit in audits), sum(row["counts"]["words"] for row in rows)),
            "characters": _change_counts(sum(audit["raw_counts"]["characters"] for audit in audits), sum(row["counts"]["characters"] for row in rows)),
            "changed_segments": sum(row["changed"] for row in rows),
            "unchanged_segments": sum(not row["changed"] for row in rows),
            "automatic_flags": _flag_totals([row["automatic_flags"] for row in rows]),
            "rules_applied_to_segments": dict(Counter(rule for row in rows for rule in row["rules"])),
            "risk_descriptions": sorted({row["risk"] for row in rows}),
            "compression_timing": _timing_report(timings[(variant, "compression", None)]),
            "reference_tokens": {},
        }
        for encoding in counters:
            per_session = [session["variants"][variant]["reference_tokens"][encoding] for session in sessions]
            token_totals = {}
            for mode in ("unguarded", "standalone_positive_guard"):
                token_totals[mode] = {}
                for scope in ("standalone_segments_sum", "separately_wrapped_segment_prompts_sum", "complete_session_prompt"):
                    token_totals[mode][scope] = _change_counts(
                        sum(row[mode][scope]["raw"] for row in per_session),
                        sum(row[mode][scope]["compact"] for row in per_session),
                    )
            token_totals["standalone_positive_guard"].update({
                "accepted_edits": sum(row["standalone_positive_guard"]["accepted_edits"] for row in per_session),
                "rejected_edits": sum(row["standalone_positive_guard"]["rejected_edits"] for row in per_session),
                "sessions_with_complete_prompt_increase": sum(row["standalone_positive_guard"]["complete_prompt_increased"] for row in per_session),
                "automatic_flags": _flag_totals([row["reference_tokens"][encoding]["standalone_positive_guard"]["automatic_flags"] for row in rows]),
                "guard_only_timing": _timing_report(timings[(variant, "guard_only", encoding)]),
                "compression_plus_guard_timing": _timing_report(timings[(variant, "compression_plus_guard", encoding)]),
            })
            totals["reference_tokens"][encoding] = token_totals
        variants[variant] = totals

    return {
        "summary": {
            "schema_version": 1, "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "corpus_metadata": {key: value for key, value in corpus.items() if key != "recordings"},
            "recordings_metadata": [{key: value for key, value in recording.items() if key != "segments"}
                                    for recording in corpus["recordings"]],
            "recording_count": len(corpus["recordings"]), "session_count": len(sessions), "segment_count": len(audits),
            "variants": variants, "sessions": sessions,
            "method": {
                "production_minimal_rules_version": RULES_VERSION,
                "iterations_per_segment_variant_mode": iterations, "excluded_warmup_repetitions": warmup,
                "reference_encodings": list(counters), "production_downstream_model_selected": False,
                "prompt_prefix": PREFIX, "prompt_suffix": SUFFIX, "joiner": "\\n",
                "protected_terms": list(terms), "word_count": "Unicode lexical regex; not model tokens.",
                "tokenization": "Ordinary literal text; standalone sums, sums of separately wrapped segment prompts, and complete joined-session prompt counts are measured separately.",
                "guard": "Optional standalone positive-savings guard, separately evaluated from unguarded deployed minimal. Complete guarded prompts are re-counted; positive per-segment savings do not certify full-request savings.",
                "timings": "Warm local compression, guard-only, and combined operations. Wall-clock and process-CPU times include timer/adapter overhead; exclude imports, tokenizer loading, input/output, STT, and prompt assembly. Every final segment is repeated equally. Raw is a measured adapter control; a deployed raw-only path need not call a compressor.",
                "automatic_flags": "Lexical count differences for numerals, number words, negation, modality, uncertainty, person references, conditions/time, and configured phrases. A flag is not proof of harm; absence of flags is not proof of semantic preservation. Review the actual side-by-side text.",
                "source_verification": "Supplied provenance is retained, not independently verified by this script. No audio file or descriptive audio_path is opened.",
                "csv_export": "String cells beginning with spreadsheet formula/control prefixes (including after leading spaces) receive an apostrophe prefix. Exact source/compact text remains in audit.json.",
                "network_calls": False, "live_capture": False, "hosted_inference": False,
            },
            "environment": {"python": platform.python_version(), "platform": platform.platform(),
                            "package_versions": {"tiktoken": _package_version("tiktoken"), "call-audio-helper": _package_version("call-audio-helper")}},
            "limitations": [
                "Results apply to these supplied finalized STT segments, including recognizer omissions/errors; not directly to every spoken word in the original recording.",
                "The same finalized corpus is used for every variant; no provisional revisions, synthetic replacement dialogue, or repeated event delivery are counted.",
                "Reference-token savings are not production billing estimates; model choice, message framing, cached-input billing, and actual downstream prompts are not specified.",
                "These experiments do not change the running service or enable stronger variants in production.",
            ],
        },
        "segments": audits,
    }


def _markdown_cell(text) -> str:
    escaped = html.escape(str(text), quote=False).replace("\\", "\\\\")
    for character in ("|", "`", "*", "_", "[", "]"):
        escaped = escaped.replace(character, "\\" + character)
    return escaped.replace("\r", "").replace("\n", "<br>")


def render_markdown(evaluation: dict) -> str:
    summary = evaluation["summary"]
    lines = ["# Local call-transcript variant audit", "",
             f"Corpus: {_markdown_cell(summary['corpus_metadata']['corpus_id'])}", "",
             "All variants use the same finalized raw STT. These text-only checks do not establish semantic equivalence or verify the recording's provenance.", "",
             "| Variant | Changed segments | Words saved | Characters saved | Automatic review flags | Warm compression p95 (ms) |",
             "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for variant, result in summary["variants"].items():
        lines.append(f"| {_markdown_cell(variant)} | {result['changed_segments']} | {result['words']['saved']} | {result['characters']['saved']} | {result['automatic_flags']['flagged_segments']} | {result['compression_timing']['wall_clock']['p95_ms']} |")
    lines.extend(["", "Reference counts use the exact fixed wrapper recorded in summary.json; no transcript was uploaded. Guarded and unguarded results are separate in the machine-readable reports.", ""])
    for segment in evaluation["segments"]:
        identity = f"{segment['recording_id']} / {segment['session_id']} / {segment['segment_id']}"
        lines.extend([f"## {_markdown_cell(identity)}", "", f"Audio-relative interval: {segment['start_ms']}–{segment['end_ms']} ms.", "",
                      "| Variant | Text | Applied rules | Automatic review flags |", "| --- | --- | --- | --- |"])
        for variant, result in segment["variants"].items():
            lines.append("| " + " | ".join(_markdown_cell(value) for value in (
                variant, result["compact_text"], ", ".join(result["rules"]), json.dumps(result["automatic_flags"], ensure_ascii=False)
            )) + " |")
        lines.append("")
    return "\n".join(lines) + "\n"


def _private_file(path: Path):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    return os.fdopen(descriptor, "w", encoding="utf-8", newline="")


def csv_safe(value):
    """Make spreadsheet-bound string cells inert; JSON remains the exact audit."""
    if isinstance(value, str) and value:
        trimmed = value.lstrip(" ")
        if trimmed and trimmed[0] in "=+-@\t\r\n":
            return "'" + value
    return value


def write_outputs(evaluation: dict, output_dir: Path, *, markdown=False) -> dict:
    """Write only new private outputs; never overwrite an existing evaluation."""
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    paths = {"summary": output_dir / "summary.json", "audit": output_dir / "audit.json",
             "segments_csv": output_dir / "segment-audit.csv", "sessions_csv": output_dir / "session-summary.csv"}
    with _private_file(paths["summary"]) as handle:
        json.dump(evaluation["summary"], handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    with _private_file(paths["audit"]) as handle:
        json.dump({"corpus_metadata": evaluation["summary"]["corpus_metadata"], "segments": evaluation["segments"]}, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    with _private_file(paths["segments_csv"]) as handle:
        fields = ["recording_id", "session_id", "segment_id", "start_ms", "end_ms", "variant", "raw_text", "compact_text",
                  "raw_words", "compact_words", "raw_characters", "compact_characters", "rules", "risk", "removed_spans", "automatic_flags", "reference_tokens"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for segment in evaluation["segments"]:
            for variant, result in segment["variants"].items():
                row = {key: segment[key] for key in ("recording_id", "session_id", "segment_id", "start_ms", "end_ms", "raw_text")}
                row.update({"variant": variant, "compact_text": result["compact_text"],
                            "raw_words": segment["raw_counts"]["words"], "compact_words": result["counts"]["words"],
                            "raw_characters": segment["raw_counts"]["characters"], "compact_characters": result["counts"]["characters"], "risk": result["risk"]})
                row.update({key: json.dumps(result[key], ensure_ascii=False) for key in ("rules", "removed_spans", "automatic_flags", "reference_tokens")})
                writer.writerow({key: csv_safe(value) for key, value in row.items()})
    with _private_file(paths["sessions_csv"]) as handle:
        fields = ["recording_id", "session_id", "variant", "mode", "encoding", "segments", "raw_words", "compact_words", "raw_characters", "compact_characters",
                  "raw_standalone_tokens", "compact_standalone_tokens", "raw_separately_wrapped_tokens", "compact_separately_wrapped_tokens", "raw_complete_prompt_tokens", "compact_complete_prompt_tokens", "complete_prompt_saved_tokens",
                  "complete_prompt_saved_percent", "accepted_guarded_edits", "rejected_guarded_edits", "flagged_segments"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for session in evaluation["summary"]["sessions"]:
            for variant, result in session["variants"].items():
                base = {"recording_id": session["recording_id"], "session_id": session["session_id"], "variant": variant, "segments": session["segment_count"]}
                encodings = result["reference_tokens"] or {"": None}
                for encoding, tokens in encodings.items():
                    for mode in (("unguarded", "standalone_positive_guard") if tokens else ("unguarded",)):
                        metrics = tokens[mode] if tokens else {}
                        counts = metrics if mode == "standalone_positive_guard" else result
                        row = {**base, "mode": mode, "encoding": encoding,
                               "raw_words": counts["words"]["raw"], "compact_words": counts["words"]["compact"],
                               "raw_characters": counts["characters"]["raw"], "compact_characters": counts["characters"]["compact"],
                               "flagged_segments": counts["automatic_flags"]["flagged_segments"]}
                        if tokens:
                            standalone, complete = metrics["standalone_segments_sum"], metrics["complete_session_prompt"]
                            row.update({"raw_standalone_tokens": standalone["raw"], "compact_standalone_tokens": standalone["compact"],
                                        "raw_separately_wrapped_tokens": metrics["separately_wrapped_segment_prompts_sum"]["raw"],
                                        "compact_separately_wrapped_tokens": metrics["separately_wrapped_segment_prompts_sum"]["compact"],
                                        "raw_complete_prompt_tokens": complete["raw"], "compact_complete_prompt_tokens": complete["compact"],
                                        "complete_prompt_saved_tokens": complete["saved"], "complete_prompt_saved_percent": complete["saved_percent"],
                                        "accepted_guarded_edits": metrics.get("accepted_edits", ""), "rejected_guarded_edits": metrics.get("rejected_edits", "")})
                        writer.writerow({key: csv_safe(value) for key, value in row.items()})
    if markdown:
        paths["markdown"] = output_dir / "audit.md"
        with _private_file(paths["markdown"]) as handle:
            handle.write(render_markdown(evaluation))
    return {key: str(path) for key, path in paths.items()}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tokenizers", nargs="*", choices=ENCODINGS, default=[])
    parser.add_argument("--iterations", type=int, default=200)
    parser.add_argument("--warmup", type=int, default=20)
    parser.add_argument("--protect", action="append", default=[], help="Preserve a configured literal phrase; repeat as needed")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.output_dir.exists():
            raise ValueError("Choose a new output directory; existing evaluations are never overwritten.")
        corpus = json.loads(args.input.read_text(encoding="utf-8"))
        validate_corpus(corpus)
        counters = cached_counters(args.tokenizers)
        evaluation = evaluate(corpus, counters=counters, iterations=args.iterations, warmup=args.warmup, protected_terms=args.protect)
        paths = write_outputs(evaluation, args.output_dir, markdown=args.markdown)
    except (ValueError, RuntimeError, OSError) as exc:
        parser.exit(1, f"Evaluation failed: {exc}\n")
    print(json.dumps({"corpus_id": corpus["corpus_id"], "segments": evaluation["summary"]["segment_count"],
                      "reference_encodings": list(counters), "outputs": paths}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
