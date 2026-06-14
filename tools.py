"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()

_MODEL = "llama-3.3-70b-versatile"


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


def _tokenize(text: str) -> list[str]:
    """Lowercase and split text into alphanumeric word tokens."""
    return re.findall(r"[a-z0-9]+", text.lower())


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform

    TODO:
        1. Load all listings with load_listings().
        2. Filter by max_price and size (if provided).
        3. Score each remaining listing by keyword overlap with `description`.
        4. Drop any listings with a score of 0 (no relevant matches).
        5. Sort by score, highest first, and return the listing dicts.

    Before writing code, fill in the Tool 1 section of planning.md.
    """
    listings = load_listings()

    query_tokens = set(_tokenize(description or ""))

    scored: list[tuple[int, dict]] = []
    for listing in listings:
        # Price filter (inclusive). Skip if a ceiling is set and exceeded.
        if max_price is not None and listing["price"] > max_price:
            continue

        # Size filter: case-insensitive substring match ("M" matches "S/M").
        if size is not None and size.strip():
            if size.strip().lower() not in listing["size"].lower():
                continue

        # Score by keyword overlap against title, description, style_tags, colors.
        # Title and style_tags are weighted higher — they're the strongest signal.
        title_tokens = set(_tokenize(listing["title"]))
        tag_tokens = set(_tokenize(" ".join(listing.get("style_tags", []))))
        color_tokens = set(_tokenize(" ".join(listing.get("colors", []))))
        desc_tokens = set(_tokenize(listing.get("description", "")))

        score = 0
        for token in query_tokens:
            if token in title_tokens:
                score += 3
            if token in tag_tokens:
                score += 3
            if token in color_tokens:
                score += 2
            if token in desc_tokens:
                score += 1

        # Drop listings with no keyword overlap at all.
        if score == 0:
            continue

        scored.append((score, listing))

    # Sort by score, highest first. (Python's sort is stable, so equal-score
    # items keep their original dataset order.)
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [listing for _, listing in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def compare_price(item: dict, all_listings: list[dict] | None = None) -> dict:
    """
    Compare an item's price against other listings of the same category
    in the dataset and return a price assessment with reasoning.

    Args:
        item:         A listing dict (the item being considered).
        all_listings: Pre-loaded listings to compare against. If None,
                      load_listings() is called. Pass a cached list to avoid
                      repeated file reads.

    Returns:
        A dict with:
            verdict (str):          "great deal", "fair price", or "above average"
            item_price (float):     the item's price
            median_price (float):   median price of comparable items
            comparable_count (int): how many items were compared
            reasoning (str):        one sentence explaining the verdict
    """
    if all_listings is None:
        all_listings = load_listings()

    category = item.get("category", "")
    item_price = item.get("price", 0)
    item_id = item.get("id")

    comparables = [
        l for l in all_listings
        if l.get("category") == category and l.get("id") != item_id
    ]

    if not comparables:
        return {
            "verdict": "no comparables",
            "item_price": item_price,
            "median_price": None,
            "comparable_count": 0,
            "reasoning": f"No other {category} items in the dataset to compare against.",
        }

    prices = sorted(l["price"] for l in comparables)
    median = prices[len(prices) // 2]
    pct_diff = (item_price - median) / median * 100

    if pct_diff <= -20:
        verdict = "great deal"
        reasoning = (
            f"At ${item_price:.0f}, this is ${median - item_price:.0f} below the "
            f"median of ${median:.0f} for {category} in this dataset "
            f"({len(comparables)} items compared) — a strong value."
        )
    elif pct_diff <= 15:
        verdict = "fair price"
        reasoning = (
            f"At ${item_price:.0f}, this is close to the median of ${median:.0f} "
            f"for {category} in this dataset ({len(comparables)} items compared)."
        )
    else:
        verdict = "above average"
        reasoning = (
            f"At ${item_price:.0f}, this is ${item_price - median:.0f} above the "
            f"median of ${median:.0f} for {category} in this dataset "
            f"({len(comparables)} items compared) — you may find better value."
        )

    return {
        "verdict": verdict,
        "item_price": item_price,
        "median_price": median,
        "comparable_count": len(comparables),
        "reasoning": reasoning,
    }


def get_trend_context(style_tags: list[str]) -> str:
    """
    Ask the LLM what's currently trending in fashion for the given style tags.
    Returns a 2–3 sentence summary used to inform outfit suggestions.

    Args:
        style_tags: A list of style descriptors from a listing (e.g. ["vintage", "grunge"]).

    Returns:
        A non-empty string describing current trends relevant to those styles.
    """
    client = _get_groq_client()
    tags_str = ", ".join(style_tags) if style_tags else "general fashion"
    prompt = (
        f"In 2-3 sentences, describe what's currently trending in fashion "
        f"related to these styles: {tags_str}. Be specific about silhouettes, "
        f"color palettes, or styling approaches that are having a moment right now. "
        f"Keep it factual and actionable — no generic advice."
    )
    response = client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    return response.choices[0].message.content.strip()


def suggest_outfit(new_item: dict, wardrobe: dict, style_context: str | None = None, trend_context: str | None = None) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item:      A listing dict (the item the user is considering buying).
        wardrobe:      A wardrobe dict with an 'items' key. May be empty.
        style_context: Optional string describing the user's past style preferences,
                       loaded from the style profile. Injected into the prompt when set.
        trend_context: Optional string from get_trend_context() describing current
                       trends. Injected into the prompt to influence suggestions.

    Returns:
        A non-empty string with outfit suggestions. If the wardrobe is empty,
        returns general styling advice instead. Never raises.
    """
    client = _get_groq_client()

    # Describe the new item for the prompt.
    item_desc = (
        f"{new_item.get('title', 'the item')} "
        f"(category: {new_item.get('category', 'unknown')}, "
        f"colors: {', '.join(new_item.get('colors', [])) or 'n/a'}, "
        f"style: {', '.join(new_item.get('style_tags', [])) or 'n/a'})"
    )

    items = wardrobe.get("items", []) if wardrobe else []

    # Build optional context lines appended to both prompt variants.
    context_lines = ""
    if style_context:
        context_lines += f"\nUser's past style preferences: {style_context}"
    if trend_context:
        context_lines += f"\nCurrent trend context: {trend_context}"

    if not items:
        # Empty-wardrobe fallback: general styling advice, no named pieces.
        prompt = (
            f"A thrifter is considering buying this secondhand piece:\n"
            f"{item_desc}\n\n"
            f"They haven't told us what's in their closet. Give general styling "
            f"advice for this piece: what kinds of items pair well with it, what "
            f"vibe or occasions it suits, and one or two outfit directions they "
            f"could build around it. Keep it to a short, friendly paragraph in an "
            f"elevated-casual voice. Do not invent specific items they own."
            f"{context_lines}"
        )
    else:
        # Format the wardrobe into a readable list for the prompt.
        wardrobe_lines = []
        for it in items:
            colors = ", ".join(it.get("colors", []))
            tags = ", ".join(it.get("style_tags", []))
            line = f"- {it.get('name', 'item')} ({it.get('category', '')}"
            if colors:
                line += f"; {colors}"
            if tags:
                line += f"; {tags}"
            line += ")"
            wardrobe_lines.append(line)
        wardrobe_text = "\n".join(wardrobe_lines)

        prompt = (
            f"A thrifter is considering buying this secondhand piece:\n"
            f"{item_desc}\n\n"
            f"Here is what's already in their closet:\n{wardrobe_text}\n\n"
            f"Suggest 1-2 complete outfits that pair the new piece with specific "
            f"items from their closet. Refer to the wardrobe pieces by name. Keep "
            f"it concise and in an elevated-casual voice. Only use pieces from the "
            f"list above — don't invent items they don't own."
            f"{context_lines}"
        )

    response = client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    return response.choices[0].message.content.strip()


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)

    TODO:
        1. Guard against an empty or whitespace-only outfit string.
        2. Build a prompt that gives the LLM the item details and the outfit,
           and asks for a caption matching the style guidelines above.
        3. Call the LLM and return the response.

    Before writing code, fill in the Tool 3 section of planning.md.
    """
    # Guard against an empty or whitespace-only outfit string.
    if not outfit or not outfit.strip():
        return (
            "Can't create a fit card — no outfit was provided. "
            "Generate an outfit suggestion first, then try again."
        )

    client = _get_groq_client()

    title = new_item.get("title", "this find")
    price = new_item.get("price")
    price_str = f"${price:.0f}" if isinstance(price, (int, float)) else "a steal"
    platform = new_item.get("platform", "secondhand")

    prompt = (
        f"Write a short, shareable OOTD-style caption (2-4 sentences) for a "
        f"thrifted find, like a real Instagram or TikTok post — casual and "
        f"authentic, not a product description.\n\n"
        f"The find: {title}, scored for {price_str} on {platform}.\n"
        f"The outfit it's styled in:\n{outfit}\n\n"
        f"Mention the item name, the price, and the platform naturally, once "
        f"each. Capture the outfit's vibe in specific terms. Sound like a real "
        f"person, not an ad. Return only the caption."
    )

    # Higher temperature so captions vary across runs for the same input.
    response = client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=1.0,
    )
    return response.choices[0].message.content.strip()
