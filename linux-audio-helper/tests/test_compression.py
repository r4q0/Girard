"""V2 rule mechanics and conservative fallbacks, not semantic equivalence proof."""

import random
import re
from unittest.mock import Mock

import pytest

from call_audio.compression import MAX_EDITS, MAX_REMOVED_FILLERS, MAX_SEGMENT_CHARS, MinimalCompressor


def reconstruct(raw, edits):
    restored = raw
    for edit in reversed(edits):
        assert raw[edit["start"]:edit["end"]] == edit["text"]
        restored = restored[:edit["start"]] + edit["replacement"] + restored[edit["end"]:]
    return restored


@pytest.mark.parametrize(("raw", "expected", "removed"), [
    ("We, um, need approval.", "We need approval", 1),
    ("We,uh,need approval.", "We need approval", 1),
    ("We ,\tum\t, \tneed  approval.", "We need  approval", 1),
    ("We, um, uh, need approval.", "We need approval", 2),
    ("We, um, uh, um, need approval, uh, today.", "We need approval today", 4),
    ("We, um, cannot pay more than €500 per month.", "We cannot pay more than €500 per month", 1),
    ("We, uh, are not ready to buy unless approval arrives.", "We are not ready to buy unless approval arrives", 1),
    ("I think we, um, might cancel only if it exceeds £500.", "I think we might cancel only if it exceeds £500", 1),
    ("We can't, um, commit; Acme's price is 15% less.", "We can't commit; Acme's price is 15% less", 1),
    ("We can’t, uh, change O’Reilly’s order.", "We can’t change O’Reilly’s order", 1),
    ("Zoë at Acme, um, needs $1,500.50 by 2026-10-04.", "Zoë at Acme needs $1,500.50 by 2026-10-04", 1),
    ("The email is, um, noah@example.com.", "email is noah@example.com", 2),
])
def test_only_clear_internal_fillers_are_removed(raw, expected, removed):
    compressor = MinimalCompressor()
    result = compressor.compress(raw)
    metadata = result["compression"]
    assert result["compact_text"] == expected
    assert metadata["mode"] == "minimal"
    assert metadata["rules_version"] == "2"
    assert metadata["reason"] == "compressed"
    assert metadata["changed"] is True
    assert metadata["removed_words"] == removed
    assert metadata["tokens"] is None
    assert reconstruct(raw, metadata["removed_spans"]) == expected
    assert compressor.compress(expected)["compact_text"] == expected


