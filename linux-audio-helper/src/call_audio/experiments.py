"""Offline-only, auditable compression experiments. NOT production API modes.

``raw`` and the current production ``minimal`` are controls. Historical saved
reports may refer to an earlier minimal rules version; re-running now uses the
current implementation. The other variants deliberately trade
linguistic information for brevity. They never invoke a model, tokenizer, or
network service, and do not claim semantic equivalence or token savings.

All edits use original Unicode character offsets (end-exclusive). Apply them in
reverse order to reconstruct compact_text. Rules are one pass over the original
segment, not a promise that repeated experimental compaction is safe/idempotent.
The caller must retain the original recording/transcript for every comparison.
"""

from __future__ import annotations

import re

from .compression import MAX_SEGMENT_CHARS, MinimalCompressor

VARIANTS = ("raw", "minimal", "disfluency", "telegraphic_light", "telegraphic_aggressive")
MAX_EXPERIMENT_EDITS = 512

RISKS = {
    "raw": "none: original transcript unchanged",
    "minimal": "production v2: filler/article/punctuation removal can lose hesitation, definiteness, and sentence boundaries",
    "disfluency": "moderate: broader filler and introductory well/basically deletion loses hesitation or emphasis",
    "telegraphic_light": "high: article deletion additionally loses definiteness and may change implied quantities or names",
    "telegraphic_aggressive": "dangerous: copula/preposition deletion additionally destroys tense, attribution, and relationships",
}

_MINIMAL = MinimalCompressor()
_WORD = re.compile(r"[^\W_]+(?:['’][^\W_]+)*", re.UNICODE)
_META = re.compile(
    r"\b(?:spell|spells|spelled|spelt|spelling|word|phrase|letter|letters|"
    r"acronym|abbreviation|initials|initialism|name|names|named|called|"
    r"pronounce|pronounced|pronunciation|quote|quoted)\b", re.IGNORECASE,
)
_QUOTES = frozenset('"“”„‟«»‹›‘‚‛`「」『』《》〈〉〝〞〟＂＇❛❜❝❞')
_FILLERS = frozenset(("um", "uh", "erm", "er"))
_INTRODUCTORY = frozenset(("well", "basically"))
_ARTICLES = frozenset(("a", "an", "the"))
_COPULAS = frozenset(("am", "is", "are", "was", "were", "be", "been", "being"))
_PREPOSITIONS = frozenset(("of", "to", "from", "in", "on", "at", "for", "with", "by", "as"))
_NAME_BRIDGES = _ARTICLES | _PREPOSITIONS | frozenset(("and",))
_COMMON_CAPITALIZED = frozenset((
    "I", "We", "You", "He", "She", "It", "They", "This", "That", "These", "Those",
    "My", "Our", "Your", "His", "Her", "Their", "Um", "Uh", "Er", "Erm", "Well", "Basically",
))
_QUANTITY_WORDS = frozenset((
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
    "nineteen", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety",
    "hundred", "thousand", "million", "billion", "trillion", "half", "quarter", "dozen",
    "first", "second", "third", "least", "most", "more", "less", "fewer",
    "percent", "percentage", "dollar", "dollars", "euro", "euros", "pound", "pounds", "cents",
    "usd", "eur", "gbp", "ms", "milliseconds", "seconds", "minute", "minutes", "hour", "hours",
    "day", "days", "week", "weeks", "month", "months", "year", "years", "inch", "inches",
    "foot", "feet", "meter", "meters", "kg", "kilograms", "license", "licenses", "seat", "seats",
))
_JOINING = frozenset("-_‐‑–—/@\\'")


def _unchanged(text, variant, reason=None):
    risk = RISKS[variant] + (f"; unchanged: {reason}" if reason else "")
    return {"compact_text": text, "removed_spans": [], "rules": [], "risk": risk}


def _ambiguous(text):
    if _META.search(text):
        return True
    for index, character in enumerate(text):
        if character in _QUOTES or (ord(character) < 32 and character != "\t"):
            return True
        if character in "'’" and not (
            index and index + 1 < len(text)
            and text[index - 1].isalnum() and text[index + 1].isalnum()
        ):
            return True
    return False


def _fragment(text, word):
    before = text[word.start() - 1] if word.start() else ""
    after = text[word.end()] if word.end() < len(text) else ""
    if before in _JOINING or after in _JOINING:
        return True
    # Preserve components of domains, emails, identifiers, and dotted initials.
    return bool((before == "." and word.start() > 1 and text[word.start() - 2].isalnum())
                or (after == "." and word.end() + 1 < len(text) and text[word.end() + 1].isalnum()))


def _capitalized(word):
    return word[:1].isupper() and word not in _COMMON_CAPITALIZED


def _name_spans(words):
    """Protect obvious capitalized names, including Bank of the West patterns.

    This is a conservative clue, not entity recognition. Lowercase entity names
    containing function words require explicit protected_terms.
    """
    spans = []
    for index, word in enumerate(words):
        if not _capitalized(word.group()):
            continue
        cursor = index + 1
        while cursor < len(words) and cursor <= index + 5:
            value = words[cursor].group()
            if _capitalized(value):
                spans.append((word.start(), words[cursor].end()))
                break
            if value.lower() not in _NAME_BRIDGES:
                break
            cursor += 1
    return spans


def _near_quantity(words, index):
    neighbors = words[max(0, index - 1):index] + words[index + 1:index + 2]
    return any(any(character.isdigit() for character in word.group())
               or word.group().lower() in _QUANTITY_WORDS for word in neighbors)


