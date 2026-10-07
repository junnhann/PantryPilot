# 🛒 CartPilot

An AI shopping assistant for the "Daily Life" track. Say what you want to cook, and CartPilot:

1. suggests recipes and works out a shopping list scaled to your servings,
2. looks at a photo of your fridge and skips what you already have,
3. sends **browser agents to several grocery sites in parallel** while you watch them live,
4. picks the best product for each item (price per unit, smart pack sizes) and hands you the product pages.

**It never adds to cart, logs in, or buys anything.** The finished list is just links; you decide what to buy.

> Stack: Python + FastAPI, Playwright, Google Gemini (free tier), plain HTML/JS (no build step).

---

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium      # one-time, ~100 MB
cp .env.example .env                       # then edit it (see below)
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>.

**No API key? No problem.** `.env.example` defaults to `DEMO_MODE=true`, which needs no key and no internet.

### Settings (`.env`)

| Variable | Default | What it does |
|---|---|---|
| `GEMINI_API_KEY` | – | Free key from <https://aistudio.google.com/apikey>. Never commit it (`.env` is git-ignored). |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Fast and supports images. Google retires models over time; if you get "model not found", pick another from AI Studio. |
| `DEMO_MODE` | `true` | `true` = canned AI answers, zero API calls (works offline). `false` = real Gemini. |
| `STORE_MODE` | `mock` | Only `mock` is supported: the 3 built-in fake stores (100% reliable). See "Why no real store?" below. |
| `HEADLESS` | `true` | `false` shows the real browser windows on your screen while they search. |
| `MAX_PARALLEL` | `4` | How many browser pages work at once. |
| `SCREENSHOT_FPS` | `2` | Live screenshots per second per browser tile. |

---

## The demo (≈ 2 minutes, works offline)

1. Keep `DEMO_MODE=true`. Type **"bake a chocolate cake"**, 6 servings → **Suggest recipes** → pick **Classic Chocolate Cake**.
2. Upload *any* photo as the "fridge". Demo mode reports milk and eggs as clearly there (pre-ticked), and butter / baking powder as unsure (**Please check** badges).
3. Click **Approve & start searching**. Watch three differently-styled shops get searched at once: tiles labelled "FreshMart: searching cocoa powder…", a live log, and a running total per store. Try **Stop** if you like.
4. On the results page note:
   * **cocoa powder** is the real powder, not QuickBasket's "Cocoa Powder Drink Mix" (the look-alike it ranks *first* in search).
   * **baking powder** skips ValueGrocer's cheapest tin because its size is "Value Tin" (unparseable).
   * every row shows **"Need 225g → 1 x 500 g pack"**, the price per 100 g, and 1–2 swappable alternatives.
   * a **Please confirm** item must be ticked or swapped before **Open all product pages** unlocks.
5. Scroll to **Leftovers** (e.g. "plain flour: 275g left over"), then tap **Search for this recipe** on an idea: the leftovers are pre-marked as owned and you're straight back at the checklist.

To use real AI: set `DEMO_MODE=false`, add your key, restart. A real fridge photo works much better than a fake one.

---

## How it works

```
 browser (static/)  ──HTTP──▶  FastAPI (app/main.py)  ──▶  Gemini (app/ai.py)    recipes, ingredients, fridge scan,
      ▲                              │                                            match review, leftover ideas
      │ WebSocket /ws                ▼
      │                        RunManager (app/runs.py)
      │                              │ creates
      │                              ▼
      └──── events ◀──────── Run (app/agent/agent.py): a pool of browser pages pulls (store, ingredient) jobs
            frames, log,            │  every page is a SafePage ── safety guard (app/agent/safety.py)
            results, report         ▼
                              StoreAdapter ── mock stores (mock_stores/)   [a real-store adapter would plug in here]
```

| Part | File | Notes |
|---|---|---|
| Schemas | `app/models.py` | Every AI reply is validated with Pydantic. |
| AI calls | `app/ai.py` | Gemini JSON mode; friendly errors (rate limit, busy, bad key, bad image); retries; demo mode. |
| Units | `app/units.py` | Parses `1kg`, `500 g`, `6 x 50ml`, `12's`, `1.5L`…; recipe conversions (1 cup flour = 120 g); price per 100 g/ml/piece; cheapest-pack selection. |
| Matching | `app/matching.py` | Rule-based confidence flags + ranking (below). |
| Report | `app/report.py` | Merges every store's options, totals per store, applies the AI review. |
| Agent | `app/agent/` | `agent.py` (orchestrator), `safe_page.py`, `safety.py`, `stores/base.py` (the `StoreAdapter` interface), `stores/mock_store.py`. |
| Mock shops | `mock_stores/` | 3 sites, 148 listings, 41 items, messy sizes, 19 look-alike decoys. |
| UI | `static/` | Vanilla JS; text is inserted with `textContent` (never `innerHTML`). |

