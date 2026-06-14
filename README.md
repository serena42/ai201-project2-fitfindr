# FitFindr

A multi-tool AI styling agent for secondhand clothing. Given a natural-language shopping query and a user's existing wardrobe, FitFindr finds a matching thrifted piece, suggests outfits that pair it with what you already own, and generates a shareable fit card caption.

Built with Python, Groq (`llama-3.3-70b-versatile`), and Gradio.

---

## Setup

```bash
pip install -r requirements.txt
```

Create a `.env` file in the project root with your Groq API key (free at [console.groq.com](https://console.groq.com)):

```
GROQ_API_KEY=your_key_here
```

Run the app:

```bash
python app.py
```

Open the URL shown in your terminal (usually `http://127.0.0.1:7860`).

Run the CLI test (both happy and no-results paths):

```bash
python agent.py
```

Run the test suite:

```bash
python -m pytest tests/ -v           # all tests (requires GROQ_API_KEY)
python -m pytest tests/ -m "not llm" # offline tests only
```

---

## Tool Inventory

### Tool 1: `search_listings`

**File:** `tools.py`

**Purpose:** Searches the local mock listings dataset for secondhand items matching a keyword description, optionally filtered by size and price ceiling. Runs entirely offline — no LLM call.

**Inputs:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `description` | `str` | Keywords describing what the user wants (e.g. `"vintage graphic tee"`). Matched against title, description, style_tags, and colors via weighted keyword overlap. |
| `size` | `str \| None` | Size filter — case-insensitive substring match (`"M"` matches `"S/M"`). `None` skips size filtering. |
| `max_price` | `float \| None` | Inclusive price ceiling. `None` skips price filtering. |

**Output:** `list[dict]` — matching listing dicts, sorted highest-relevance first. Each dict has: `id`, `title`, `description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`, `platform`. Returns `[]` on no match — never raises.

**Scoring:** title and style_tags (+3 each per matching token), colors (+2), description (+1). Zero-score items are dropped.

---

### Tool 2: `suggest_outfit`

**File:** `tools.py`

**Purpose:** Calls the Groq LLM to suggest 1–2 complete outfit combinations that pair a new thrifted piece with items the user already owns, in an elevated-casual voice.

**Inputs:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `new_item` | `dict` | The listing dict returned by `search_listings` — the piece the user is considering buying. |
| `wardrobe` | `dict` | The user's existing closet. Contains an `items` key with a list of wardrobe-item dicts. May be empty. |

**Output:** `str` — a non-empty string with outfit suggestions referencing named wardrobe pieces. If the wardrobe is empty, returns general styling advice for the item instead (what pairs well, what vibe it suits). Always returns a non-empty string — never raises.

---

### Tool 3: `create_fit_card`

**File:** `tools.py`

**Purpose:** Calls the Groq LLM to turn a finished outfit into a short, shareable OOTD-style caption — like a real Instagram or TikTok post, not a product description.

**Inputs:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `outfit` | `str` | The outfit suggestion string returned by `suggest_outfit`. |
| `new_item` | `dict` | The listing dict for the thrifted item — used to pull title, price, and platform for the caption. |

**Output:** `str` — a 2–4 sentence caption mentioning the item name, price, and platform once each, capturing the outfit's vibe. Uses temperature 1.0 so output varies across runs. If `outfit` is empty or whitespace, returns a descriptive error message string — never raises.

---

### Stretch Tool: `get_trend_context`

**File:** `tools.py`

**Purpose:** Calls the Groq LLM to describe what's currently trending in fashion for a given set of style tags. The result is injected into `suggest_outfit` so trend awareness visibly influences the outfit suggestions.

**Inputs:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `style_tags` | `list[str]` | Style descriptors from the selected listing (e.g. `["vintage", "grunge", "streetwear"]`). |

**Output:** `str` — a 2–3 sentence summary of current trends relevant to those styles, covering silhouettes, color palettes, or styling directions that are having a moment.

**Data source:** The LLM's training knowledge about current fashion trends, prompted with the item's specific style tags. Uses temperature 0.3 for consistent, factual output.

**How it influences outfit suggestions:** The trend string is appended to the `suggest_outfit` prompt as a "Current trend context" note. The LLM incorporates it when recommending outfit combinations — e.g. if the trend context mentions oversized silhouettes and earthy tones, the outfit suggestion will lean into those directions. The trend context is also shown at the top of the outfit panel in the UI as "Trending now: ...".

---

### Stretch Tool: `compare_price`

**File:** `tools.py`

**Purpose:** Compares a listing's price against all other items of the same category in the dataset and returns a price assessment with reasoning. Runs entirely offline.

**Inputs:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `item` | `dict` | The listing dict being assessed. |
| `all_listings` | `list[dict] \| None` | Pre-loaded listings to compare against. Loads from file if `None`. |

**Output:** `dict` with keys: `verdict` ("great deal" / "fair price" / "above average" / "no comparables"), `item_price`, `median_price`, `comparable_count`, `reasoning` (one sentence explaining the verdict).

**How comparisons are made:** All listings with the same `category` field are collected (excluding the item itself). Their prices are sorted and the median is computed. Items more than 20% below the median are "great deal"; within 15% above are "fair price"; beyond that are "above average". The reasoning sentence includes the median, the count of comparable items, and the dollar difference.

The result is shown in the listing panel of the UI as a price check line, e.g.:
```
Price check ✅ GREAT DEAL: At $19, this is $2 below the median of $21 for tops in this dataset (14 items compared) — a strong value.
```

---

## Planning Loop

The planning loop in `run_agent()` (`agent.py`) is sequential and branches on whether `search_listings` finds anything. Here's exactly what it does:

**Step 1 — Parse the query.** `_parse_query()` sends the user's free-text query to the LLM with a JSON-mode prompt, asking it to extract `description`, `size`, and `max_price`. The extracted `size` is passed through `_normalize_size()`, which maps spelled-out words (`"small"` → `"S"`, `"large"` → `"L"`) to the letter codes the dataset uses. If the LLM response can't be parsed, the raw query is used as the description with no size/price filters — parsing can never crash the loop. The result is stored in `session["parsed"]`.

**Step 2 — Search.** `search_listings()` is called with the parsed parameters. Results are stored in `session["search_results"]`.

**Step 3 — Retry with loosened constraints (stretch feature).** If `search_listings` returns nothing, the loop retries automatically in three escalating steps before giving up:
1. **Adjacent sizes first:** for letter sizes (XS/S/M/L/XL), try nearby sizes in order of closeness — XXS expands to XS then S, M expands to S then L, etc. This avoids suggesting an XXL for an XXS user. On success, `session["retry_note"]` explains which nearby size was used.
2. **Drop size entirely:** if adjacent sizes also fail, retry with no size filter. On success, `session["retry_note"]` says "all sizes".
3. **Drop price ceiling:** if still empty and a price ceiling was set, retry with no size and no price filter. On success, `session["retry_note"]` explains what was removed.
4. **Give up:** if still nothing, `session["error"]` is set and the loop stops.

The retry note is shown in the listing panel so the user knows what was adjusted, e.g.: *"No results for size XXS — showing nearby size S instead."*

- **Results found:** the loop continues.

**Step 4 — Select item.** `session["selected_item"]` is set to `session["search_results"][0]` — the top-ranked result.

**Step 5 — Suggest outfit.** `suggest_outfit(session["selected_item"], wardrobe)` is called. Result stored in `session["outfit_suggestion"]`.

**Step 6 — Create fit card.** `create_fit_card(session["outfit_suggestion"], session["selected_item"])` is called. Result stored in `session["fit_card"]`.

**Step 7 — Return.** The completed session dict is returned.

The key design decision: the loop only calls the downstream tools when there is an item to work with. Calling `suggest_outfit` with no item would require inventing data; the agent stops early instead and gives the user actionable recovery guidance.

---

## State Management

All state for a single interaction lives in the session dict initialized by `_new_session()`:

```python
{
    "query": str,             # original user query
    "parsed": dict,           # extracted description / size / max_price
    "search_results": list,   # full list of matching listing dicts
    "selected_item": dict,    # top result (results[0]), or None
    "wardrobe": dict,         # user's wardrobe, passed in unchanged
    "outfit_suggestion": str, # returned by suggest_outfit, or None
    "fit_card": str,          # returned by create_fit_card, or None
    "error": str,             # set if the interaction ended early, else None
}
```

Each tool writes its output into the session dict immediately after it returns. The next tool reads from the session dict rather than receiving a return value directly — this makes the state visible and inspectable at every step:

- `session["selected_item"]` is passed as `new_item` to `suggest_outfit`
- `session["outfit_suggestion"]` is passed as `outfit` to `create_fit_card`
- `session["selected_item"]` is also passed as `new_item` to `create_fit_card`

No data is re-derived between steps and no values are hardcoded. If state isn't flowing correctly, printing the session dict after any step reveals exactly what was passed.

---

## Error Handling

| Tool | Failure mode | What the agent does |
|------|-------------|-------------------|
| `search_listings` | No listings match the query | Returns `[]`. The planning loop sets `session["error"]` to a message naming the failure and suggesting three recovery actions (drop the size filter, raise the price ceiling, use simpler keywords), then returns the session early without calling the downstream tools. |
| `suggest_outfit` | Wardrobe is empty | The tool detects `wardrobe["items"] == []` and switches to a general-styling prompt that doesn't reference named wardrobe pieces. The LLM returns general advice about what pairs well with the item. No exception, no empty string. |
| `create_fit_card` | Outfit string is empty or whitespace | The tool guards at the top: `if not outfit or not outfit.strip()` returns a descriptive error string (`"Can't create a fit card — no outfit was provided. Generate an outfit suggestion first, then try again."`). The LLM is never called. |

### Triggered examples

**Failure 1 — no search results:**
```
$ python -c "from agent import run_agent; from utils.data_loader import get_example_wardrobe; s=run_agent('designer ballgown size XXS under \$5', get_example_wardrobe()); print(s['error'])"
Nothing matched that search. Try loosening your criteria — drop the size filter, raise the price ceiling, or use simpler keywords.
```
`s["fit_card"]` and `s["selected_item"]` are both `None`.

**Failure 2 — empty wardrobe:**
```
$ python -c "
from tools import search_listings, suggest_outfit
from utils.data_loader import get_empty_wardrobe
item = search_listings('vintage graphic tee', size=None, max_price=50)[0]
print(suggest_outfit(item, get_empty_wardrobe()))
"
This graphic tee is a great find for anyone who loves a laid-back, edgy vibe. To style it, consider pairing it with high-waisted jeans or a flowy skirt for a chic, contrasting look. The grunge-inspired aesthetic makes it perfect for casual outings, like concerts or weekend brunches. You could build an outfit around this tee by adding some distressed denim and chunky sneakers for a streetwear-inspired look, or dress it up with a leather jacket and heeled ankle boots for a more polished take on the vintage band tee trend.
```

**Failure 3 — empty outfit string:**
```
$ python -c "
from tools import search_listings, create_fit_card
item = search_listings('vintage graphic tee', size=None, max_price=50)[0]
print(create_fit_card('', item))
"
Can't create a fit card — no outfit was provided. Generate an outfit suggestion first, then try again.
```

---

## Spec Reflection

**What changed from planning.md to implementation:**

The planning.md spec described LLM-based query parsing but didn't anticipate the size-matching problem. The dataset stores sizes as letter codes (`S`, `M`, `S/M`, `L/XL`) but users naturally say "small" or "large." The implementation added a `_normalize_size()` helper that maps spelled-out size words to codes before passing them to `search_listings`. This isn't a deviation from the spec — it's a gap the spec didn't surface until the tool was live.

The error message for the no-results path is more specific than the spec called for. The spec said "tell the user nothing matched"; the implementation names three concrete recovery actions. This came from testing — a generic "no results" message isn't useful without telling the user what to change.

Everything else matched the spec: the session dict shape, the branch logic, the tool call order, and all three failure modes.

---

## AI Tool Usage

### Instance 1 — Milestone 3 tool implementations

**What I gave the AI:** the `tools.py` file with blank function bodies, the Tool 1–3 spec blocks from `planning.md` (inputs/outputs/failure modes for each tool), and the instruction to use `load_listings()` from `utils/data_loader.py` rather than re-implementing file loading.

**What it produced:** complete implementations of all three tools, including the keyword-overlap scoring loop with field weights, the empty-wardrobe branch in `suggest_outfit`, and the empty-outfit guard in `create_fit_card`.

**What I reviewed and changed:** I verified the scoring weights matched the spec (title and style_tags × 3, colors × 2, description × 1). I set `create_fit_card`'s LLM temperature to 1.0 rather than the default 0.7, after verifying that two runs at 0.7 produced identical output — the spec requires output to vary across runs. I also confirmed `max_price` filtering was inclusive (using `>` not `>=` to exclude) and that zero-score items were dropped not just sorted last.

### Instance 2 — Milestone 4 planning loop

**What I gave the AI:** the Architecture diagram from `planning.md` (the Mermaid flowchart), the Planning Loop section (the 8-step numbered list), and the State Management section (the session dict fields and how state flows between tools).

**What it produced:** the `run_agent()` implementation, the `_parse_query()` helper using Groq's JSON mode, and the `handle_query()` function in `app.py`.

**What I reviewed and changed:** I confirmed the branch was on `session["search_results"]` being empty — not on a boolean flag or exception. I verified `session["selected_item"]` was set to `results[0]` before being passed into `suggest_outfit` (not passed as a local variable that bypassed the session dict). I added the `_normalize_size()` helper after discovering "size small" returned no results — the AI didn't surface this gap because it didn't have visibility into the dataset's size format.
