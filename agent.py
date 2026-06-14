"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Complete tools.py and test each tool in isolation before implementing this file.

Usage (once implemented):
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import json

from tools import (
    search_listings,
    suggest_outfit,
    create_fit_card,
    compare_price,
    get_trend_context,
    _get_groq_client,
    _MODEL,
)
from utils.data_loader import load_listings as _load_listings


# ── query parsing ─────────────────────────────────────────────────────────────

# The dataset stores sizes as letter codes ("S", "M", "S/M"), never words.
# Map the common spelled-out sizes back to those codes so a substring match works.
_SIZE_WORDS = {
    "extra small": "XS",
    "xsmall": "XS",
    "x-small": "XS",
    "small": "S",
    "medium": "M",
    "large": "L",
    "extra large": "XL",
    "xlarge": "XL",
    "x-large": "XL",
}


def _normalize_size(size: str | None) -> str | None:
    """Map spelled-out size words ('small') to dataset codes ('S')."""
    if not size:
        return None
    return _SIZE_WORDS.get(size.strip().lower(), size.strip())


# Adjacent sizes to try when the exact size returns no results, ordered by
# closeness. Only letter sizes are expanded — numeric sizes (shoe/waist) are
# left to the caller to decide whether to drop entirely.
_ADJACENT_SIZES: dict[str, list[str]] = {
    "XXS": ["XS", "S"],
    "XS":  ["S", "XXS"],
    "S":   ["XS", "M"],
    "M":   ["S", "L"],
    "L":   ["M", "XL"],
    "XL":  ["L", "XXL"],
    "XXL": ["XL", "L"],
}


def _expand_size(size: str) -> list[str]:
    """Return adjacent sizes to try when the exact size yields no results."""
    return _ADJACENT_SIZES.get(size.upper(), [])


