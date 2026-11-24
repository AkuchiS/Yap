"""Auto-vocabulary: learn the words you actually use.

yap watches your transcripts and counts the "learnable" tokens — acronyms
(NASA, GDPR), CamelCase (JavaScript, GitHub), and mid-sentence proper nouns
(names, places). Once you've used one `min_count` times it's promoted into your
personal glossary, which biases future recognition toward spelling it right.

Safety rails so it never degrades accuracy:
  * only repeated words get promoted (one-offs are ignored),
  * sentence-initial capitalization is skipped (that's grammar, not a name),
  * words already in your manual vocabulary are left alone,
  * the learned glossary is capped (keep the most frequent), so the Whisper
    prompt never grows unbounded.

Counts persist to <config_dir>/learned.json, so it keeps learning across runs.
"""

from __future__ import annotations

import difflib
import json
import re
from typing import Any

_STRIP = " \t\n.,;:!?\"'()[]{}"

# Cap how big a single learned phrase-fix can be, so a whole-sentence rewrite
# isn't saved as one giant find/replace. Short spans are genuine corrections
# ("post grey sequel" -> "PostgreSQL"); long ones are messy edits we ignore.
_MAX_FIX_WORDS = 6
_MAX_FIX_CHARS = 64


def _phrase(words) -> str:
    """Join a run of tokens into a clean phrase, dropping edge punctuation."""
    return " ".join(p for p in (w.strip(_STRIP) for w in words) if p)


def diff_corrections(old_text: str, new_text: str):
    """Compare what yap typed (`old_text`) with your corrected version (`new_text`)
    and return (fixes, casings):

      * fixes:   {heard_lower: wanted}  — spelling corrections → vocab replacements
      * casings: [Word, ...]            — casing-only fixes    → vocabulary entries

    Aligns on lower-cased words (so casing changes don't look like replacements),
    then learns:
      * casing-only differences (same word, different case),
      * clean 1:1 word substitutions, and
      * short *phrase* substitutions where the word count changes, e.g.
        "post grey sequel" -> "PostgreSQL" (3 words -> 1) — the single most common
        correction, which a strict 1:1 match silently dropped.
    Pure insertions/deletions and over-long (sentence-sized) edits are ignored.
    """
    old, new = (old_text or "").split(), (new_text or "").split()
    sm = difflib.SequenceMatcher(a=[w.lower() for w in old],
                                 b=[w.lower() for w in new], autojunk=False)
    fixes: dict[str, str] = {}
    casings: list[str] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":  # same words case-insensitively → look for casing-only edits
            for ow, nw in zip(old[i1:i2], new[j1:j2]):
                o, n = ow.strip(_STRIP), nw.strip(_STRIP)
                if o and n and o != n and o.lower() == n.lower() and n not in casings:
                    casings.append(n)
        elif tag == "replace":
            if (i2 - i1) == (j2 - j1):  # clean 1:1 substitutions → per-word fixes
                for ow, nw in zip(old[i1:i2], new[j1:j2]):
                    o, n = ow.strip(_STRIP), nw.strip(_STRIP)
                    if o and n and o.lower() != n.lower():
                        fixes[o.lower()] = n
            elif (i2 - i1) <= _MAX_FIX_WORDS and (j2 - j1) <= _MAX_FIX_WORDS:
                # word count changed (e.g. 3 -> 1): learn the whole short span as a
                # phrase fix; apply_replacements matches multi-word keys fine.
                heard = _phrase(old[i1:i2]).lower()
                wanted = _phrase(new[j1:j2])
                if (heard and wanted and heard != wanted.lower()
                        and len(heard) <= _MAX_FIX_CHARS):
                    fixes[heard] = wanted
    return fixes, casings

from .config import config_dir

# A token: starts with a letter, may contain letters/digits/'-_.
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9'_-]*")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_CAMEL = re.compile(r"[a-z][A-Z]")

# Don't "learn" these even if capitalized mid-sentence (common words, weekdays…).
_STOP = {
    "i", "i'm", "i'd", "i'll", "i've", "ok", "okay", "the", "a", "an", "and",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "mr", "mrs", "ms", "dr",
}


