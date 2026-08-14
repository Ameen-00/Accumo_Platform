"""Name and invoice normalisation — jurisdiction-neutral.

These two functions decide whether duplicate rules work.
Gulf legal suffixes (FZE, FZCO, EST) live here from day one so
India → Dubai is a deploy, not a rewrite.
"""

from __future__ import annotations

import re
import unicodedata

_LEGAL = re.compile(
    r"\b("
    r"PVT|PRIVATE|LTD|LIMITED|LLC|LLP|INC|CO|COMPANY|"
    r"TRADING|TRDG|TRADERS|TRADER|"
    r"EST|ESTABLISHMENT|FZE|FZCO|FZ-LLC|PJSC|LLC-FZ"
    r")\b"
)
_NON_ALNUM = re.compile(r"[^A-Z0-9]")
_PADDED_ZEROS = re.compile(r"(?<=[A-Z])0+(?=\d)")
_NON_NAME = re.compile(r"[^A-Z0-9]+")


def strip_accents(value: str) -> str:
    nfkd = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def normalise_name(raw: str | None) -> str:
    if not raw:
        return ""
    s = strip_accents(raw).upper()
    s = _LEGAL.sub(" ", s)
    s = _NON_NAME.sub(" ", s)
    return " ".join(s.split())


def normalise_invoice(raw: str | None) -> str:
    if not raw:
        return ""
    s = raw.upper()
    s = _NON_ALNUM.sub("", s)
    s = _PADDED_ZEROS.sub("", s)
    return s


def normalise_tax_id(raw: str | None) -> str:
    if not raw:
        return ""
    return re.sub(r"[^A-Z0-9]", "", raw.upper())


def digits_only(raw: str | None) -> str:
    if not raw:
        return ""
    return re.sub(r"\D", "", raw)
