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

from tools import search_listings, suggest_outfit, create_fit_card, compare_price
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
    # "M" should match whole-token sizes like "M", "S/M", "M/L" — word-boundary match.
    results = search_listings("tee", size="M", max_price=None)
    assert len(results) > 0
    for item in results:
        # Every result must contain "M" as a whole token, not as part of another token.
        import re
        assert re.search(r"\bM\b", item["size"], re.IGNORECASE), (
            f"Expected whole-token 'M' in size '{item['size']}'"
        )


def test_search_size_no_cross_category_bleed():
    # Shoe size "8" must NOT match waist size "W28" — word-boundary prevents this.
    results = search_listings("boots", size="8", max_price=None)
    for item in results:
        assert "W28" not in item["size"] and "W" not in item["size"][:1], (
            f"Shoe size '8' matched waist size '{item['size']}'"
        )


def test_search_category_filter():
    # Category filter restricts results to the specified category only.
    results = search_listings("black", size=None, max_price=None, category="shoes")
    assert len(results) > 0
    assert all(item["category"] == "shoes" for item in results)


def test_search_category_excludes_others():
    # A keyword like "black" would match both tops and bottoms without a category filter.
    # With category="shoes", no tops or bottoms should appear.
    results = search_listings("black", size=None, max_price=None, category="shoes")
    assert all(item["category"] != "tops" for item in results)
    assert all(item["category"] != "bottoms" for item in results)


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


# ── Stretch Tool: compare_price (offline) ───────────────────────────────────

def test_compare_price_returns_verdict():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    result = compare_price(item)
    assert result["verdict"] in ("great deal", "fair price", "above average", "no comparables")
    assert isinstance(result["reasoning"], str)
    assert len(result["reasoning"]) > 0
    assert result["item_price"] == item["price"]


def test_compare_price_median_is_same_category():
    # Median must be drawn from the same category as the item.
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    from utils.data_loader import load_listings
    all_listings = load_listings()
    same_cat = [l for l in all_listings if l["category"] == item["category"] and l["id"] != item["id"]]
    prices = sorted(l["price"] for l in same_cat)
    expected_median = prices[len(prices) // 2]
    result = compare_price(item, all_listings=all_listings)
    assert result["median_price"] == expected_median
    assert result["comparable_count"] == len(same_cat)


def test_compare_price_no_comparables():
    # An item with a unique category returns the no-comparables fallback.
    fake_item = {"id": "fake-99", "category": "nonexistent", "price": 25.0}
    result = compare_price(fake_item)
    assert result["verdict"] == "no comparables"
    assert result["median_price"] is None
    assert result["comparable_count"] == 0
