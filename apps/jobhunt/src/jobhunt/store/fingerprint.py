"""Posting fingerprints: the same job from different sources gets the same key. See spec 04,
"Postings". Exact matching on normalized text; fuzzy matching comes with the matcher spec.
"""

import hashlib
import re
import unicodedata

# Letters that Unicode decomposition doesn't reduce to ASCII (đ is not "d" + a mark).
_UNDECOMPOSABLE = str.maketrans({"đ": "d", "Đ": "d", "ø": "o", "Ø": "o", "ł": "l", "Ł": "l"})
_NON_WORD = re.compile(r"[\W_]+")

# Vietnamese legal-form phrases, removed wherever they appear as whole words. Longest first, so
# "cong ty co phan" goes before "co phan" and "phan" in "phan mem" (software) is kept.
_LEGAL_PHRASES = (
    "cong ty co phan",
    "cong ty tnhh",
    "cong ty",
    "co phan",
    "tnhh",
    "mot thanh vien",
    "mtv",
)
# Legal-form words removed from the end of a company name.
_LEGAL_SUFFIXES = frozenset(
    {"co", "ltd", "limited", "company", "jsc", "inc", "llc", "corp", "corporation", "pte",
     "gmbh", "plc"}
)  # fmt: skip


def fold(text: str) -> str:
    """Lowercase words without diacritics; punctuation becomes spaces, whitespace collapses."""
    decomposed = unicodedata.normalize("NFKD", text.translate(_UNDECOMPOSABLE))
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(_NON_WORD.sub(" ", stripped.casefold()).split())


def normalize_company(name: str) -> str:
    """Company name without legal forms or LinkedIn's "| Part of ..." suffix."""
    folded = fold(name.split("|", 1)[0])
    text = f" {folded} "
    for phrase in _LEGAL_PHRASES:
        while f" {phrase} " in text:
            text = text.replace(f" {phrase} ", " ")
    words = text.split()
    while len(words) > 1 and words[-1] in _LEGAL_SUFFIXES:
        words.pop()
    return " ".join(words) or folded


def normalize_title(title: str) -> str:
    return fold(title)


def fingerprint(company: str, title: str) -> str:
    """SHA-256 of `normalize_company | normalize_title`."""
    key = f"{normalize_company(company)}|{normalize_title(title)}"
    return hashlib.sha256(key.encode()).hexdigest()
