"""Semantic guards and reconstruction checks for the opt-in filler pass."""

import random
import re
from unittest.mock import Mock

import pytest

from call_audio.compression import MAX_REMOVED_FILLERS, MAX_SEGMENT_CHARS, MinimalCompressor


def reconstruct(raw, edits):
    restored = raw
    for edit in reversed(edits):
        assert raw[edit["start"]:edit["end"]] == edit["text"]
        restored = restored[:edit["start"]] + edit["replacement"] + restored[edit["end"]:]
    return restored


@pytest.mark.parametrize(("raw", "expected", "removed"), [
    ("We, um, need approval.", "We need approval.", 1),
    ("We,uh,need approval.", "We need approval.", 1),
    ("We ,\tum\t, \tneed  approval.", "We need  approval.", 1),
    ("We, um, uh, need approval.", "We need approval.", 2),
    ("We, um, uh, um, need approval, uh, today.", "We need approval today.", 4),
    ("We, um, cannot pay more than €500 per month.", "We cannot pay more than €500 per month.", 1),
    ("We, uh, are not ready to buy unless approval arrives.", "We are not ready to buy unless approval arrives.", 1),
    ("I think we, um, might cancel only if it exceeds £500.", "I think we might cancel only if it exceeds £500.", 1),
    ("We can't, um, commit; Acme's price is 15% less.", "We can't commit; Acme's price is 15% less.", 1),
    ("We can’t, uh, change O’Reilly’s order.", "We can’t change O’Reilly’s order.", 1),
    ("Zoë at Acme, um, needs $1,500.50 by 2026-10-04.", "Zoë at Acme needs $1,500.50 by 2026-10-04.", 1),
    ("The email is, um, noah@example.com.", "The email is noah@example.com.", 1),
])
def test_only_clear_internal_fillers_are_removed(raw, expected, removed):
    compressor = MinimalCompressor()
    result = compressor.compress(raw)
    metadata = result["compression"]
    assert result["compact_text"] == expected
    assert metadata["mode"] == "minimal"
    assert metadata["rules_version"] == "1"
    assert metadata["reason"] == "compressed"
    assert metadata["changed"] is True
    assert metadata["removed_words"] == removed
    assert metadata["tokens"] is None
    assert reconstruct(raw, metadata["removed_spans"]) == expected
    assert compressor.compress(expected)["compact_text"] == expected


@pytest.mark.parametrize("raw", [
    "", "um", "uh", ", um,", "Um, we need approval.", "um, we need approval.",
    "We need approval, um.", "We, um,", ", um, we need approval.",
    "um, uh, approval", "We, um, uh", "We, um, uh, ", "We, UM, need approval.",
    "We, Uh, need approval.", "We, umami, need approval.",
    "uh-uh, no", "uh-huh, yes", "We, uh-huh, agree.", "We, uh-uh, disagree.",
    "We are not ready to buy.", "Only if it is under 500 euros.",
    "I think we might cancel.", "Well, actually, I just sort of like it, you know.",
    "No, no, never. I mean yes—no, only if procurement agrees.",
    'She asked "We, um, need approval."', "She asked 'We, um, need approval.'",
    'She asked “We, um, need approval.”', "She asked ‘We, um, need approval.’",
    "She asked ‚We, um, need approval.‛", "She asked 「We, um, need approval.」",
    "We, um, need an unmatched 'quote", "The customers', um, invoices arrived.",
    "The word, um, is a hesitation.", "Spell, um, as U M.",
    "The acronym, uh, is not a filler.", "Her name, um, is written here.",
    "It is U, um, H.", "The code is, uh, A B C.",
    "We call it a spelling test, um, today.", "We. , um, need approval.",
    "We, um, . Need approval.", "We, um, , uh, need approval.",
    "We, um, need approval.\nToday.", "We, um, need\x00approval.",
    "We, um, need `literal text`.",
])
def test_ambiguous_or_meaningful_material_is_unchanged(raw):
    result = MinimalCompressor().compress(raw)
    assert result["compact_text"] == raw
    assert result["compression"]["changed"] is False
    assert result["compression"]["removed_words"] == 0
    assert result["compression"]["removed_spans"] == []


def test_whole_segment_is_retained_if_one_candidate_is_ambiguous():
    raw = "We, um, need approval, uh,"
    result = MinimalCompressor().compress(raw)
    assert result["compact_text"] == raw
    assert result["compression"]["reason"] == "ambiguous_context"


@pytest.mark.parametrize("terms", [("um",), ("UM",), ("um, need",), ("We, um",)])
def test_protected_terms_overlap_candidate_spans(terms):
    raw = "We, um, need approval, uh, today."
    result = MinimalCompressor(protected_terms=terms).compress(raw)
    assert result["compact_text"] == raw
    assert result["compression"]["reason"] == "protected_term"


def test_other_protected_names_and_regex_characters_are_literal():
    result = MinimalCompressor(protected_terms=("Acme", ".*", "Zoë")).compress("Zoë at Acme, um, needs approval.")
    assert result["compact_text"] == "Zoë at Acme needs approval."


