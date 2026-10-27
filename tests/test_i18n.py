"""Languages: English is the source and the default; every key the page or
the server uses exists in en.json; de.json covers every key; the request's
language follows ?lang, the cookie, the person's users.yaml entry, then
Accept-Language."""
from __future__ import annotations

import json
import re
from pathlib import Path

from tests.conftest import client_as

from app import i18n

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "app" / "static" / "index.html").read_text()
SERVER = "".join(p.read_text() for p in (ROOT / "app").rglob("*.py"))
EN = json.loads((ROOT / "app" / "static" / "i18n" / "en.json").read_text())
DE = json.loads((ROOT / "app" / "static" / "i18n" / "de.json").read_text())

KEY = r"""\bt\(\s*['"]([a-z0-9_.]+)['"]"""


def used_keys() -> set[str]:
    """Keys the page or the server reference: t('…') calls, data-i18n
    attributes, and key strings kept in data tables (COLS, OKR_FIELDS)."""
    keys = set(re.findall(KEY, PAGE)) | set(re.findall(r'data-i18n="([a-z0-9_.]+)"', PAGE)) | set(re.findall(KEY, SERVER))
    keys |= {k for k in re.findall(r"""['"]([a-z]+\.[a-z0-9_.]+)['"]""", PAGE) if k in EN}
    return {k for k in keys if not k.endswith(".")}      # dynamic prefixes (status., sh.role.) are checked below


def test_every_used_key_is_in_the_english_catalog():
    missing = sorted(k for k in used_keys() if k not in EN and f"{k}_one" not in EN)
    assert not missing, missing


def test_plural_keys_have_both_forms():
    for key in EN:
        if key.endswith("_one"):
            assert key[:-4] + "_other" in EN


def test_dynamic_prefixes_are_covered():
    for role in ("owner", "reviewer", "watcher"):
        assert f"sh.role.{role}" in EN
    for status in ("draft", "active", "closed", "on_track", "at_risk", "off_track", "done", "ok", "warn", "crit",
                   "unknown", "approved", "archived", "none"):
        assert f"status.{status}" in EN


def test_german_covers_every_english_key_and_nothing_else():
    assert set(DE) == set(EN), {"missing": sorted(set(EN) - set(DE)), "extra": sorted(set(DE) - set(EN))}
    assert all(v.strip() for v in DE.values())
    for key, en in EN.items():   # the same placeholders in both languages
        assert set(re.findall(r"\{\{(\w+)\}\}", en)) == set(re.findall(r"\{\{(\w+)\}\}", DE[key])), key


def test_unused_catalog_keys_are_removed():
    used = used_keys()
    used |= {k + suffix for k in used for suffix in ("_one", "_other")}
    dynamic = {k for k in EN if k.startswith(("status.", "sh.role."))}
    unused = sorted(k for k in EN if k not in used and k not in dynamic)
    assert not unused, unused


def test_t_falls_back_to_english_then_to_the_key():
    assert i18n.t("err.not_found", lang="de") == "Nicht gefunden"
    assert i18n.t("err.not_found", lang="fr") == "Not found"
    assert i18n.t("no.such.key", lang="de") == "no.such.key"
    assert i18n.t("err.claim_not_ready", lang="en", status="review").startswith("Only Ready tasks can be claimed; this task is review.")


def test_pick_order():
    assert i18n.pick() == "en"
    assert i18n.pick(accept="de-CH,de;q=0.9,en;q=0.8") == "de"
    assert i18n.pick(accept="fr-CH,fr;q=0.9") == "en"
    assert i18n.pick(accept="fr,de;q=0.5") == "de"
    assert i18n.pick(user_lang="de", accept="en") == "de"
    assert i18n.pick(cookie="en", user_lang="de") == "en"
    assert i18n.pick(query="de", cookie="en") == "de"
    assert i18n.pick(query="xx", cookie="EN") == "en"


def test_server_replies_follow_the_request_language():
    c = client_as(None)
    assert c.get("/api/board").json()["detail"] == "Not logged in"
    assert c.get("/api/board", headers={"Accept-Language": "de-CH"}).json()["detail"] == "Nicht angemeldet"
    assert c.get("/api/board?lang=de").json()["detail"] == "Nicht angemeldet"
    c.cookies.set("lang", "de")
    assert c.get("/api/board").json()["detail"] == "Nicht angemeldet"
    assert c.get("/api/board?lang=en").json()["detail"] == "Not logged in"


def test_a_persons_language_applies_once_logged_in(calls):
    mia = client_as("@mia:hs.test")          # users.yaml: language: de
    r = mia.get("/api/profile")
    assert r.json()["language"] == "de" and r.json()["languages"] == ["en", "de"]
    assert mia.get("/api/tasks/t_missing").json()["detail"] == "Nicht gefunden"
    # the browser's explicit choice wins over the users.yaml entry
    assert mia.get("/api/tasks/t_missing?lang=en").json()["detail"] == "Not found"
    tim = client_as("@tim:hs.test")          # no language set: English unless the browser says otherwise
    assert tim.get("/api/tasks/t_missing").json()["detail"] == "Not found"
    assert tim.get("/api/profile").json()["language"] is None
    assert tim.get("/api/tasks/t_missing", headers={"Accept-Language": "de"}).json()["detail"] == "Nicht gefunden"


def test_help_has_both_languages_and_a_switch():
    c = client_as(None)
    en = c.get("/help")
    assert en.status_code == 200 and '<html lang="en">' in en.text and "Guide for the team" in en.text
    assert 'href="/help?lang=de">Deutsch</a>' in en.text
    de = c.get("/help?lang=de")
    assert '<html lang="de">' in de.text and "Anleitung für das Team" in de.text and 'id="was-ist-neu"' in de.text
    assert "lang=de" in de.headers.get("set-cookie", "")
    assert '<html lang="de">' in client_as(None).get("/help", headers={"Accept-Language": "de"}).text


def test_people_language_is_validated_and_passed_on(calls, monkeypatch):
    from app import people
    seen = []
    monkeypatch.setattr(people, "update", lambda *a, **k: (seen.append(a), people.Result(True))[1])
    monkeypatch.setattr(people, "set_language", lambda *a: (seen.append(("lang",) + a), people.Result(True))[1])
    owen = client_as("@own:hs.test")
    assert owen.put("/api/people/tim", json={"tenants": ["tech"], "approve": [], "language": "xx"}).status_code == 422
    assert owen.put("/api/people/tim", json={"tenants": ["tech"], "approve": [], "language": "DE"}).status_code == 200
    assert seen[-1] == ("tim", ["tech"], [], "de")
    assert owen.post("/api/profile/language", json={"language": "de"}).status_code == 200
    assert seen[-1] == ("lang", "own", "de")
    assert owen.post("/api/profile/language", json={"language": None}).status_code == 200
    assert seen[-1] == ("lang", "own", None)


def test_german_guide_mirrors_the_english_structure():
    en = (ROOT / "docs" / "user-guide.md").read_text()
    de = (ROOT / "docs" / "user-guide.de.md").read_text()
    assert len(re.findall(r"^## ", en, re.M)) == len(re.findall(r"^## ", de, re.M))
    assert len(re.findall(r"^### ", en, re.M)) == len(re.findall(r"^### ", de, re.M))
    assert "{{HOST}}" in de and "[TOC]" in de
    assert "/whoami" in de and "/retry" in de     # slash commands stay as they are


def test_catalogs_are_served():
    assert client_as(None).get("/static/i18n/de.json").json()["nav.help"] == "Hilfe"