def _parse_query(query: str) -> dict:
    """
    Use the LLM to extract search parameters from a free-text query.

    Returns a dict with keys:
        description (str): the keywords describing the item
        size (str | None): a size if one was stated, else None
        max_price (float | None): a price ceiling if one was stated, else None

    Falls back to using the raw query as the description (size/max_price None)
    if the LLM response can't be parsed — parsing must never crash the loop.
    """
    client = _get_groq_client()
    prompt = (
        "Extract clothing search parameters from this shopping request and "
        "return ONLY a JSON object — no prose, no code fences.\n\n"
        f'Request: "{query}"\n\n'
        "JSON shape:\n"
        "{\n"
        '  "description": "<just the item keywords, e.g. \'vintage graphic tee\'; '
        'drop size/price/wardrobe chatter>",\n'
        '  "size": "<the size as a code if stated — S, M, L, XL, or a number '
        "like '8'; map words such as 'small'->'S', 'large'->'L'; else null>\",\n"
        '  "max_price": <the price ceiling as a number if stated; else null>\n'
        "}"
    )

    fallback = {"description": query, "size": None, "max_price": None}
    try:
        response = client.chat.completions.create(
            model=_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"},
        )
        parsed = json.loads(response.choices[0].message.content)
    except (json.JSONDecodeError, KeyError, AttributeError, TypeError):
        return fallback

    description = parsed.get("description") or query
    size = _normalize_size(parsed.get("size"))

    max_price = parsed.get("max_price")
    if max_price is not None:
        try:
            max_price = float(max_price)
        except (TypeError, ValueError):
            max_price = None

    return {"description": description, "size": size, "max_price": max_price}


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.

    You may add fields to this dict as needed for your implementation.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "price_comparison": None,    # dict returned by compare_price
        "trend_context": None,       # string returned by get_trend_context
        "retry_note": None,          # set when search was retried with loosened params
        "error": None,               # set if the interaction ended early
    }


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.

    TODO — implement this function using the planning loop you designed in planning.md:

        Step 1: Initialize the session with _new_session().

        Step 2: Parse the user's query to extract a description, size, and
                max_price. You can use regex, string splitting, or ask the LLM
                to parse it — document your choice in planning.md.
                Store the result in session["parsed"].

        Step 3: Call search_listings() with the parsed parameters.
                Store results in session["search_results"].
                If no results: set session["error"] to a helpful message and
                return the session early. Do NOT proceed to suggest_outfit
                with empty input.

        Step 4: Select the item to use (e.g., the top result).
                Store it in session["selected_item"].

        Step 5: Call suggest_outfit() with the selected item and wardrobe.
                Store the result in session["outfit_suggestion"].

        Step 6: Call create_fit_card() with the outfit suggestion and selected item.
                Store the result in session["fit_card"].

        Step 7: Return the session.

    Before writing code, complete the Planning Loop and State Management sections
    of planning.md — your implementation should match what you described there.
    """
    # Step 1: fresh session — the single source of truth for this interaction.
    session = _new_session(query, wardrobe)

    # Step 2: parse the free-text query into search parameters.
    session["parsed"] = _parse_query(query)
    parsed = session["parsed"]

    # Step 3: search the listings with the parsed parameters.
    session["search_results"] = search_listings(
        parsed["description"],
        size=parsed["size"],
        max_price=parsed["max_price"],
    )

    # If nothing matched, retry with progressively loosened size constraints.
    if not session["search_results"] and parsed["size"]:
        original_size = parsed["size"]

        # First: try adjacent sizes (e.g. XXS → XS, S) before giving up on size.
        for adjacent in _expand_size(original_size):
            session["search_results"] = search_listings(
                parsed["description"], size=adjacent, max_price=parsed["max_price"]
            )
            if session["search_results"]:
                session["retry_note"] = (
                    f"No results for size {original_size} — showing nearby size {adjacent} instead."
                )
                parsed = {**parsed, "size": adjacent}
                break

        # Second: if adjacent sizes also failed, drop size entirely.
        if not session["search_results"]:
            session["search_results"] = search_listings(
                parsed["description"], size=None, max_price=parsed["max_price"]
            )
            if session["search_results"]:
                session["retry_note"] = (
                    f"No results for size {original_size} or nearby sizes — showing all sizes instead."
                )
                parsed = {**parsed, "size": None}

    # Third: if still empty and a price ceiling was set, drop that too.
    if not session["search_results"] and parsed["max_price"]:
        session["search_results"] = search_listings(
            parsed["description"], size=None, max_price=None
        )
        if session["search_results"]:
            note = f"No results for size {parsed['size']}" if parsed["size"] else "No results"
            note += f" under ${parsed['max_price']:.0f}"
            session["retry_note"] = note + " — showing all sizes and prices instead."
            parsed = {**parsed, "size": None, "max_price": None}

    # After all retries, if still nothing: set error and stop.
    if not session["search_results"]:
        session["error"] = (
            "Nothing matched that search even after loosening the filters. "
            "Try simpler keywords or a different item."
        )
        return session

    # Step 4: select the top (most relevant) result to build around.
    session["selected_item"] = session["search_results"][0]

    # Compare the selected item's price against the full dataset (offline).
    session["price_comparison"] = compare_price(
        session["selected_item"], all_listings=_load_listings()
    )

    # Fetch current trend context for the item's style tags (LLM call).
    session["trend_context"] = get_trend_context(
        session["selected_item"].get("style_tags", [])
    )

    # Step 5: suggest an outfit pairing the selected item with the wardrobe.
    # Pass trend context so it visibly influences the outfit suggestions.
    session["outfit_suggestion"] = suggest_outfit(
        session["selected_item"], wardrobe,
        trend_context=session["trend_context"],
    )

    # Step 6: turn the outfit into a shareable fit card.
    session["fit_card"] = create_fit_card(
        session["outfit_suggestion"], session["selected_item"]
    )

    # Step 7: done.
    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"Outfit: {session['outfit_suggestion']}")
        print(f"Fit card: {session['fit_card']}")

    print("=== No-results path ===")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")
