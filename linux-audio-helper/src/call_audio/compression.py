"""Conservative, local-only shortening of finalized English STT segments.

This module does not detect language. Callers must retain the original text and
must opt in before applying it to finalized English segments. Removing a filler
also removes its hesitation signal; even these rules cannot promise semantic
equivalence for arbitrary speech.

Stable reasons (rules_version ``1``):
* compressed: eligible fillers removed, with measured savings if configured.
* no_eligible_fillers: no eligible lowercase comma-delimited filler run.
* ambiguous_context: quotes, spelling/name discussion, boundaries, or controls.
* protected_term: an edit would overlap a configured protected phrase.
* limit_exceeded: more than 8192 characters or 64 candidate fillers; no token work.
* no_token_savings: a named tokenizer found no decrease; original returned.
* token_count_failed: token counter failed/returned invalid data; original returned.

Spans use Python/Unicode character offsets into the original segment, with an
exclusive ``end``. Replacing all spans (in reverse order) exactly reconstructs
``compact_text``. There is no global transcript cache, model, or network access.
"""

from __future__ import annotations

import re
from collections.abc import Callable

MAX_SEGMENT_CHARS = 8192
MAX_REMOVED_FILLERS = 64
RULES_VERSION = "1"
RULE_ID = "comma_delimited_filler_run"

# Starting at a literal comma avoids a quadratic search through long whitespace.
# One match consumes an entire adjacent filler run, including shared commas.
_FILLER_RUN = re.compile(r",[ \t]*(?:um|uh)(?:[ \t]*,[ \t]*(?:um|uh))*[ \t]*,")
_FILLER_WORD = re.compile(r"\b(?:um|uh)\b")
_WORD = re.compile(r"[^\W_]+(?:['’][^\W_]+)*", re.UNICODE)
_META_WORD = re.compile(
    r"\b(?:spell|spells|spelled|spelling|say|says|said|saying|word|words|phrase|"
    r"letter|letters|initial|initials|acronym|abbreviation|name|names|named|"
    r"called|means|meaning|pronounce|pronounced|pronunciation|quote|quoted|"
    r"spelt|code|codes|identifier|identifiers|initialism)\b",
    re.IGNORECASE,
)
_QUOTES = frozenset('"“”„‟«»‹›‘‚‛`「」『』《》〈〉〝〞〟＂＇❛❜❝❞')
_CLAUSE_BOUNDARIES = frozenset(".,;:!?")


def _ambiguous(text: str) -> bool:
    if _META_WORD.search(text) or re.search(r",[ \t]*,", text):
        return True
    for index, character in enumerate(text):
        if character in _QUOTES or (ord(character) < 32 and character != "\t"):
            return True
        if character in "'’":
            # can't / customer's are words, but quoted or unmatched apostrophes
            # are ambiguous. Plural possessives conservatively stay unchanged.
            if not (index and index + 1 < len(text)
                    and text[index - 1].isalnum() and text[index + 1].isalnum()):
                return True
    return False


def _meaningful_context(text: str, start: int, end: int) -> bool:
    left_words = list(_WORD.finditer(text, 0, start))
    right_word = _WORD.search(text, end)
    if not left_words or right_word is None:
        return False
    left_word = left_words[-1]
    if left_word.group().lower() in ("um", "uh") or right_word.group().lower() in ("um", "uh"):
        return False
    if (len(left_word.group()) == len(right_word.group()) == 1
            and left_word.group().isalpha() and right_word.group().isalpha()):
        return False  # Potential letter-by-letter spelling without an explicit cue.
    # A filler on either side of a sentence/clause boundary isn't interior to
    # meaningful speech just because another sentence exists elsewhere.
    surrounding = text[left_word.end():start] + text[end:right_word.start()]
    return not any(character in _CLAUSE_BOUNDARIES for character in surrounding)