### Product matching, in plain English

For each product, confidence is the **weakest** of these checks:

| Check | Result |
|---|---|
| Name doesn't contain the ingredient or a known synonym | **low** – "Name doesn't mention 'cocoa powder'" |
| Name has a different-form word (*drink, biscuit, coconut, ice cream, self raising…*) | **low** – "Might be a different product" |
| Name contains a *different* known ingredient ("brown sugar" for caster sugar) | **low** |
| Pack size can't be parsed | **low** – "Size unclear" |
| Sold by a unit we can't convert (pieces vs g) | **low** |
| Only a generic synonym matched ("sugar") or g↔ml was estimated | **medium** |

Ranking: confident matches first, then **cheapest total cost to cover the amount needed** (one pack type, bought 1+ times), then least waste. Per-unit price is shown and used as a tiebreak, so a 5 kg sack never "wins" a 200 g need.
In real-AI mode, one extra Gemini call double-checks the chosen products. It can only **lower** confidence, never raise it.

### Safety rules (enforced in code, with tests)

* **Search and open product pages only.** `app/agent/safety.py` refuses any click whose text, aria-label, CSS class, link target or enclosing button looks like *add to cart / buy / checkout / pay / place order / login / sign up / account*. It only lets the agent type into search boxes, and only visit the stores' own hosts (no `/cart`, `/checkout`, `/login`, `?add-to-cart=`, `javascript:` …).
* **By construction:** agent and adapters only ever get a `SafePage`, never a raw Playwright page. Every action is guard-checked, stop-checked and logged. A second, network-level check aborts any forbidden navigation (e.g. a redirect to a login page).
* **Nothing starts without approval:** `Run.start()` raises unless `approved=True`; `POST /api/runs` returns 400 without it; only the **Approve** button sends it.
* **Stop** halts every agent immediately (sets a flag all pages obey, cancels all tasks, closes the browsers).
* **Every action is logged** and streamed to the activity log.
* If a store looks blocked or unexpected (CAPTCHA, layout change), that store is abandoned and the UI says why. No stealth plugins, no CAPTCHA solving.

The mock product pages include an inert "Add to cart" button and a "Sign in" link, on purpose, so the guard has something real to refuse.

---

## Tests

```bash
python -m pytest -q                       # everything (~80 s: it drives real headless Chromium)
python -m pytest tests/test_safety.py -q  # safety guard only (instant)
```

| File | Covers |
|---|---|
| `test_safety.py` | the guard: forbidden clicks/typing/URLs and what must stay allowed |
| `test_units.py` | size parsing, conversions, price per unit, pack choice, leftovers |
| `test_matching.py` | confidence rules, ranking, and *every* catalogue item in *every* store |
| `test_mock_stores.py` | the fake shops: data, search, HTML contract, no cart/checkout pages |
| `test_agent.py` | real browsers: guard blocks Add-to-cart, parallel limit, Stop, failed store |
| `test_report.py` | report building, AI-review merging, leftovers, substitutes |
| `test_runs.py` | end-to-end: approve → live WebSocket events → report |
| `test_ui.py` | the actual web page, clicked through like a person (set `SHOT_DIR=…` to save screenshots) |
| `test_ai_demo.py`, `test_fridge.py`, `test_health.py` | AI layer (offline), fridge scan, API basics |

Watch the agents without the web UI: `python scripts/watch_agent.py` (opens real browser windows).

---

## Troubleshooting

* **"Model … not found"** → change `GEMINI_MODEL` in `.env` (list available ones in AI Studio).
* **"AI service is busy" / rate limit** → free tier hiccup; wait a few seconds or switch to `DEMO_MODE=true`.
* **Browser agents won't start** → run `python -m playwright install chromium`.
* **Real error details** are printed in the terminal running uvicorn.

## Known limitations

* Only the mock stores are wired in (see below).
* The fridge scan is only as good as the photo; that's why anything not high-confidence needs a human tick.
* The 30% leftover threshold, the typical piece weights (an onion ≈ 150 g) and the cup→gram table are rough, home-cooking-level approximations.
* One search runs at a time.

## Why no real store?

The original plan had a stretch goal: one real Singapore grocer. We checked FairPrice's public `robots.txt` first. It disallows `/search` for all automated visitors (along with `/cart`, `/checkout` and `/login`), and searching is exactly what the agent does, so **we deliberately did not build a real-store adapter**. Respecting a site's stated rules matters more than a flashier demo.

The design is ready if you find a store that permits it: implement the three methods of `StoreAdapter` (`search`, `open_product_page`, `get_product_details`) in a new file under `app/agent/stores/`, set a conservative `delay_range` and `max_concurrency` (1–2), raise `UnexpectedPage` on a CAPTCHA or odd layout, and add its host to `allowed_hosts`. The safety guard, Stop button, logging and live view then work unchanged. Check the site's `robots.txt` and terms first, and keep volume low.