def extract_candidates(text: str) -> list[str]:
    """Proper-noun-ish tokens worth learning (preserving their casing)."""
    out: list[str] = []
    for sentence in _SENT_SPLIT.split(text or ""):
        words = list(_WORD.finditer(sentence))
        for i, m in enumerate(words):
            w = m.group(0)
            if len(w) < 2 or w.lower() in _STOP:
                continue
            if w.isupper():                         # acronym: NASA, GDPR
                out.append(w)
            elif _CAMEL.search(w):                  # CamelCase: JavaScript
                out.append(w)
            elif w[0].isupper() and i > 0:          # mid-sentence proper noun
                out.append(w)
    return out


# A learned word this similar to one of YOUR vocabulary words is almost certainly
# Whisper mishearing it ("Akutchess" for AkuchiS, "Jazz" for Jaz). Learning it
# would feed the wrong spelling back into the prompt and lock the mistake in.
_NEAR_MISS = 0.72


def _near_miss(word: str, manual: "set[str]") -> bool:
    w = word.lower()
    return any(w != m and difflib.SequenceMatcher(None, w, m).ratio() >= _NEAR_MISS
               for m in manual)


class VocabLearner:
    def __init__(self, cfg: dict[str, Any]):
        lc = cfg.get("learning", {}) or {}
        self.enabled = bool(lc.get("enabled", True))
        self.min_count = int(lc.get("min_count", 3))
        self.max_words = int(lc.get("max_words", 80))
        self.path = config_dir() / "learned.json"
        # How often each candidate also turns up in plain lowercase. A word you say
        # lowercase as often as capitalised ("more", "new", "everything") is an
        # ordinary word Whisper happened to capitalise — not a name. Kept in its own
        # file so older yap versions can still read learned.json.
        self.lower_path = config_dir() / "learned_lower.json"
        self._manual = {str(w).lower() for w in cfg.get("vocabulary", []) if str(w).strip()}
        self._counts: dict[str, int] = self._load(self.path)
        self._lower: dict[str, int] = self._load(self.lower_path)
        self._promoted = self._compute_promoted()

    @staticmethod
    def _load(path) -> dict[str, int]:
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                return {str(k): int(v) for k, v in data.items()}
        except Exception:
            pass
        return {}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._counts, indent=2), encoding="utf-8")
            self.lower_path.write_text(json.dumps(self._lower, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _eligible(self, w: str, c: int) -> bool:
        lw = w.lower()
        return (c >= self.min_count
                and lw not in self._manual
                # names are almost never said in lowercase (Hermes 124:0, Mac 104:0);
                # ordinary words are, a lot (More 70:40). Allow a little noise.
                and self._lower.get(lw, 0) * 4 < c
                and not _near_miss(w, self._manual))

    def _compute_promoted(self) -> list[str]:
        eligible = [(w, c) for w, c in self._counts.items() if self._eligible(w, c)]
        # most frequent first, capped
        eligible.sort(key=lambda wc: (-wc[1], wc[0]))
        return [w for w, _ in eligible[: self.max_words]]

    def observe(self, text: str) -> list[str]:
        """Count words from a transcript. Return any words newly promoted."""
        if not self.enabled or not text.strip():
            return []
        before = set(self._promoted)
        for w in extract_candidates(text):
            if w.lower() in self._manual:
                continue
            self._counts[w] = self._counts.get(w, 0) + 1
        known = {k.lower() for k in self._counts}
        for m in _WORD.finditer(text):
            tok = m.group(0)
            if tok.islower() and tok in known:   # only track words we're weighing
                self._lower[tok] = self._lower.get(tok, 0) + 1
        self._promoted = self._compute_promoted()
        self._save()
        return [w for w in self._promoted if w not in before]

    def casing_words(self) -> list[str]:
        """Learned terms safe to force-case everywhere: CamelCase only (GitHub,
        iPhone). Plain capitalised or all-caps words are not ("More", "IT")."""
        return [w for w in self._promoted if _CAMEL.search(w)]

    def words(self) -> list[str]:
        """The current learned glossary (promoted words)."""
        return list(self._promoted)

    def forget(self, word: str) -> bool:
        """Drop a learned word and stop it being relearned immediately."""
        hit = False
        for key in [k for k in self._counts if k.lower() == word.lower()]:
            del self._counts[key]
            hit = True
        if hit:
            self._promoted = self._compute_promoted()
            self._save()
        return hit