@pytest.mark.parametrize("raw", [
    "", "um", "uh", ", um,", "We, um,", ", um, we need approval.",
    "um, uh, approval", "We, um, uh", "We, um, uh, ",
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
    assert result["compact_text"] == "Zoë at Acme needs approval"


def test_unicode_offsets_and_untouched_whitespace():
    raw = "  Zoë 😊,\tum,  needs  €500, uh, today.  "
    result = MinimalCompressor().compress(raw)
    assert result["compact_text"] == "  Zoë 😊 needs  €500 today"
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
    assert result["compact_text"] == "We need approval"
    assert result["compression"]["tokens"] is None
    counter.assert_not_called()


def test_unchanged_text_counts_only_once():
    counter = Mock(return_value=3)
    result = MinimalCompressor(token_counter=counter, tokenizer_name="test").compress("We need approval")
    assert result["compression"]["tokens"]["saved"] == 0
    counter.assert_called_once_with("We need approval")


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
    assert result["compact_text"] == "We need approval"
    assert result["compression"]["removed_words"] == MAX_REMOVED_FILLERS


def test_arbitrary_corpus_is_deterministic_idempotent_and_reconstructable():
    rng = random.Random(813)
    pieces = ["We", "not", "only", "unless", "€500", "Acme", "Zoë", "😊", "can’t", "uh-huh",
              ", um, ", ", uh, ", ", um, uh, ", "UM", "um", "uh", "the", "The", "THE", "for", "FOR", " ", "  ", ",", ".", "'", '"', "\n", "\t"]
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
        assert [word for word in before_words if word not in ("um", "uh") and word.lower() != "the"] == [word for word in after_words if word not in ("um", "uh") and word.lower() != "the"]


@pytest.mark.parametrize("terms", ["um", ("",), (None,)])
def test_invalid_protected_configuration_is_explicit(terms):
    with pytest.raises(ValueError):
        MinimalCompressor(protected_terms=terms)


@pytest.mark.parametrize(("raw", "expected", "removed"), [
    ("The customer, um, needs the contract for the pilot.", "customer needs contract for pilot", 4),
    ("THE plan is for The buyer, not FOR the seller.", "plan is for buyer not FOR seller", 3),
    ("For the pilot, keep the plan for them.", "For pilot keep plan for them", 2),
    ("The, um, contract is for the pilot.", "contract is for pilot", 3),
    ("The, um, the, uh, plan is ready.", "plan is ready", 4),
    ("The the THE plan is ready.", "plan is ready", 3),
    ("We need,the,plan.", "We need plan", 1),
    ("We need the... plan.", "We need plan", 1),
    ("the.other and the-company need the's approval.", "the.other and the-company need the's approval", 0),
    ("We need them, other, therefore, and mother.", "We need them other therefore and mother", 0),
    ("We need the pilot? For the buyer!", "We need pilot? For buyer!", 2),
    ("We need the pilot; for the buyer: yes.", "We need pilot; for buyer: yes", 2),
])
def test_v2_combines_article_filler_and_sentence_punctuation(raw, expected, removed):
    compressor = MinimalCompressor()
    result = compressor.compress(raw)
    assert result["compact_text"] == expected
    assert result["compression"]["removed_words"] == removed
    assert reconstruct(raw, result["compression"]["removed_spans"]) == expected
    assert compressor.compress(expected)["compact_text"] == expected
    # Preserve every literal for token, including its original capitalization.
    assert re.findall(r"\bfor\b", raw, re.I) == re.findall(r"\bfor\b", expected, re.I)


@pytest.mark.parametrize(("raw", "expected"), [
    ("Ready,now. Next,please.", "Ready now Next please"),
    ("Ready... now.", "Ready now"),
    ("Ready,now? Yes!", "Ready now? Yes!"),
    ("Ready. (Next, please.)", "Ready (Next please)"),
    ("We, UM, need approval.", "We UM need approval"),
    ("Um, we need approval.", "Um we need approval"),
    ("We need approval, um.", "We need approval um"),
    ("uh-huh, yes.", "uh-huh yes"),
    ("uh-uh, no.", "uh-uh no"),
])
def test_punctuation_only_changes_do_not_claim_removed_words(raw, expected):
    result = MinimalCompressor().compress(raw)
    assert result["compact_text"] == expected
    assert result["compression"]["removed_words"] == 0
    assert {edit["rule_id"] for edit in result["compression"]["removed_spans"]} == {"remove_sentence_punctuation"}
    assert reconstruct(raw, result["compression"]["removed_spans"]) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("The price is $1,500.50 for 3.14 units.", "price is $1,500.50 for 3.14 units"),
    ("The date is 2026.09.23 for the pilot.", "date is 2026.09.23 for pilot"),
    ("The host is 192.168.1.1 for v2.3.4.", "host is 192.168.1.1 for v2.3.4"),
    ("The rate is .5 for the buyer.", "rate is .5 for buyer"),
    ("Send the report.v2.csv to sales@example.com.", "Send report.v2.csv to sales@example.com"),
    ("Use https://example.com/the,pilot?q=1,2 for the plan.", "Use https://example.com/the,pilot?q=1,2 for plan"),
    ("Use www.example.com/the for the plan.", "Use www.example.com/the for plan"),
    ("Use the@example.com for the plan.", "Use the@example.com for plan"),
    ("Use /the/pilot.txt for the plan.", "Use /the/pilot.txt for plan"),
    ("Use the_company and the-company for the plan.", "Use the_company and the-company for plan"),
    ("Use the’s label for the plan.", "Use the’s label for plan"),
    ("Wait.Here, please.", "Wait.Here please"),
])
def test_technical_fragments_and_numeric_separators_are_retained(raw, expected):
    compressor = MinimalCompressor()
    result = compressor.compress(raw)
    assert result["compact_text"] == expected
    assert reconstruct(raw, result["compression"]["removed_spans"]) == expected
    assert compressor.compress(expected)["compact_text"] == expected


