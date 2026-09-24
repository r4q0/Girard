"""The line filter: plain code, no model, runs on every transcribed chunk before anything else.

Rules (in order):
1. Drop lines that are only backchannel ("yeah", "ok", "mm-hmm", ...).
2. Strip filler words from a fixed list ("like" and "actually" always go).
3. Collapse stutters ("we we we need" -> "we need").
4. Hold fragments under 3 words and join them to the next chunk.
5. Lines with a signal (question, no/not, a number or money, a company name) skip rules 1 and 4
   and go out at once.
6. Repeats are kept: a repeated point is signal for the advice model.
Before all of that, misheard company names are fixed against the known names ("Zap here" -> "Zapier").
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

from rapidfuzz import fuzz

BACKCHANNEL_PHRASES = ["mm hmm", "uh huh", "got it", "i see", "fair enough", "makes sense", "all right"]
BACKCHANNEL_WORDS = {
    "yeah", "yes", "yep", "yup", "ok", "okay", "right", "sure", "mm", "mhm", "mmhmm", "hmm", "uh", "um",
    "oh", "ah", "alright", "cool", "great", "fine", "exactly", "totally", "absolutely", "true", "nice",
    "and", "so", "well", "_bc",
}
FILLER_PHRASES = ["you know", "i mean", "sort of", "kind of"]
FILLER_WORDS = {"um", "uh", "uhm", "umm", "erm", "er", "ah", "hmm", "mm", "like", "actually", "basically"}
NEGATIONS = {"no", "not", "nope", "never", "don't", "dont", "can't", "cant", "won't", "wont", "isn't",
             "doesn't", "didn't", "wouldn't", "shouldn't", "aren't", "wasn't"}
NUMBER_WORDS = {
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
    "fifteen", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety", "hundred",
    "thousand", "million", "billion", "percent", "euro", "euros", "dollar", "dollars", "k",
}
MIN_WORDS = 3
HOLD_SECONDS = 3.0  # a held fragment with no follow-up goes out on its own after this
NAME_SCORE = 88        # one heard word vs a name
NAME_SCORE_SPLIT = 75  # a name heard as 2-3 words ("Zap here" -> Zapier) is a strong hint on its own
# Words that often start a short line and are not names.
COMMON_STARTERS = {"Maybe", "Yes", "Okay", "Sure", "So", "Well", "Thanks", "Thank", "Great", "Right", "Exactly",
                   "Perhaps", "Probably", "Definitely", "Absolutely", "Hello", "Hi", "Sorry", "Good", "Fine",
                   "Cool", "Really", "Interesting", "Wow", "Hmm", "Oh", "Yeah", "No", "Not", "What", "Why",
                   "How", "When", "Where", "Who", "The", "That", "This", "It", "We", "You", "They", "And", "But"}


@dataclass
class Result:
    text: str   # what goes to the advice model ("" = nothing)
    rule: str   # which rule decided: signal, full, joined, held, dropped, empty


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


class LineFilter:
    def __init__(self, names: list[str] | None = None):
        self.names: list[str] = []
        self.set_names(names or [])
        self.held = ""
        self.held_at = 0.0

    def set_names(self, names: list[str]) -> None:
        self.names = sorted({n.strip() for n in names if len(n.strip()) >= 3})

    # --- name fix -----------------------------------------------------------------------------
    def fix_names(self, text: str) -> str:
        """Replace a 1-3 word window that sounds like a known company name with that name."""
        if not self.names:
            return text
        tokens = text.split()
        out: list[str] = []
        i = 0
        while i < len(tokens):
            best = None  # (score, -size, size, replacement): highest score wins, then the shorter window
            for size in (1, 2, 3):
                window = tokens[i:i + size]
                if len(window) < size:
                    continue
                trail = re.search(r"[^\w']+$", window[-1])
                joined = re.sub(r"[^\w]", "", "".join(window)).lower()
                if len(joined) < 4:
                    continue
                need = NAME_SCORE if size == 1 else NAME_SCORE_SPLIT
                for name in self.names:
                    key = re.sub(r"[^\w]", "", name).lower()
                    if abs(len(key) - len(joined)) > 3:
                        continue
                    score = fuzz.ratio(joined, key)
                    if score >= need and size > 1:
                        # Do not swallow a neighbouring word: the match must need every word in the window.
                        inner = [re.sub(r"[^\w]", "", "".join(w)).lower() for w in (window[1:], window[:-1])]
                        if any(fuzz.ratio(x, key) >= score for x in inner if len(x) >= 4):
                            continue
                    if score >= need:
                        cand = (score, -size, size, name + (trail.group(0) if trail else ""))
                        if best is None or cand[:2] > best[:2]:
                            best = cand
            if best:
                out.append(best[3])
                i += best[2]
            else:
                out.append(tokens[i])
                i += 1
        return " ".join(out)

    # --- rules --------------------------------------------------------------------------------
    def has_signal(self, text: str) -> bool:
        if "?" in text:
            return True
        words = set(_words(text))
        if words & NEGATIONS:
            return True
        if re.search(r"\d|[€$£]", text) or words & NUMBER_WORDS:
            return True
        lowered = text.lower()
        if any(n.lower() in lowered for n in self.names):
            return True
        # A capitalised word that is not "I" is probably a name. The first word only counts when it
        # has an inner capital (HubSpot) or the line is very short and it is not a common starter.
        tokens = [t.strip(".,!?;:\"'") for t in text.split()]
        if not tokens:
            return False
        first = tokens[0]
        short_name = (len(tokens) <= 2 and re.match(r"[A-Z][a-z]", first) and first not in COMMON_STARTERS
                      and re.sub(r"[^a-z]", "", first.lower()) not in BACKCHANNEL_WORDS)
        if re.search(r"[a-z][A-Z]", first) or short_name:
            return True
        raw = text.split()
        for prev, tok in zip(raw, tokens[1:]):
            if prev.endswith((".", "!", "?")):
                continue  # capitalised because a new sentence starts, not because it is a name
            if (re.match(r"[A-Z][a-z]", tok) and tok not in COMMON_STARTERS
                    and tok not in {"I", "I'm", "I'd", "I'll", "I've"}):
                return True
        return False

    @staticmethod
    def is_backchannel(text: str) -> bool:
        t = " ".join(_words(text))
        for p in BACKCHANNEL_PHRASES:
            t = re.sub(rf"\b{p}\b", "_bc", t)
        words = t.split()
        return not words or all(w in BACKCHANNEL_WORDS for w in words)

    @staticmethod
    def strip_fillers(text: str) -> str:
        # A filler set off by commas takes one comma with it: "who, you know, spend" -> "who spend".
        for p in FILLER_PHRASES:
            text = re.sub(rf"(?i),?\s*\b{p}\b,?", " ", text)
        kept: list[str] = []
        for t in text.split():
            if re.sub(r"[^\w']", "", t).lower() in FILLER_WORDS:
                if kept and kept[-1].endswith(","):
                    kept[-1] = kept[-1][:-1]
                continue
            kept.append(t)
        return " ".join(kept)

    @staticmethod
    def collapse_stutters(text: str) -> str:
        out: list[str] = []
        for t in text.split():
            if out and re.sub(r"[^\w']", "", t).lower() == re.sub(r"[^\w']", "", out[-1]).lower():
                out[-1] = t  # keep the last copy, it carries the punctuation
                continue
            out.append(t)
        return " ".join(out)

    @staticmethod
    def tidy(text: str) -> str:
        text = re.sub(r"\s+([,.!?])", r"\1", text)
        text = re.sub(r"^[,.\s]+", "", text)
        text = re.sub(r",\s*([.!?])", r"\1", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:1].upper() + text[1:] if text else text

    def process(self, raw: str, now: float | None = None) -> Result:
        now = time.monotonic() if now is None else now
        text = self.fix_names(raw.strip())
        signal = self.has_signal(text)
        if not signal and self.is_backchannel(text):
            return Result("", "dropped")
        text = self.tidy(self.collapse_stutters(self.strip_fillers(text)))
        if self.held:
            text = self.tidy(f"{self.held} {text}")
            self.held = ""
            joined = True
        else:
            joined = False
        if not text:
            return Result("", "empty")
        if signal:
            return Result(text, "signal")
        if len(_words(text)) < MIN_WORDS:
            self.held, self.held_at = text, now
            return Result("", "held")
        return Result(text, "joined" if joined else "full")

    def flush_due(self, now: float | None = None) -> Result | None:
        """A held fragment that got no follow-up within HOLD_SECONDS goes out alone."""
        now = time.monotonic() if now is None else now
        if self.held and now - self.held_at >= HOLD_SECONDS:
            text, self.held = self.held, ""
            return Result(text, "flushed")
        return None
