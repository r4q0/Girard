"""Synthetic semantic expectations and benchmark accounting; no tokenizer downloads."""

import importlib.util
import json
from pathlib import Path

import pytest

from call_audio.compression import MinimalCompressor

PROJECT = Path(__file__).resolve().parents[1]
CASES = json.loads((PROJECT / "tests/fixtures/compression_cases.json").read_text(encoding="utf-8"))["cases"]
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


def test_no_changes_to_clean_real_recognizer_output():
    report = json.loads((PROJECT / "reports/local-benchmark.json").read_text())
    raw = report["runs"][0]["final_text"]
    result = MinimalCompressor().compress(raw)
    assert result["compact_text"] == raw
    assert not result["compression"]["changed"]


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
