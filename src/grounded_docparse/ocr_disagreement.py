from __future__ import annotations

import re
import unicodedata


def _tokens(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.findall(r"[^\W_]+", normalized, flags=re.UNICODE)


def token_edit_similarity(left: str, right: str) -> float:
    """Return normalized Levenshtein similarity over OCR word tokens."""

    a, b = _tokens(left), _tokens(right)
    if not a and not b:
        return 1.0
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
