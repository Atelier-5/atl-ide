# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5, Atelier-5
"""
i18n.py — atl-ide in English, French and German (from digitalhome-twin-edge-WormBed-5).

The English text is the key (as with gettext): code says `_("The simulation is not running.")`
and the catalogs i18n/fr.json and i18n/de.json map each English text to its
translation. A text with values names them in braces, `_("{n} claps", n=3)`; a
translation keeps the same names. A text without a translation stays English.

The language is the person's choice on the page (a cookie, `lang`), else what
the browser asks for, else English. It is set per request (`use`), so code
deeper down only calls `_()`.

The page's own texts are in the same catalogs: the page gets the one for its
language embedded (window.I18N_BOOT) and from GET /api/i18n, and static/app.js
translates with the same rule. Young people are addressed as "tu" / "du".

Standard library only.
"""

from __future__ import annotations

import contextvars
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

LANGS = ("en", "fr", "de")
NAMES = {"en": "English", "fr": "Français", "de": "Deutsch"}
FOLDER = Path(__file__).resolve().parent / "i18n"
_lang: contextvars.ContextVar[str] = contextvars.ContextVar("lang", default="en")


@lru_cache(maxsize=None)
def catalog(lang: str) -> Dict[str, str]:
    """English text -> its translation, for `lang` (empty for English or a missing file)."""
    if lang == "en":
        return {}
    try:
        return json.loads((FOLDER / f"{lang}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def use(lang: Optional[str]) -> str:
    """Speak `lang` from here on (in this request or thread); an unknown one is English."""
    lang = lang if lang in LANGS else "en"
    _lang.set(lang)
    return lang


def current() -> str:
    return _lang.get()


def _(text: str, lang: Optional[str] = None, /, **values: Any) -> str:
    """`text` in the current language (or `lang`), with `values` filled in."""
    if not text:
        return text
    out = catalog(lang or _lang.get()).get(text, text)
    if values:
        try:
            return out.format(**values)
        except (KeyError, IndexError, ValueError):     # a broken translation: say it in English rather than fail
            return text.format(**values)
    return out


def pick(cookie: Optional[str], accept: Optional[str]) -> str:
    """The language for a request: the person's choice (cookie), else the browser's first one we speak."""
    if cookie in LANGS:
        return cookie
    for part in (accept or "").split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in LANGS:
            return code
    return "en"
