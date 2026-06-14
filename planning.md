# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## Tools

List every tool your agent will use. For each tool, fill in all four fields.
You must have at least 3 tools. The three required tools are listed — add any additional tools below them.

### Tool 1: search_listings

**What it does:**
Searches the local listings dataset for secondhand items matching a keyword description, optionally narrowed by size and a price ceiling; returns matches ranked by relevance.

**Input parameters:**
- `description` (str, required): keywords for what the user wants (e.g. "linen blazer"). Matched fuzzily against each listing's title, description, style_tags, and colors.
- `size` (str, optional, default `None`): case-insensitive substring match ("M" matches "S/M"); None skips size filtering.
- `max_price` (float, optional, default `None`): inclusive price ceiling; `None` skips price filtering.

**What it returns:**
A list of listing dicts (list[dict]), each carrying the full field set (id, title, description, category, style_tags, size, condition, price, colors, brand, platform), scored by keyword overlap, zero-score items dropped, sorted highest-first. 

**What happens if it fails or returns nothing:**
Returns []. The Agent will decide how to present this to the user. 

---

### Tool 2: suggest_outfit

**What it does:** 
Given a found item and the user's existing wardrobe, calls the LLM to suggest 1–2 complete outfit combinations that pair the new piece with named items the user already owns, in an elevated-casual voice.

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->
- `new_item` (dict): the listing dict returned by search_listings — the piece the user is considering buying.
- `wardrobe` (dict): the user's existing closet; contains an items key holding a list of wardrobe-item dicts. May be empty — handled gracefully.

**What it returns:**
A non-empty string describing 1–2 outfit combos, referencing specific wardrobe pieces by name. If the wardrobe is empty, returns general styling advice for the item instead (what pairs well, what vibe it suits).

**What happens if it fails or returns nothing:**
Empty wardrobe['items'] does not crash — the tool falls back to general styling advice. Always returns a non-empty string.

---

### Tool 3: create_fit_card

**What it does:**
Calls the LLM to turn a finished outfit into a short, shareable OOTD-style caption for the thrifted find.

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->
- `outfit` (str): the outfit suggestion string returned by suggest_outfit.
- `new_item` (dict): the listing dict for the thrifted item, used to pull name, price, and platform.

**What it returns:**
A 2–4 sentence caption string, mentioning the item name, price, and platform once each naturally, capturing the outfit's vibe. Uses higher LLM temperature so output varies across runs for different inputs.

**What happens if it fails or returns nothing:**
If outfit is empty or whitespace-only, returns a descriptive error-message string (not an exception, not "").

---

### Additional Tools (if any)

<!-- Copy the block above for any tools beyond the required three -->

---

## Planning Loop

