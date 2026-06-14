"""
tests/test_agent.py

Tests for the planning loop in agent.py — focused on the branch behavior that
defines Milestone 4/5: the agent must NOT call the downstream tools when
search_listings returns nothing, and it must surface a specific error message.

The no-results test is marked `llm` because run_agent() makes one LLM call to
parse the query before searching. The size-normalization tests are offline.

Run from the project root:
    pytest tests/
    pytest tests/ -m "not llm"   # skip the LLM call
"""

import pytest

from agent import run_agent, _normalize_size, _expand_size
from utils.data_loader import get_example_wardrobe


# ── size normalization (offline) ────────────────────────────────────────────

def test_normalize_size_words_to_codes():
    # Spelled-out sizes map to the letter codes the dataset uses.
    assert _normalize_size("small") == "S"
    assert _normalize_size("SMALL") == "S"
    assert _normalize_size("medium") == "M"
    assert _normalize_size("Large") == "L"


def test_normalize_size_passthrough_and_empty():
    # Already-a-code values pass through; empty/None become None.
    assert _normalize_size("M") == "M"
    assert _normalize_size("8") == "8"
    assert _normalize_size(None) is None
    assert _normalize_size("") is None


def test_expand_size_adjacent_order():
    # XXS should try XS before S — closest first.
    assert _expand_size("XXS") == ["XS", "S"]
    assert _expand_size("M") == ["S", "L"]
    assert _expand_size("XL") == ["L", "XXL"]


def test_expand_size_unknown_returns_empty():
    # Numeric and unknown sizes have no adjacency map — return empty so the
    # retry loop falls through to dropping the size entirely.
    assert _expand_size("8") == []
    assert _expand_size("W30") == []
    assert _expand_size("One Size") == []


# ── planning loop: no-results branch ─────────────────────────────────────────

@pytest.mark.llm
def test_run_agent_no_results_stops_early():
    # An impossible query: search_listings returns [], so the agent must set a
    # helpful error and NOT proceed to suggest_outfit / create_fit_card.
    session = run_agent("designer ballgown size XXS under $5", get_example_wardrobe())

    assert session["error"] is not None
    assert session["search_results"] == []
    assert session["selected_item"] is None
    assert session["outfit_suggestion"] is None
    assert session["fit_card"] is None


@pytest.mark.llm
def test_run_agent_retry_sets_retry_note():
    # An impossible size (XXS) with a valid description should trigger a retry
    # and set session["retry_note"] explaining what was loosened.
    session = run_agent("vintage graphic tee size XXS", get_example_wardrobe())
    assert session["error"] is None
    assert session["retry_note"] is not None
    assert "XXS" in session["retry_note"]
    assert session["selected_item"] is not None


@pytest.mark.llm
def test_run_agent_happy_path_flows_through_all_tools():
    # A query that matches: every downstream field gets populated and no error.
    session = run_agent("vintage graphic tee under $30", get_example_wardrobe())

    assert session["error"] is None
    assert len(session["search_results"]) > 0
    # State passes correctly: the selected item is exactly the top search result.
    assert session["selected_item"] is session["search_results"][0]
    assert isinstance(session["outfit_suggestion"], str)
    assert len(session["outfit_suggestion"].strip()) > 0
    assert isinstance(session["fit_card"], str)
    assert len(session["fit_card"].strip()) > 0
