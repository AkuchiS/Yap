"""Vocabulary biasing + deterministic replacements — the 'remembers my words' bit.

Two complementary mechanisms, mirroring what makes Wispr feel personalized:

  * build_prompt(): turns your vocabulary list into a Whisper "initial prompt".
    Whisper biases its output toward spellings it has just seen, so listing
    "PostgreSQL", "Anthropic", "Kubernetes" nudges it to transcribe them correctly
    instead of guessing ("Java", "philanthropic", "cube an eddies").

  * apply_replacements(): whole-word, case-insensitive find/replace for the
    cases Whisper *consistently* gets wrong, e.g. {"github": "GitHub"}.
"""

from __future__ import annotations

import re
from typing import Optional


def build_prompt(vocabulary, base: Optional[str] = None) -> Optional[str]:
    words = [str(w).strip() for w in (vocabulary or []) if str(w).strip()]
    parts = []
    if base:
        parts.append(base.strip())
    if words:
        # A short, comma-separated glossary is the most reliable biasing form.
        parts.append("Glossary: " + ", ".join(words) + ".")
    return " ".join(parts) if parts else None


def normalize_case(text: str, vocabulary) -> str:
    """Force the casing of known vocabulary onto the transcript.

    Whisper writes proper nouns in lower-case ("akuchis", "dime"), so once a word
    is in your vocabulary with deliberate casing ("AkuchiS", "DIME"), rewrite any
    whole-word, case-insensitive match to that exact casing. This is what makes
    `yap vocab add AkuchiS` (or DIME) actually correct the casing every time — you
    add the word once, the way you want it, and stop retyping it.
    """
    if not text or not vocabulary:
        return text
    canon = {}
    for w in vocabulary:
        w = str(w).strip()
        if w and w.lower() != w:          # only terms with intentional casing
            canon[w.lower()] = w
    if not canon:
        return text
    return re.sub(r"[A-Za-z][A-Za-z0-9'_-]*",
                  lambda m: canon.get(m.group(0).lower(), m.group(0)), text)


def apply_replacements(text: str, replacements) -> str:
    if not text or not replacements:
        return text
    out = text
    for heard, wanted in replacements.items():
        if not heard:
            continue
        # \b doesn't hug non-word edges, so allow leading/trailing non-word chars.
        pattern = re.compile(r"(?<!\w)" + re.escape(str(heard)) + r"(?!\w)", re.IGNORECASE)
        out = pattern.sub(str(wanted), out)
    return out
