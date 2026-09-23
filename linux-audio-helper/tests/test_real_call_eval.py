"""Offline evaluator regression fixtures only; never presented as real-call results."""

from __future__ import annotations

import copy
import csv
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/evaluate_real_call.py"
spec = importlib.util.spec_from_file_location("evaluate_real_call", SCRIPT)
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


def segment(text="We, um, need approval.", *, identity="first", session="session", start=0, end=1000):
    return {"session_id": session, "segment_id": identity, "start_ms": start, "end_ms": end,
            "text": text, "is_final": True}


def corpus(*segments):
    return {
        "corpus_id": "unit-test-only-synthetic-regression",
        "provenance": {"recording_type": "synthetic regression fixture; not evaluation data", "source_url": "not-applicable"},
        "recordings": [{"recording_id": "fixture", "channel_label": "fixture-channel",
                        "audio_path": "/this/path/must/never/be/opened.wav", "segments": list(segments or [segment()])}],
    }


@pytest.fixture(scope="module")
def measured_fixture():
    # len is explicitly a fake unit-test counter, not a reference tokenizer or
    # a reported real-call measurement. Production CLI permits named encodings.
    return evaluation.evaluate(corpus(), counters={"unit-test-length-counter": len}, iterations=200, warmup=1)


def test_validates_final_raw_identity_and_orders_without_reading_audio():
    source = corpus(segment("Second.", identity="second", start=2000, end=3000), segment())
    source["recordings"][0]["segments"][1]["compact_text"] = "This is not the raw text."
    original = copy.deepcopy(source)
    rows = evaluation.validate_corpus(source)
    assert [row["segment_id"] for row in rows] == ["first", "second"]
    assert rows[0]["text"] == "We, um, need approval."
    assert source == original


@pytest.mark.parametrize("change", [
    lambda data: data["recordings"][0]["segments"][0].update(is_final=False),
    lambda data: data["recordings"][0]["segments"][0].update(is_final=1),
    lambda data: data["recordings"][0]["segments"][0].update(text=None),
    lambda data: data["recordings"][0]["segments"][0].update(start_ms=float("nan")),
    lambda data: data["recordings"][0]["segments"][0].update(end_ms=-1),
    lambda data: data["recordings"][0]["segments"][0].update(start_ms=True),
    lambda data: data["recordings"][0]["segments"].append(segment()),
    lambda data: data["recordings"].append(copy.deepcopy(data["recordings"][0])),
    lambda data: data.update(recordings=[]),
])
def test_rejects_ambiguous_or_nonfinal_corpus(change):
    data = corpus()
    change(data)
    with pytest.raises(ValueError):
        evaluation.validate_corpus(data)


def test_protection_flags_are_lexical_review_signals():
    raw = "We cannot pay $5,000 before Friday; we might need ten seats."
    compact = "Pay $5000 Friday; need seats."
    flags = evaluation.protection_flags(raw, compact, ("Friday",))
    assert flags["numerals"] == {"removed": {"5,000": 1}, "added": {"5000": 1}}
    assert flags["negation"]["removed"] == {"cannot": 1}
    assert flags["modality"]["removed"] == {"might": 1}
    assert flags["number_words"]["removed"] == {"ten": 1}
    assert flags["person_references"]["removed"] == {"we": 2}
    assert flags["conditions_or_time"]["removed"] == {"before": 1}
    assert "protected_terms" not in flags
    assert evaluation.protection_flags(raw, raw, ("Friday",)) == {}


def test_negation_contractions_and_protected_phrase_changes_are_detected():
    flags = evaluation.protection_flags("We can't use Project Atlas.", "Use Atlas.", ("Project Atlas",))
    assert flags["negation"]["removed"] == {"can't": 1}
    assert flags["protected_terms"]["removed"] == {"Project Atlas": 1}


def test_audit_rejects_unexplained_rewrite():
    result = {"compact_text": "We can commit.", "removed_spans": [], "rules": [], "risk": "fixture"}
    with pytest.raises(ValueError, match="not accounted"):
        evaluation.validate_result("We cannot commit.", "minimal", result)


def test_positive_guard_keeps_raw_for_equal_or_increased_counts():
    assert evaluation.positive_guard("raw", "new", len)["compact_text"] == "raw"
    rejected = evaluation.positive_guard("raw", "longer", len)
    assert rejected["rejected_edit"] and not rejected["accepted_edit"]
    assert rejected["saved"] == 0
    accepted = evaluation.positive_guard("longer", "raw", len)
    assert accepted["accepted_edit"] and accepted["saved"] == 3
    unchanged = evaluation.positive_guard("raw", "raw", len)
    assert not unchanged["rejected_edit"] and not unchanged["accepted_edit"]


def test_invalid_reference_count_is_not_reported_as_measured():
    with pytest.raises(ValueError, match="invalid count"):
        evaluation.positive_guard("raw", "candidate", lambda _: True)


def test_reports_all_variants_and_measured_scopes(measured_fixture):
    report = measured_fixture["summary"]
    assert tuple(report["variants"]) == evaluation.VARIANTS
    assert report["segment_count"] == 1
    assert report["recordings_metadata"][0]["audio_path"] == "/this/path/must/never/be/opened.wav"
    assert not report["method"]["network_calls"]
    assert report["method"]["iterations_per_segment_variant_mode"] == 200
    minimal = report["variants"]["minimal"]
    assert minimal["changed_segments"] == 1
    assert minimal["compression_timing"]["wall_clock"]["samples"] == 200
    assert minimal["compression_timing"]["process_cpu"]["samples"] == 200
    token_data = minimal["reference_tokens"]["unit-test-length-counter"]
    assert token_data["unguarded"]["standalone_segments_sum"]["raw"] == len("We, um, need approval.")
    full = token_data["unguarded"]["complete_session_prompt"]
    assert full["raw"] == len(evaluation.full_prompt("We, um, need approval."))
    assert full["compact"] == len(evaluation.full_prompt("We need approval"))
    assert token_data["unguarded"]["separately_wrapped_segment_prompts_sum"] == full
    guarded = token_data["standalone_positive_guard"]
    assert guarded["accepted_edits"] == 1
    assert guarded["compression_plus_guard_timing"]["wall_clock"]["samples"] == 200
    assert guarded["guard_only_timing"]["wall_clock"]["samples"] == 200


