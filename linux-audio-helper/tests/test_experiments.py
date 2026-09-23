"""Experimental tradeoffs: audit correctness does not imply meaning preservation."""

import random
import re

import pytest

from call_audio.compression import MAX_SEGMENT_CHARS, MinimalCompressor
from call_audio.experiments import MAX_EXPERIMENT_EDITS, VARIANTS, compress_variant


def reconstruct(text, spans):
    result = text
    previous_end = 0
    for span in spans:
        assert 0 <= span["start"] < span["end"] <= len(text)
        assert span["start"] >= previous_end
        assert span["text"] == text[span["start"]:span["end"]]
        assert span["rule_id"]
        previous_end = span["end"]
    for span in reversed(spans):
        result = result[:span["start"]] + span["replacement"] + result[span["end"]:]
    return result


def test_public_variant_contract():
    assert VARIANTS == ("raw", "minimal", "disfluency", "telegraphic_light", "telegraphic_aggressive")
    for variant in VARIANTS:
        result = compress_variant("We, um, are the buyer.", variant)
        assert set(result) == {"compact_text", "removed_spans", "rules", "risk"}
        assert isinstance(result["rules"], list)
        assert isinstance(result["risk"], str)
        assert reconstruct("We, um, are the buyer.", result["removed_spans"]) == result["compact_text"]


@pytest.mark.parametrize("text", [
    "We, um, need approval.", "Um, we need approval.", 'We said "um".',
    "We, um, uh, need €500.", "We, um, need approval, uh, today.",
])
def test_minimal_control_exactly_wraps_production(text):
    expected = MinimalCompressor().compress(text)
    actual = compress_variant(text, "minimal")
    assert actual["compact_text"] == expected["compact_text"]
    assert actual["removed_spans"] == expected["compression"]["removed_spans"]


@pytest.mark.parametrize(("text", "expected"), [
    ("Um, we need approval.", "we need approval."),
    ("We need approval, uh.", "We need approval."),
    ("We um need approval.", "We need approval."),
    ("Erm, uh, we, um, need approval, er.", "we need approval."),
    ("Well, basically, we need approval.", "we need approval."),
    ("We, um, uh, need approval.", "We need approval."),
    ("Zoë, um, needs €500.", "Zoë needs €500."),
])
def test_expanded_disfluency_examples(text, expected):
    result = compress_variant(text, "disfluency")
    assert result["compact_text"] == expected
    assert reconstruct(text, result["removed_spans"]) == expected


@pytest.mark.parametrize("text", [
    "It works well.", "The well, pump, and pipe are broken.", "Basically this is required.",
    "ER accepts this patient.", "We, UM, need approval.", "We, UH, disagree.",
    "uh-uh, no", "uh-huh, yes", "We need uh-huh confirmation.",
    'He wrote "We, um, need the contract."', "She asked ‘We, um, need it?’",
    "Spell um correctly.", "The word, uh, is literal.", "Her name is Um.",
    "We, um, need\nthose contracts.", "Um.", "uh", "um, uh, erm.",
])
def test_disfluency_retains_ambiguous_and_meaningful_material(text):
    assert compress_variant(text, "disfluency")["compact_text"] == text


@pytest.mark.parametrize("variant", VARIANTS)
def test_semantic_tokens_survive_all_variants(variant):
    text = "We, um, cannot agree to the deal unless you can pay €500.50 for 12 seats, only if they might renew, not cancel."
    result = compress_variant(text, variant)
    for token in ("We", "cannot", "unless", "you", "can", "€500.50", "12", "seats", "only", "if", "they", "might", "not", "cancel"):
        assert token in result["compact_text"]
    assert reconstruct(text, result["removed_spans"]) == result["compact_text"]


@pytest.mark.parametrize("variant", VARIANTS[2:])
def test_protected_phrases_and_obvious_names_survive(variant):
    text = "Um Health works with Bank of the West on the who campaign."
    result = compress_variant(text, variant, protected_terms=("Um Health", "the who"))
    assert "Um Health" in result["compact_text"]
    assert "Bank of the West" in result["compact_text"]
    assert "the who" in result["compact_text"]
    assert reconstruct(text, result["removed_spans"]) == result["compact_text"]


def test_literal_protection_cannot_be_regex():
    assert compress_variant("We um agree.", "disfluency", protected_terms=(".*",))["compact_text"] == "We agree."
    assert compress_variant("We um agree.", "disfluency", protected_terms=("UM",))["compact_text"] == "We um agree."