def _overlaps(start, end, spans):
    return any(start < right and end > left for left, right in spans)


def _candidate_span(text, word, remove_commas):
    start, end = word.span()
    while start and text[start - 1] in " \t":
        start -= 1
    while end < len(text) and text[end] in " \t":
        end += 1
    if remove_commas:
        if start and text[start - 1] == ",":
            start -= 1
        if end < len(text) and text[end] == ",":
            end += 1
        while start and text[start - 1] in " \t":
            start -= 1
        while end < len(text) and text[end] in " \t":
            end += 1
    return start, end


def compress_variant(text: str, variant: str, *, protected_terms=()) -> dict:
    """Apply an experimental variant once, without token-count enforcement.

    Variants are progressive: disfluency adds standalone um/uh/erm/er (also
    boundaries) and comma-marked initial well/basically; light adds lowercase
    articles; aggressive also removes lowercase copulas and listed prepositions.
    Pronouns, negation, modal verbs, numeric tokens, and content words are never
    selected by a broad stopword list. Grammar deletion remains semantically
    dangerous even when those individual tokens survive.
    """
    if variant not in VARIANTS:
        raise ValueError(f"Unknown experimental variant: {variant!r}")
    if not isinstance(text, str):
        raise TypeError("Experimental compression expects a text string.")
    if isinstance(protected_terms, str):
        raise ValueError("protected_terms must be a collection of nonempty strings.")
    protected_terms = tuple(protected_terms)
    if any(not isinstance(term, str) or not term.strip() for term in protected_terms):
        raise ValueError("protected_terms must contain nonempty strings.")
    if variant == "raw":
        return _unchanged(text, variant)
    if variant == "minimal":
        compressor = MinimalCompressor(protected_terms) if protected_terms else _MINIMAL
        result = compressor.compress(text)
        edits = result["compression"]["removed_spans"]
        return {"compact_text": result["compact_text"], "removed_spans": edits,
                "rules": list(dict.fromkeys(edit["rule_id"] for edit in edits)), "risk": RISKS[variant]}
    if len(text) > MAX_SEGMENT_CHARS:
        return _unchanged(text, variant, "length limit")
    if _ambiguous(text):
        return _unchanged(text, variant, "quoted/metalinguistic/ambiguous segment")

    words = list(_WORD.finditer(text))
    protected = _name_spans(words)
    for term in protected_terms:
        protected.extend(match.span() for match in re.finditer(re.escape(term), text, re.IGNORECASE))
    candidates = []
    initial = True
    for index, word in enumerate(words):
        value = word.group()
        lowered = value.lower()
        rule = None
        commas = False
        fragment = _fragment(text, word)
        # Uppercase ER/UH/UM can be acronyms; title case is accepted only at the
        # leading boundary. A configured name always overrides a candidate.
        if lowered in _FILLERS and (value == lowered or (initial and value == lowered.capitalize())):
            rule, commas = "extended_hesitation", True
        elif initial and lowered in _INTRODUCTORY and not value.isupper():
            if text[word.end():].lstrip(" \t").startswith(","):
                rule, commas = "initial_discourse_marker", True
        elif variant in ("telegraphic_light", "telegraphic_aggressive") and value in _ARTICLES:
            rule = "article_deletion"
        elif variant == "telegraphic_aggressive" and value in _COPULAS:
            rule = "copula_deletion"
        elif variant == "telegraphic_aggressive" and value in _PREPOSITIONS:
            rule = "preposition_deletion"
        if rule not in ("extended_hesitation", "initial_discourse_marker"):
            initial = False
        if rule is None or fragment or _overlaps(word.start(), word.end(), protected):
            continue
        if rule in ("article_deletion", "copula_deletion", "preposition_deletion"):
            if _near_quantity(words, index):
                continue
            neighbors = words[max(0, index - 1):index] + words[index + 1:index + 2]
            if any(_capitalized(item.group()) for item in neighbors):
                continue
        start, end = _candidate_span(text, word, commas)
        if _overlaps(start, end, protected):
            continue
        candidates.append((start, end, rule))
        if len(candidates) > MAX_EXPERIMENT_EDITS:
            return _unchanged(text, variant, "edit limit")

    # Overlapping/adjacent removals share whitespace/commas. Merge them before
    # constructing edits so every span refers directly to the original input.
    merged = []
    for start, end, rule in candidates:
        if merged and start <= merged[-1][1]:
            old_start, old_end, rules = merged[-1]
            merged[-1] = (old_start, max(old_end, end), rules + ([rule] if rule not in rules else []))
        else:
            merged.append((start, end, [rule]))
    edits = []
    applied_rules = []
    for start, end, rules in merged:
        replacement = " "
        if start == 0 or end == len(text) or text[end] in ",.;:!?)]}" or text[start - 1] in "([{":
            replacement = ""
        edits.append({"start": start, "end": end, "text": text[start:end],
                      "replacement": replacement, "rule_id": "+".join(rules)})
        applied_rules.extend(rule for rule in rules if rule not in applied_rules)
    parts = []
    cursor = 0
    for edit in edits:
        parts.extend((text[cursor:edit["start"]], edit["replacement"]))
        cursor = edit["end"]
    parts.append(text[cursor:])
    compact = "".join(parts)
    remaining = list(_WORD.finditer(compact))
    if not remaining or all(word.group().lower() in _FILLERS for word in remaining):
        return _unchanged(text, variant, "would leave no meaningful words")
    return {"compact_text": compact, "removed_spans": edits, "rules": applied_rules, "risk": RISKS[variant]}
