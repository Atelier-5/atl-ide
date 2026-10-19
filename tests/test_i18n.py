# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Atelier-5
"""The page in English, French and German: every catalog complete, the page's texts all in it."""

import json
import re
from pathlib import Path

from atl import i18n

ROOT = Path(__file__).resolve().parents[1] / "atl"


def catalogs():
    return {lang: json.loads((ROOT / "i18n" / f"{lang}.json").read_text(encoding="utf-8")) for lang in ("fr", "de")}


def test_english_first_then_french_and_german():
    assert i18n.LANGS == ("en", "fr", "de")


def test_french_and_german_have_the_same_texts():
    c = catalogs()
    assert set(c["fr"]) == set(c["de"]), set(c["fr"]) ^ set(c["de"])
    for lang, cat in c.items():
        assert all(v.strip() for v in cat.values()), f"{lang}: an empty translation"


def test_every_visible_text_of_the_page_is_translated():
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    html = re.sub(r"{%.*?%}|{{.*?}}|{#.*?#}|<!--.*?-->|<svg.*?</svg>|<script.*?</script>", " ", html, flags=re.S)
    texts = {t.strip() for t in re.findall(r">([^<>]+)<", html)}
    texts |= set(re.findall(r'(?:title|aria-label|alt|placeholder)="([^"{]+)"', html))
    texts = {re.sub(r"\s+", " ", t) for t in texts if re.search(r"[A-Za-z]{2}", t)}
    texts -= {"atl-ide", "-ide", "atl", "E-stop"} - set(catalogs()["fr"])        # names stay
    missing = sorted(t for t in texts if t not in catalogs()["fr"])
    assert not missing, f"not in i18n/fr.json and de.json: {missing}"


def test_the_language_follows_the_cookie_then_the_browser():
    assert i18n.pick("de", "fr-FR,fr;q=0.9") == "de"
    assert i18n.pick(None, "fr-FR,fr;q=0.9") == "fr"
    assert i18n.pick(None, "es") == "en"