def test_standalone_guard_does_not_claim_complete_prompt_guarantee():
    def context_sensitive_test_counter(text):
        if text.startswith(evaluation.PREFIX):
            return 100 if ", um," in text else 200
        return len(text)
    result = evaluation.evaluate(corpus(), counters={"unit-test-context-counter": context_sensitive_test_counter}, iterations=200, warmup=1)
    guarded = result["summary"]["variants"]["minimal"]["reference_tokens"]["unit-test-context-counter"]["standalone_positive_guard"]
    assert guarded["accepted_edits"] == 1
    assert guarded["sessions_with_complete_prompt_increase"] == 1
    assert guarded["complete_session_prompt"]["saved"] == -100


def test_sessions_and_per_segment_wrappers_are_counted_separately():
    data = corpus(segment("First."), segment("Second.", identity="second", start=2000, end=3000),
                  segment("Third.", identity="third", session="another", start=4000, end=5000))
    result = evaluation.evaluate(data, counters={"unit-test-length-counter": len}, iterations=200, warmup=1)
    report = result["summary"]
    assert report["session_count"] == 2
    counts = report["variants"]["raw"]["reference_tokens"]["unit-test-length-counter"]["unguarded"]
    assert counts["standalone_segments_sum"]["raw"] == len("First.Second.Third.")
    assert counts["complete_session_prompt"]["raw"] == len(evaluation.full_prompt("First.\nSecond.")) + len(evaluation.full_prompt("Third."))
    assert counts["separately_wrapped_segment_prompts_sum"]["raw"] == sum(len(evaluation.full_prompt(text)) for text in ("First.", "Second.", "Third."))


def test_small_iteration_count_is_rejected():
    with pytest.raises(ValueError, match="at least 200"):
        evaluation.evaluate(corpus(), iterations=199)


@pytest.mark.parametrize("value", ["=SUM(1,2)", "+command", "-123", "@formula", "\t=evil", "\r=evil", "\n=evil", "   =evil"])
def test_csv_formula_prefixes_are_inert(value):
    assert evaluation.csv_safe(value) == "'" + value


def test_csv_sanitizer_does_not_change_ordinary_values():
    for value in ("Hello.", "Value = 12", "", "   ", 12, -5, None):
        assert evaluation.csv_safe(value) == value


def test_outputs_are_new_private_and_include_complete_audits(tmp_path, measured_fixture):
    directory = tmp_path / "new-evaluation"
    paths = evaluation.write_outputs(measured_fixture, directory, markdown=True)
    assert set(paths) == {"summary", "audit", "segments_csv", "sessions_csv", "markdown"}
    assert directory.stat().st_mode & 0o777 == 0o700
    assert all(Path(path).stat().st_mode & 0o777 == 0o600 for path in paths.values())
    audit = json.loads(Path(paths["audit"]).read_text())
    assert audit["segments"][0]["raw_text"] == "We, um, need approval."
    with Path(paths["segments_csv"]).open(newline="") as handle:
        assert len(list(csv.DictReader(handle))) == len(evaluation.VARIANTS)
    with Path(paths["sessions_csv"]).open(newline="") as handle:
        assert len(list(csv.DictReader(handle))) == 2 * len(evaluation.VARIANTS)
    with pytest.raises(FileExistsError):
        evaluation.write_outputs(measured_fixture, directory)


def test_export_escapes_spreadsheet_cells_but_json_keeps_original(tmp_path, measured_fixture):
    report = copy.deepcopy(measured_fixture)
    raw = '=HYPERLINK("https://example.invalid","test")'
    report["segments"][0]["raw_text"] = raw
    paths = evaluation.write_outputs(report, tmp_path / "csv-check")
    with Path(paths["segments_csv"]).open(newline="") as handle:
        assert next(csv.DictReader(handle))["raw_text"] == "'" + raw
    assert json.loads(Path(paths["audit"]).read_text())["segments"][0]["raw_text"] == raw


def test_markdown_does_not_turn_transcript_markup_into_html_or_images():
    cell = evaluation._markdown_cell('<img src="x"> ![test](remote) | value\nnext')
    assert "<img" not in cell
    assert "![test]" not in cell
    assert "\\|" in cell and "<br>" in cell


def test_no_requested_tokenizers_needs_no_optional_package():
    assert evaluation.cached_counters([]) == {}


def test_offline_loader_blocks_cache_miss_download(monkeypatch):
    pytest.importorskip("tiktoken.load")
    import tiktoken.load
    import call_audio.tokens
    attempted_fetches = []
    def forbidden_fetch(*args, **kwargs):
        attempted_fetches.append(args)
        raise AssertionError("Network/file fetch should have been blocked by the evaluator.")
    monkeypatch.setattr(tiktoken.load, "read_file", forbidden_fetch)
    monkeypatch.setattr(call_audio.tokens, "load_token_counter", lambda name: tiktoken.load.read_file("https://not-a-real-tokenizer.invalid"))
    with pytest.raises(RuntimeError, match="did not download"):
        evaluation.cached_counters(["cl100k_base"])
    assert not attempted_fetches