class MinimalCompressor:
    """A deterministic, bounded filler pass with an optional named tokenizer.

    ``token_counter`` must be local and return a non-negative integer. Both a
    counter and a nonempty ``tokenizer_name`` are needed to report token counts.
    It may count a complete downstream prompt wrapping the supplied text; use
    exactly the same wrapper for both inputs. Oversized inputs bypass counting.
    Protected phrases use case-insensitive literal matches, not regex syntax.
    """

    def __init__(
        self,
        protected_terms: tuple[str, ...] = (),
        token_counter: Callable[[str], int] | None = None,
        tokenizer_name: str | None = None,
    ):
        if isinstance(protected_terms, str):
            raise ValueError("protected_terms must be a collection of nonempty strings.")
        terms = tuple(protected_terms)
        if any(not isinstance(term, str) or not term.strip() for term in terms):
            raise ValueError("protected_terms must contain nonempty strings.")
        self._protected = tuple(re.compile(re.escape(term), re.IGNORECASE) for term in terms)
        self._counter = token_counter if callable(token_counter) and isinstance(tokenizer_name, str) and tokenizer_name.strip() else None
        self._tokenizer_name = tokenizer_name.strip() if self._counter else None

    def compress(self, text: str) -> dict:
        if not isinstance(text, str):
            raise TypeError("MinimalCompressor expects a text string.")
        if len(text) > MAX_SEGMENT_CHARS:
            return self._result(text, "limit_exceeded")
        matches = list(_FILLER_RUN.finditer(text))
        count = sum(len(_FILLER_WORD.findall(match.group())) for match in matches)
        if count > MAX_REMOVED_FILLERS:
            return self._result(text, "limit_exceeded")
        if not matches:
            return self._counted_result(text, text, "no_eligible_fillers")
        if _ambiguous(text):
            return self._counted_result(text, text, "ambiguous_context")

        edits = []
        for match in matches:
            start, end = match.span()
            if not _meaningful_context(text, start, end):
                return self._counted_result(text, text, "ambiguous_context")
            # Only normalize horizontal whitespace directly touching this edit.
            while start > 0 and text[start - 1] in " \t":
                start -= 1
            while end < len(text) and text[end] in " \t":
                end += 1
            edits.append({
                "start": start, "end": end, "text": text[start:end],
                "replacement": " ", "rule_id": RULE_ID,
            })

        for protected in self._protected:
            for occurrence in protected.finditer(text):
                if any(occurrence.start() < edit["end"] and occurrence.end() > edit["start"] for edit in edits):
                    return self._counted_result(text, text, "protected_term")
        parts = []
        cursor = 0
        for edit in edits:
            parts.extend((text[cursor:edit["start"]], edit["replacement"]))
            cursor = edit["end"]
        parts.append(text[cursor:])
        candidate = "".join(parts)
        if not candidate.strip():
            return self._counted_result(text, text, "ambiguous_context")
        return self._counted_result(text, candidate, "compressed", edits, count)

    def _counted_result(self, raw, compact, reason, edits=None, removed_words=0):
        tokens = None
        if self._counter is not None:
            try:
                raw_count = self._counter(raw)
                compact_count = self._counter(compact) if compact != raw else raw_count
                if any(type(value) is not int or value < 0 for value in (raw_count, compact_count)):
                    raise ValueError("Token counter must return non-negative integers.")
            except Exception:
                return self._result(raw, "token_count_failed")
            if compact != raw and compact_count >= raw_count:
                compact, compact_count = raw, raw_count
                reason, edits, removed_words = "no_token_savings", None, 0
            tokens = {"tokenizer": self._tokenizer_name, "raw": raw_count,
                      "compact": compact_count, "saved": raw_count - compact_count}
        return self._result(compact, reason, edits, removed_words, tokens)

    @staticmethod
    def _result(compact, reason, edits=None, removed_words=0, tokens=None):
        return {
            "compact_text": compact,
            "compression": {
                "mode": "minimal", "changed": bool(edits),
                "removed_words": removed_words, "rules_version": RULES_VERSION,
                "reason": reason, "removed_spans": edits or [], "tokens": tokens,
            },
        }
