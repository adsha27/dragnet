"""
ATS-safe text normalization.
Call normalize() on any string before sending to ATS form fields.
Legacy ATS parsers reject em-dashes, smart quotes, and zero-width chars.
"""

_REPLACEMENTS = [
    ("–", "-"),   # en-dash
    ("—", "-"),   # em-dash
    ("‘", "'"),   # left single quote
    ("’", "'"),   # right single quote
    ("“", '"'),   # left double quote
    ("”", '"'),   # right double quote
    ("…", "..."), # ellipsis
    ("•", "-"),   # bullet
    (" ", " "),   # non-breaking space
    ("​", ""),    # zero-width space
    ("‌", ""),    # zero-width non-joiner
    ("‍", ""),    # zero-width joiner
    ("﻿", ""),    # BOM
]


def normalize(text: str) -> str:
    for char, replacement in _REPLACEMENTS:
        text = text.replace(char, replacement)
    return text
