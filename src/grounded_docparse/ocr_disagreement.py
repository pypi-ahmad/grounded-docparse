"""Compares two OCR readings of the same region for how much they actually
disagree, at word-token granularity rather than raw character diff.

Next: see callers in quality.py for how this feeds OCR disagreement/quality
signals.
"""

from __future__ import annotations

import re
import unicodedata


def _tokens(value: str) -> list[str]:
    # NFKC folds visually-equivalent forms (e.g. full-width vs half-width,
    # combining characters) to the same representation before comparing, so
    # two OCR engines' differing Unicode normalization doesn't look like a
    # real disagreement. `[^\W_]+` splits into alphanumeric tokens
    # (word characters minus underscore).
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.findall(r"[^\W_]+", normalized, flags=re.UNICODE)


def token_edit_similarity(left: str, right: str) -> float:
    """Return normalized Levenshtein similarity over OCR word tokens."""

    a, b = _tokens(left), _tokens(right)
    if not a and not b:
        return 1.0
    # Classic Levenshtein edit-distance DP, space-optimized to one row
    # (`previous`/`current`) instead of a full len(a) x len(b) matrix.
    previous = list(range(len(b) + 1))
    for row, left_token in enumerate(a, 1):
        current = [row]
        for column, right_token in enumerate(b, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (left_token != right_token),
                )
            )
        previous = current
    return 1 - previous[-1] / max(len(a), len(b), 1)
