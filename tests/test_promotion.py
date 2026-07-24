"""Catalog auto-promotion tests — no network; a fake discovery+trends stand in.

Never touches the real solesight/catalog.json: every test points `run()` at
a throwaway JSON file via the `catalog_path` param.
"""
from __future__ import annotations

import json

import pytest

from solesight.insights import discovery, promotion


def _seed_catalog(tmp_path, entries=None):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(entries or [], indent=1))
    return path


def test_below_mention_threshold_is_not_promoted(tmp_path, monkeypatch):
    path = _seed_catalog(tmp_path)
    monkeypatch.setattr(discovery, "run", lambda limit=10: [
        {"name": "Nike Air Huarache Since 91", "mentions": 2, "outlets": 2}])
    added = promotion.run(catalog_path=path, confirm=lambda term: 40.0)
    assert added == []
    assert json.loads(path.read_text()) == []


def test_below_outlet_threshold_is_not_promoted(tmp_path, monkeypatch):
    path = _seed_catalog(tmp_path)
    monkeypatch.setattr(discovery, "run", lambda limit=10: [
        {"name": "Nike Air Huarache Since 91", "mentions": 5, "outlets": 1}])
    added = promotion.run(catalog_path=path, confirm=lambda term: 40.0)
    assert added == []


def test_failed_trends_confirmation_blocks_promotion(tmp_path, monkeypatch):
    """Enough press mentions, but no real search interest — don't add it."""
    path = _seed_catalog(tmp_path)
    monkeypatch.setattr(discovery, "run", lambda limit=10: [
        {"name": "Nike Air Huarache Since 91", "mentions": 5, "outlets": 3}])
    added = promotion.run(catalog_path=path, confirm=lambda term: None)
    assert added == []
    assert json.loads(path.read_text()) == []


def test_candidate_clearing_both_bars_gets_promoted(tmp_path, monkeypatch):
    path = _seed_catalog(tmp_path)
    monkeypatch.setattr(discovery, "run", lambda limit=10: [
        {"name": "Nike Air Huarache Since 91", "mentions": 4, "outlets": 3}])
    added = promotion.run(catalog_path=path, confirm=lambda term: 22.5)

    assert len(added) == 1
    entry = added[0]
    assert entry["slug"] == "nike-air-huarache-since-91"
    assert entry["name"] == "Nike Air Huarache Since 91"
    assert entry["brand"] == "Nike"
    assert entry["category"] == "lifestyle"
    assert entry["trends_term"] == "Nike Air Huarache Since 91"
    assert entry["keywords"] == ["nike air huarache since 91"]
    # Never fabricate what we don't actually know.
    assert "retail" not in entry
    assert "image" not in entry

    on_disk = json.loads(path.read_text())
    assert on_disk == [entry]


def test_brand_category_defaults():
    assert promotion._make_entry(
        {"name": "Air Jordan 9 Retro Racer Blue"})["category"] == "basketball"
    assert promotion._make_entry(
        {"name": "New Balance 1080v13"})["category"] == "running"
    assert promotion._make_entry(
        {"name": "Vans Sk8-Hi Reissue"})["category"] == "skate"


def test_existing_slug_collision_is_skipped_not_overwritten(tmp_path, monkeypatch):
    existing = [{"slug": "nike-air-huarache-since-91", "name": "placeholder",
                 "brand": "Nike", "category": "lifestyle",
                 "trends_term": "placeholder", "keywords": ["placeholder"]}]
    path = _seed_catalog(tmp_path, existing)
    monkeypatch.setattr(discovery, "run", lambda limit=10: [
        {"name": "Nike Air Huarache Since 91", "mentions": 5, "outlets": 3}])
    added = promotion.run(catalog_path=path, confirm=lambda term: 30.0)
    assert added == []
    # Original entry untouched.
    assert json.loads(path.read_text()) == existing


def test_multiple_candidates_only_qualifying_ones_promoted(tmp_path, monkeypatch):
    path = _seed_catalog(tmp_path)
    monkeypatch.setattr(discovery, "run", lambda limit=10: [
        {"name": "Nike Air Huarache Since 91", "mentions": 5, "outlets": 3},
        {"name": "adidas Samba Rumor Colorway", "mentions": 2, "outlets": 1},
    ])
    seen_terms = []

    def confirm(term):
        seen_terms.append(term)
        return 25.0 if "Huarache" in term else None

    added = promotion.run(catalog_path=path, confirm=confirm)
    assert [a["slug"] for a in added] == ["nike-air-huarache-since-91"]
    # The low-traction candidate never even reached the trends check.
    assert "adidas Samba Rumor Colorway" not in seen_terms


def test_catalog_json_format_matches_existing_style(tmp_path, monkeypatch):
    """Round-trip formatting must match the real catalog.json exactly
    (indent=1, no stray trailing newline) so a promoted entry looks
    hand-written, not machine-dumped."""
    path = _seed_catalog(tmp_path, [{"slug": "existing-shoe", "name": "Existing Shoe",
                                       "brand": "Nike", "category": "lifestyle",
                                       "trends_term": "Existing Shoe",
                                       "keywords": ["existing shoe"]}])
    monkeypatch.setattr(discovery, "run", lambda limit=10: [
        {"name": "Nike Air Huarache Since 91", "mentions": 4, "outlets": 2}])
    promotion.run(catalog_path=path, confirm=lambda term: 20.0)
    raw = path.read_text()
    assert raw == json.dumps(json.loads(raw), indent=1)
    assert not raw.endswith("\n")