def test_filler_shaped_url_content_is_not_destroyed():
    raw = "Use https://example.com/foo,um,bar for the plan."
    result = MinimalCompressor().compress(raw)
    assert result["compact_text"] == raw
    assert result["compression"]["reason"] == "ambiguous_context"


@pytest.mark.parametrize("raw", [
    'The buyer requested "the plan."', "The password is spelled T H E.",
    "The name is The Company.", "The plan\nfor the buyer.", "The plan\x00for the buyer.",
    "The customers' plan is ready.",
])
def test_v2_global_ambiguity_guard_applies_without_any_filler(raw):
    result = MinimalCompressor().compress(raw)
    assert result["compact_text"] == raw
    assert result["compression"]["reason"] == "ambiguous_context"


@pytest.mark.parametrize(("raw", "term"), [
    ("The plan is for the buyer.", "the buyer"),
    ("We need the plan, now.", "plan, now"),
    ("We need the plan.", "plan."),
])
def test_protected_overlap_with_new_rules_returns_entire_raw(raw, term):
    result = MinimalCompressor(protected_terms=(term,)).compress(raw)
    assert result["compact_text"] == raw
    assert result["compression"]["reason"] == "protected_term"
    assert result["compression"]["removed_spans"] == []


def test_rules_merge_without_losing_original_offset_audit():
    raw = "The, um, contract is for the pilot."
    result = MinimalCompressor().compress(raw)
    edits = result["compression"]["removed_spans"]
    all_rules = {rule for edit in edits for rule in edit["rule_id"].split("+")}
    assert all_rules == {"comma_delimited_filler_run", "remove_definite_article", "remove_sentence_punctuation"}
    assert all(left["end"] <= right["start"] for left, right in zip(edits, edits[1:]))
    assert reconstruct(raw, edits) == result["compact_text"]


@pytest.mark.parametrize("raw", ["the", "THE.", "the, the.", "The um.", ".", ",", "...", "The!"])
def test_deleting_all_meaningful_words_returns_raw(raw):
    result = MinimalCompressor().compress(raw)
    assert result["compact_text"] == raw
    assert result["compression"]["removed_words"] == 0
    assert result["compression"]["removed_spans"] == []


def test_new_edit_limit_bypasses_token_counting():
    raw = "the item " * (MAX_EDITS + 1)
    counter = Mock(side_effect=AssertionError("edit guard must avoid token work"))
    result = MinimalCompressor(token_counter=counter, tokenizer_name="test").compress(raw)
    assert result["compact_text"] == raw
    assert result["compression"]["reason"] == "limit_exceeded"
    counter.assert_not_called()


def test_plain_unchanged_reason_and_version_are_current():
    result = MinimalCompressor().compress("We need approval for them")
    assert result["compression"]["reason"] == "no_eligible_changes"
    assert result["compression"]["rules_version"] == "2"


@pytest.mark.parametrize("raw", ["The plan for the buyer.", "Ready, now."])
def test_token_guard_covers_new_rules_too(raw):
    result = MinimalCompressor(token_counter=lambda _: 8, tokenizer_name="test").compress(raw)
    assert result["compact_text"] == raw
    assert result["compression"]["reason"] == "no_token_savings"
    assert result["compression"]["removed_spans"] == []


def test_adversarial_adjacent_contexts_are_idempotent():
    rng = random.Random(173)
    pieces = ["the", "The", "THE", "for", "FOR", "the's", "the-company", "other", "them", ".", ",", "...",
              "um", "uh", "1,500.50", "2026.09.23", "a.b", "x@the.example", "hello", "😊", " ", "\t", "?", "!"]
    compressor = MinimalCompressor()
    for _ in range(1500):
        raw = "".join(rng.choices(pieces, k=rng.randint(1, 35)))
        result = compressor.compress(raw)
        compact = result["compact_text"]
        assert compressor.compress(compact)["compact_text"] == compact, (raw, compact)
        assert reconstruct(raw, result["compression"]["removed_spans"]) == compact
