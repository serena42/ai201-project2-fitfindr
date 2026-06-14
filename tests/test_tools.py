"""
tests/test_tools.py

Tests for each FitFindr tool, including its failure mode.

Run from the project root with:
    pytest tests/

The search_listings tests are offline (no network). The suggest_outfit and
create_fit_card tests that hit the Groq LLM are marked `llm` so they can be
skipped without a network/API key:
    pytest tests/ -m "not llm"
"""

import pytest

from tools import search_listings, suggest_outfit, create_fit_card
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe


# ── Tool 1: search_listings (offline) ──────────────────────────────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0


def test_search_empty_results():
    # Impossible combination — no exception, just an empty list.
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=10)
    assert all(item["price"] <= 10 for item in results)


def test_search_size_filter():
    # "M" should match sizes like "M", "S/M", "M/L" (case-insensitive substring).
    results = search_listings("tee", size="m", max_price=None)
    assert all("m" in item["size"].lower() for item in results)


def test_search_sorted_by_relevance():
    results = search_listings("vintage denim jeans", size=None, max_price=None)
    assert len(results) > 1
    # The top result should be a strong keyword match.
    top = results[0]
    haystack = (top["title"] + " " + " ".join(top["style_tags"])).lower()
    assert any(word in haystack for word in ("vintage", "denim", "jeans"))


# ── Tool 2: suggest_outfit ──────────────────────────────────────────────────

@pytest.mark.llm
def test_suggest_outfit_with_wardrobe():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    result = suggest_outfit(item, get_example_wardrobe())
    assert isinstance(result, str)
    assert len(result.strip()) > 10


@pytest.mark.llm
def test_suggest_outfit_empty_wardrobe():
    # Failure mode: empty wardrobe must not crash; falls back to general advice.
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    result = suggest_outfit(item, get_empty_wardrobe())
    assert isinstance(result, str)
    assert len(result.strip()) > 0


# ── Tool 3: create_fit_card ─────────────────────────────────────────────────

def test_create_fit_card_empty_outfit():
    # Failure mode: empty/whitespace outfit returns an error string, no exception.
    item = {"title": "Vintage Band Tee", "price": 19.0, "platform": "depop"}
    result = create_fit_card("   ", item)
    assert isinstance(result, str)
    assert len(result.strip()) > 0
    assert "fit card" in result.lower() or "outfit" in result.lower()


@pytest.mark.llm
def test_create_fit_card_happy_path():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    outfit = "Pair the tee with baggy jeans and chunky white sneakers."
    result = create_fit_card(outfit, item)
    assert isinstance(result, str)
    assert len(result.strip()) > 0
