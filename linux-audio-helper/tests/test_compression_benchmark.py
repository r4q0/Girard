"""Synthetic semantic expectations and benchmark accounting; no tokenizer downloads."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from call_audio.compression import MinimalCompressor, RULES_VERSION

PROJECT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((PROJECT / "tests/fixtures/compression_cases.json").read_text(encoding="utf-8"))
CASES = FIXTURE["cases"]
spec = importlib.util.spec_from_file_location("check_compression", PROJECT / "scripts/check_compression.py")
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_synthetic_sales_case_and_full_character_audit(case):
    compressor = MinimalCompressor(protected_terms=case.get("protected_terms", ()))
    result = benchmark.audit_case(case, compressor)
    assert result["raw_text"] == case["text"]
    assert result["compact_text"] == case["expected_compact"]
    assert result["reference_prompt_tokens"] is None


def test_reference_counter_wraps_both_versions_and_treats_special_strings_as_text():
    class Encoding:
        def __init__(self):
            self.inputs = []
        def encode_ordinary(self, text):
            self.inputs.append(text)
            return [1, 2, 3]
        def encode(self, *args, **kwargs):
            raise AssertionError("Special-token-aware encoding must not parse transcript delimiters.")
    encoding = Encoding()
    count = benchmark.wrapped_counter(encoding)
    assert count("We, um, need <|endoftext|>.") == 3
    assert count("We need <|endoftext|>.") == 3
    assert encoding.inputs == [
        benchmark.PREFIX + "We, um, need <|endoftext|>." + benchmark.SUFFIX,
        benchmark.PREFIX + "We need <|endoftext|>." + benchmark.SUFFIX,
    ]


def test_audit_rejects_an_unexplained_text_change():
    with pytest.raises(AssertionError, match="audit span"):
        benchmark.audit_spans("We cannot commit.", {
            "compact_text": "We can commit.", "compression": {"removed_spans": []}
        })


def test_clean_real_recognizer_output_changes_under_v2_articles_and_punctuation():
    report = json.loads((PROJECT / "reports/local-benchmark.json").read_text())
    raw = report["runs"][0]["final_text"]
    result = MinimalCompressor().compress(raw)
    assert result["compact_text"] == benchmark.NARRATION_V2_EXPECTED
    assert result["compression"]["changed"]
    assert result["compression"]["rules_version"] == "2"
    benchmark.audit_spans(raw, result)


def test_fixture_evidence_is_current_and_preserves_42_reviewed_cases():
    assert RULES_VERSION == FIXTURE["rules_version"] == "2"
    assert len(CASES) == 42
    assert len({case["id"] for case in CASES}) == 42


def test_historical_v1_benchmark_report_cannot_be_overwritten(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["check_compression.py", "--report",
                                     str(PROJECT / "reports/compression-benchmark.json")])
    with pytest.raises(SystemExit) as raised:
        benchmark.main()
    assert raised.value.code == 2
    assert "historical version-1 report is preserved" in capsys.readouterr().err


def test_report_stamps_v2_and_labels_changed_historical_narration():
    report = benchmark.benchmark(iterations=20)
    assert report["rules_version"] == report["evidence"]["fixture_rules_version"] == "2"
    assert report["evidence"]["benchmark_revision"] == "minimal-v2"
    assert report["evidence"]["generated_at_utc"]
    assert report["case_count"] == report["changed_cases"] + report["unchanged_cases"] == 42
    assert report["clean_local_narration"]["compression"]["changed"]
    assert report["reference_token_summary"] is None


def test_positive_guard_rejects_equal_or_increased_counts_without_losing_unicode():
    case = {
        "id": "guarded_unicode", "category": "guard_counterexample",
        "text": "The cost, for José, is €1,234.50.",
        "expected_compact": "cost for José is €1,234.50",
    }
    for candidate_count in (2, 3):
        def counter(text):
            return 2 if text == case["text"] else candidate_count
        compressor = MinimalCompressor(token_counter=counter, tokenizer_name="test:adversarial-count")
        result = benchmark.audit_case(case, compressor, counter)
        assert result["compact_text"] == case["text"]
        assert result["expected_unguarded_compact"] == case["expected_compact"]
        assert result["compression"]["reason"] == "no_token_savings"
        assert result["compression"]["removed_spans"] == []
        assert result["reference_prompt_tokens"]["saved"] == 0


@pytest.mark.parametrize(("raw", "expected"), [
    ("The théatre is for Zoë, not for them.", "théatre is for Zoë not for them"),
    ("THE weather, therefore, is for them.", "weather therefore is for them"),
    ("The fee is €1.234,56 for 1,000 seats on 23.09.2026.",
     "fee is €1.234,56 for 1,000 seats on 23.09.2026"),
])
def test_v2_unicode_for_and_numeric_punctuation_contract(raw, expected):
    result = benchmark.audit_case({"id": "v2-boundaries", "category": "counterexample",
                                   "text": raw, "expected_compact": expected}, MinimalCompressor())
    assert result["compact_text"] == expected


def test_stress_text_lengths_and_oversize_guard():
    compressor = MinimalCompressor()
    for size in (2000, 8192, 8193):
        text = benchmark.stress_text(size)
        assert len(text) == size
        result = compressor.compress(text)
        benchmark.audit_spans(text, result)
        if size > 8192:
            assert result["compact_text"] == text
            assert result["compression"]["reason"] == "limit_exceeded"