**How does your agent decide which tool to call next?**
1. Loop receives description, optional size, optional max_price, and wardrobe.
2. Parse the query string into description, size, and max_price using an LLM call; store in session["parsed"].
3. Call search_listings(description, size, max_price).
4. Fork on the result:
- If results == []: set session["error"] to a widen-your-search message, leave selected_item, outfit_suggestion, and fit_card as None, and return session.  (Why: The found item is what both downstream tools operate on; with no item there's nothing to style or caption.)
- If results is non-empty: continue ↓
5. Set session["selected_item"] = results[0].
6. Call suggest_outfit(session["selected_item"], wardrobe); store in session["outfit_suggestion"].
7. Call create_fit_card(session["outfit_suggestion"], session["selected_item"]); store in session["fit_card"].
8. return session.

---

## State Management

**How does information from one tool get passed to the next?**
For each run there is a session dict, holding `parsed` (LLM parsed dict with description, price_max and size), `search_results` (full list), `selected_item`, `outfit_suggestion`, `fit_card`, and `error` (all starting as `None`)

The output of one tool is read back out of the session dict and handed in as the argument to the next. session["selected_item"] becomes the new_item argument to suggest_outfit; session["outfit_suggestion"] becomes the outfit argument to create_fit_card

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query | tells the user nothing matched and to loosen criteria (drop the size filter, raise the price, simpler keywords), and stops |
| suggest_outfit | Wardrobe is empty | the tool returns general styling guidance for the piece instead of named-wardrobe pairings |
| create_fit_card | Outfit input is missing or incomplete |Returns a short error message (unlikely since the suggest outfit tool guarantees non-empty string return) |

---

## Architecture

```mermaid
flowchart TD
    User[User query: description, size, max_price] --> Loop[Planning Loop]
    Loop --> Search[search_listings]
    Search -->|returns empty list| Err[Set session error, return]
    Search -->|returns non-empty list| Store1[session selected_item = results 0]
    Store1 -->|new_item = session selected_item| Suggest[suggest_outfit new_item, wardrobe]
    Suggest --> Store2[session outfit_suggestion]
    Store2 -->|outfit = session outfit_suggestion| Card[create_fit_card outfit, new_item]
    Card --> Store3[session fit_card]
    Store3 --> Return[return session]
    Err --> Return
```

---

## AI Tool Plan


**Milestone 3 — Individual tool implementations:**
For each of the three tools I will use Claude Code, giving it the function signature from tools.py, the corresponding tool spec block from planning.md (inputs, return value, failure mode), and the instruction to use load_listings() from utils/data_loader.py rather than reimplementing file loading. Before running the generated code I will check that it filters by all three parameters, handles None values for size and max_price by skipping those filters, scores by keyword overlap against title/description/style_tags/colors, drops zero-score items, and returns [] on no match rather than None or raising. I will then run it against three queries: one that should return results, one with a price ceiling that excludes everything, and one impossible combination (e.g. designer ballgown, XXS, $5) that must return [] without crashing. 

Once I believe the implementation is complete I will use Copilot as a second opinion — giving it the spec and the generated code and asking it to identify any requirement mismatches or edge cases I may have missed, not to generate alternative code.

**Milestone 4 — Planning loop and state management:**
I will give Claude Code the Architecture diagram from planning.md and the Planning Loop + State Management sections, and ask it to implement run_agent() in agent.py. Before running I will verify the generated code branches on the search result (not just calls all three tools unconditionally), stores each tool's output in the session dict immediately after it returns, and passes session["selected_item"] as new_item and session["outfit_suggestion"] as outfit rather than using any hardcoded values. I will then run the no-results test case and confirm session["fit_card"] stays None and session["error"] is set.

---

## A Complete Interaction (Step by Step)

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1:**
The planning loop extracts description="vintage graphic tee", size=None (not specified), and max_price=30.0 from the query and calls search_listings("vintage graphic tee", size=None, max_price=30.0). The tool scores all listings by keyword overlap against title, description, style_tags, and colors, drops zero-score items, filters out anything over $30, and returns a sorted list. The top result is the Vintage Band Tee — Faded Grey ($19, depop, fair condition). The loop sets session["selected_item"] to that listing dict.

**Error path:**
 If search_listings returns [] — for example, search_listings("designer ballgown", size="XXS", max_price=5.0) — the loop sets session["error"] to a message telling the user nothing matched and suggesting they drop the size filter, raise the price ceiling, or simplify their keywords, and returns immediately. suggest_outfit and create_fit_card are never called.

**Step 2:**
The loop calls suggest_outfit(new_item=session["selected_item"], wardrobe=get_example_wardrobe()). The tool formats the wardrobe items and the new piece into a prompt and calls the Groq LLM, which returns outfit suggestions pairing the band tee with named wardrobe pieces. The loop sets session["outfit_suggestion"] to that string. ("error path" doesn't happen, calling because step 1 successful and will give generic advice if wardrobe is None.)

**Step 3:**
The loop calls create_fit_card(outfit=session["outfit_suggestion"], new_item=session["selected_item"]). The tool prompts the LLM for a casual OOTD caption mentioning the item name, price, and platform naturally. The loop sets session["fit_card"] to the returned caption string.

**Final output to user:**
The Gradio interface populates three panels — the search result panel shows the Vintage Band Tee listing details, the outfit suggestion panel shows the LLM's styled combination using named wardrobe pieces, and the fit card panel shows the shareable caption.
