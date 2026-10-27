"""Languages of the Portal's own text: English is the source, other
languages are catalogs that override it (docs/plans/i18n.md in harness-kit).

Catalogs: app/static/i18n/<lang>.json, i18next JSON v4 (flat keys,
`{{var}}` placeholders, `_one` / `_other` plural suffixes). The page reads
the same files; `t()` here serves the server's replies (HTTPException
`detail`, the login DM, the verify page, /help).

The language of a request is chosen once per request (LanguageMiddleware
in main.py) and kept in a context variable: `?lang=` wins, then the `lang`
cookie, then the person's users.yaml `language` (require_user sets it when
the request carried neither), then Accept-Language, else English."""
from __future__ import annotations

import json
import re
from contextvars import ContextVar
from pathlib import Path

CATALOG_DIR = Path(__file__).resolve().parent / "static" / "i18n"
DEFAULT = "en"
SUPPORTED = ("en", "de")
COOKIE = "lang"
COOKIE_MAX_AGE = 365 * 24 * 3600

_catalogs: dict[str, dict[str, str]] = {}
_current: ContextVar[str] = ContextVar("portal_lang", default=DEFAULT)
_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


def load() -> None:
    for lang in SUPPORTED:
        path = CATALOG_DIR / f"{lang}.json"
        _catalogs[lang] = json.loads(path.read_text()) if path.exists() else {}


load()


def normalize(code: object) -> str | None:
    """'de-CH' -> 'de'; anything not supported -> None."""
    if not code:
        return None
    short = str(code).strip().lower().replace("_", "-").split("-")[0]
    return short if short in SUPPORTED else None


def from_accept_language(header: str | None) -> str | None:
    if not header:
        return None
    ranked = []
    for i, part in enumerate(header.split(",")):
        tag, _, rest = part.strip().partition(";")
        q = 1.0
        if rest.strip().startswith("q="):
            try:
                q = float(rest.strip()[2:])
            except ValueError:
                q = 0.0
        if tag and q > 0:
            ranked.append((-q, i, tag))
    for _, _, tag in sorted(ranked):
        lang = normalize(tag)
        if lang:
            return lang
    return None


def pick(query: object = None, cookie: object = None, user_lang: object = None, accept: str | None = None) -> str:
    for candidate in (normalize(query), normalize(cookie), normalize(user_lang), from_accept_language(accept)):
        if candidate:
            return candidate
    return DEFAULT


def current() -> str:
    return _current.get()


def use(lang: object) -> None:
    _current.set(normalize(lang) or DEFAULT)


def t(key: str, lang: str | None = None, **params: object) -> str:
    """The text for `key` in `lang` (default: the request's language),
    English when the language has no entry, the key itself when nobody has."""
    lang = normalize(lang) or _current.get()
    text = _catalogs.get(lang, {}).get(key)
    if text is None:
        text = _catalogs.get(DEFAULT, {}).get(key, key)
    if params:
        text = _PLACEHOLDER.sub(lambda m: str(params.get(m.group(1), m.group(0))), text)
    return text
