from __future__ import annotations

import html
import re
import unicodedata
from urllib.parse import unquote, urlparse


NOISE_PATTERNS = (
    r"\bgameplay\b",
    r"\bwalkthrough\b",
    r"\bfull\s+game\b",
    r"\bplay\s+online\b",
    r"\bfree\s+online\s+game\b",
    r"\bonline\s+game\b",
    r"\btrailer\b",
    r"\bpart\s+\d+\b",
    r"\bepisode\s+\d+\b",
    r"\b(?:id|game)[-_ ]?\d{4,}\b",
)
GENERIC_TERMS = {
    "game", "games", "online game", "free game", "new game", "play game",
    "arcade game", "browser game", "mobile game", "html5 game",
}


def title_from_url(url: str) -> str:
    path = unquote(urlparse(url).path).rstrip("/")
    slug = path.rsplit("/", 1)[-1]
    slug = re.sub(r"\.(?:html?|php|aspx?)$", "", slug, flags=re.I)
    return re.sub(r"[-_]+", " ", slug)


def normalize_game_title(raw_title: str, language: str = "en") -> tuple[str, str] | None:
    value = unicodedata.normalize("NFKC", html.unescape(unquote(raw_title))).strip()
    value = re.sub(r"[|–—:]+\s*(?:crazygames|poki|steam|itch\.io)\s*$", "", value, flags=re.I)
    value = re.sub(r"\[[^\]]{0,40}\]|\([^)]*(?:gameplay|walkthrough|trailer|\d{4})[^)]*\)", " ", value, flags=re.I)
    for pattern in NOISE_PATTERNS:
        value = re.sub(pattern, " ", value, flags=re.I)
    value = re.sub(r"\s+", " ", value).strip(" -_|:.,")
    normalized_key = re.sub(r"[^\w\u4e00-\u9fff]+", " ", value.casefold(), flags=re.UNICODE).strip()
    normalized_key = re.sub(r"\s+", " ", normalized_key)

    if not normalized_key or normalized_key in GENERIC_TERMS:
        return None
    if len(value) < 2 or len(value) > 100 or len(normalized_key.split()) > 12:
        return None
    if normalized_key.isdigit() or re.fullmatch(r"\d{4,}", normalized_key):
        return None
    if language.lower().startswith("en"):
        letters = sum(character.isascii() and character.isalpha() for character in value)
        alphabetic = sum(character.isalpha() for character in value)
        if alphabetic and letters / alphabetic < 0.65:
            return None
    return value, normalized_key