@pytest.mark.parametrize("text", [
    "We need 12 in of cable at 10 am.",
    "We need five to ten seats for a month.",
    "We need at least five seats.",
    "We use a.example.com and uh-huh.example.org.",
])
def test_quantity_and_identifier_fragments_are_preserved(text):
    result = compress_variant(text, "telegraphic_aggressive")
    for protected in ("12 in", "10 am", "five to ten", "a month", "at least", "a.example.com", "uh-huh.example.org"):
        if protected in text:
            assert protected in result["compact_text"]


def test_progressive_grammar_rules_are_explicit():
    text = "We, um, are the buyer in the contract."
    assert compress_variant(text, "disfluency")["compact_text"] == "We are the buyer in the contract."
    light = compress_variant(text, "telegraphic_light")
    assert light["compact_text"] == "We are buyer in contract."
    assert "article_deletion" in light["rules"]
    aggressive = compress_variant(text, "telegraphic_aggressive")
    assert aggressive["compact_text"] == "We buyer contract."
    assert {"article_deletion", "copula_deletion", "preposition_deletion"} <= set(aggressive["rules"])
    assert "dangerous" in aggressive["risk"]


def test_dangerous_counterexample_direction_is_destroyed():
    # The same compact text now represents opposite payment directions.
    incoming = compress_variant("payment from buyer to seller.", "telegraphic_aggressive")
    outgoing = compress_variant("payment to buyer from seller.", "telegraphic_aggressive")
    assert incoming["compact_text"] == outgoing["compact_text"] == "payment buyer seller."
    assert "dangerous" in incoming["risk"]


def test_dangerous_counterexample_tense_is_destroyed():
    past = compress_variant("We were the owner.", "telegraphic_aggressive")
    present = compress_variant("We are the owner.", "telegraphic_aggressive")
    assert past["compact_text"] == present["compact_text"] == "We owner."


def test_article_counterexample_reference_is_weakened():
    # The definite, already-discussed vendor becomes an unspecified label.
    result = compress_variant("We need the vendor.", "telegraphic_light")
    assert result["compact_text"] == "We need vendor."
    assert "definiteness" in result["risk"]


@pytest.mark.parametrize("variant", VARIANTS)
def test_empty_and_size_guards_keep_original(variant):
    for raw in ("", "We um need " + "x" * MAX_SEGMENT_CHARS):
        result = compress_variant(raw, variant)
        assert result["compact_text"] == raw
        assert result["removed_spans"] == []


def test_edit_limit_keeps_original():
    raw = "We " + "the item " * (MAX_EXPERIMENT_EDITS + 1)
    result = compress_variant(raw, "telegraphic_aggressive")
    assert result["compact_text"] == raw
    assert "edit limit" in result["risk"]


def test_punctuation_only_or_all_deleted_falls_back():
    for raw in ("um, uh.", "the a an", "is are was", "in on at"):
        result = compress_variant(raw, "telegraphic_aggressive")
        assert result["compact_text"] == raw
        assert result["removed_spans"] == []


def test_deterministic_corpus_reconstructs_and_preserves_nonselected_words():
    rng = random.Random(1117)
    pieces = ["We", "we", "you", "they", "cannot", "not", "unless", "if", "might", "€500", "25", "Zoë",
              "need", "contract", "vendor", "are", "were", "the", "a", "an", "from", "to", "with", "um", "uh", "erm", "er", ",", ".", " ", "😊"]
    deletable = {"um", "uh", "erm", "er", "well", "basically", "the", "a", "an", "am", "is", "are", "was", "were", "be", "been", "being", "of", "to", "from", "in", "on", "at", "for", "with", "by", "as"}
    for _ in range(200):
        raw = " ".join(rng.choices(pieces, k=rng.randint(1, 30)))
        for variant in VARIANTS:
            result = compress_variant(raw, variant)
            assert result == compress_variant(raw, variant)
            assert reconstruct(raw, result["removed_spans"]) == result["compact_text"]
            before = [word for word in re.findall(r"\w+", raw) if word.lower() not in deletable]
            after = [word for word in re.findall(r"\w+", result["compact_text"]) if word.lower() not in deletable]
            assert before == after


def test_rejects_invalid_variant_and_configuration():
    with pytest.raises(ValueError):
        compress_variant("We need approval.", "production_aggressive")
    with pytest.raises(ValueError):
        compress_variant("We need approval.", "raw", protected_terms="um")
    with pytest.raises(ValueError):
        compress_variant("We need approval.", "raw", protected_terms=("",))