def test_unicode_offsets_and_untouched_whitespace():
    raw = "  Zoë 😊,\tum,  needs  €500, uh, today.  "
    result = MinimalCompressor().compress(raw)
    assert result["compact_text"] == "  Zoë 😊 needs  €500 today.  "
    assert reconstruct(raw, result["compression"]["removed_spans"]) == result["compact_text"]


def test_named_local_counter_reports_measured_counts():
    counter = Mock(side_effect=lambda value: len(value.split()))
    result = MinimalCompressor(token_counter=counter, tokenizer_name="test-whitespace").compress("We, um, need approval.")
    assert result["compression"]["tokens"] == {"tokenizer": "test-whitespace", "raw": 4, "compact": 3, "saved": 1}
    assert counter.call_count == 2


@pytest.mark.parametrize("values", [(4, 4), (4, 7)])
def test_no_measured_token_savings_returns_raw(values):
    raw = "We, um, need approval."
    result = MinimalCompressor(token_counter=Mock(side_effect=values), tokenizer_name="test").compress(raw)
    assert result["compact_text"] == raw
    assert result["compression"]["reason"] == "no_token_savings"
    assert result["compression"]["changed"] is False
    assert result["compression"]["removed_words"] == 0
    assert result["compression"]["removed_spans"] == []
    assert result["compression"]["tokens"] == {"tokenizer": "test", "raw": 4, "compact": 4, "saved": 0}


@pytest.mark.parametrize("counter", [
    Mock(side_effect=RuntimeError("unavailable")), Mock(side_effect=[4, RuntimeError("failed")]),
    lambda text: -1, lambda text: True, lambda text: 1.5, lambda text: None,
])
def test_token_count_failures_never_lose_text(counter):
    raw = "We, um, need approval."
    result = MinimalCompressor(token_counter=counter, tokenizer_name="test").compress(raw)
    assert result["compact_text"] == raw
    assert result["compression"]["reason"] == "token_count_failed"
    assert result["compression"]["changed"] is False
    assert result["compression"]["removed_spans"] == []
    assert result["compression"]["tokens"] is None


def test_unnamed_counter_does_not_claim_token_measurement():
    counter = Mock(side_effect=AssertionError("Unknown tokenizer must not run"))
    result = MinimalCompressor(token_counter=counter).compress("We, um, need approval.")
    assert result["compact_text"] == "We need approval."
    assert result["compression"]["tokens"] is None
    counter.assert_not_called()


def test_unchanged_text_counts_only_once():
    counter = Mock(return_value=3)
    result = MinimalCompressor(token_counter=counter, tokenizer_name="test").compress("We need approval.")
    assert result["compression"]["tokens"]["saved"] == 0
    counter.assert_called_once_with("We need approval.")


@pytest.mark.parametrize("raw", [
    "We, um, need " + "a" * MAX_SEGMENT_CHARS,
    "We" + ", um" * (MAX_REMOVED_FILLERS + 1) + ", need approval.",
])
def test_input_guards_bypass_extra_work(raw):
    counter = Mock(side_effect=AssertionError("Oversize input must bypass token work"))
    result = MinimalCompressor(token_counter=counter, tokenizer_name="test").compress(raw)
    assert result["compact_text"] == raw
    assert result["compression"]["reason"] == "limit_exceeded"
    assert result["compression"]["tokens"] is None
    counter.assert_not_called()


def test_limit_boundaries_are_inclusive():
    prefix = "We, um, need "
    raw = prefix + "a" * (MAX_SEGMENT_CHARS - len(prefix))
    assert MinimalCompressor().compress(raw)["compression"]["changed"] is True
    raw = "We" + ", um" * MAX_REMOVED_FILLERS + ", need approval."
    result = MinimalCompressor().compress(raw)
    assert result["compact_text"] == "We need approval."
    assert result["compression"]["removed_words"] == MAX_REMOVED_FILLERS


def test_arbitrary_corpus_is_deterministic_idempotent_and_reconstructable():
    rng = random.Random(813)
    pieces = ["We", "not", "only", "unless", "€500", "Acme", "Zoë", "😊", "can’t", "uh-huh",
              ", um, ", ", uh, ", ", um, uh, ", "UM", "um", "uh", " ", "  ", ",", ".", "'", '"', "\n", "\t"]
    compressor = MinimalCompressor()
    for _ in range(1000):
        raw = " ".join(rng.choices(pieces, k=rng.randint(1, 35)))
        first = compressor.compress(raw)
        assert compressor.compress(raw) == first
        compact = first["compact_text"]
        assert compressor.compress(compact)["compact_text"] == compact
        assert reconstruct(raw, first["compression"]["removed_spans"]) == compact
        before_words = re.findall(r"\w+(?:['’]\w+)*", raw)
        after_words = re.findall(r"\w+(?:['’]\w+)*", compact)
        assert [word for word in before_words if word not in ("um", "uh")] == [word for word in after_words if word not in ("um", "uh")]


@pytest.mark.parametrize("terms", ["um", ("",), (None,)])
def test_invalid_protected_configuration_is_explicit(terms):
    with pytest.raises(ValueError):
        MinimalCompressor(protected_terms=terms)
