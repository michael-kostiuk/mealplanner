# Meal Planning Backend

FastAPI + PostgreSQL backend for a meal planning app. Users get a generated week of meals matched to their calorie target, with a consolidated shopping list. Recipes can be imported by photographing a cookbook page.

**Stack:** Python 3.12 · FastAPI · SQLAlchemy · PostgreSQL · Alembic · Docker · Google Gemini (via OpenRouter) · Dropbox

**Frontend:** [michael-kostiuk/mp-ai-frontend](https://github.com/michael-kostiuk/mp-ai-frontend) — React + TypeScript UI, fully AI-generated (Bolt.new + Claude Code).

> **Personal project.** Many decisions deliberately favour simplicity over production-grade robustness: synchronous DB sessions in async handlers, in-memory job queue, full table loads for recipe selection, a bundled FDC SQLite snapshot instead of live API calls, and no authentication. These are known trade-offs, not oversights — the app runs on a single node for one user, so the usual concerns around concurrency, scalability, and multi-tenancy don't apply.
>
> **Scope note:** authentication is intentionally out of scope. The app operates as single-user — all meal plans are stored under a default user record (id=1). Adding an auth layer is the natural next step but was deprioritised to focus on the core planning and import logic.

---

## Flows worth looking at

### 1. Meal plan generation
`app/services/meal_plan_generator.py` — `MealPlanGenerator`

Generates a full week of breakfast/lunch/dinner slots. Selection is weighted-random using per-recipe suitability weights (`breakfast_weight`, `lunch_weight`, `dinner_weight` on the `Recipe` model). Each slot targets a calorie fraction of the daily goal (25 / 35 / 40%), with a 4-level fallback when the pool is thin, a max-2-uses cap per recipe across the plan, and a 7-day recency penalty drawn from the user's history.

The same `_select_recipe` logic drives the single-meal re-roll endpoint (`suggest_meal`), so swapping one slot uses identical selection rules.

Router: `app/routers/meal_plans.py`

---

### 2. Recipe import pipeline (image → structured recipe)
`app/services/recipe_import/pipeline.py` — `RecipeImportPipeline`

A four-stage async pipeline invoked when a user uploads a cookbook photo:

1. **Extract** (`extractors/image.py`) — sends the image to Gemini and gets back a raw JSON draft (name, ingredients with quantities and units, instructions).
2. **Normalise & merge** — units are normalised through `app/units.py` (multilingual aliases: EN/UK/RU/ES), then duplicate ingredients in the draft are collapsed.
3. **Match** — each ingredient name is fuzzy-matched against the DB using `rapidfuzz` (WRatio + token-sort). High-confidence matches are accepted automatically; borderline matches go to an AI verification step that asks Gemini whether the two names refer to the same thing.
4. **Nutrition estimation** — `app/services/nutrition_estimator.py` estimates per-serving macros for the finished recipe.

Progress is streamed to the client via a job-store pattern (`job_store.py` / `service.py`) so the UI can show live status.

Router: `app/routers/recipes.py` (`/recipes/parse-from-image`)

---

### 3. Unit conversion & shopping list aggregation
`app/services/unit_converter.py` — `aggregate_quantities()`

Takes every ingredient across all meals in the plan and collapses them into one shopping list line per ingredient. Conversion path: static mass (g → kg) → FDC portion lookup (pieces, cups, tbsp via a local SQLite snapshot) → kept as unconvertible (pinch, to taste). Items from different measurement families that can't be unified are returned as separate lines.

FDC integration: `app/services/fdc_linker.py`, `app/services/fdc_lookup.py`

Router: `app/routers/shopping_lists.py`

---

### 4. Auth & demo mode
`app/auth/`, `app/demo/`, `app/database.py`

Logged out is the demo: anonymous visitors get a throwaway SQLite database seeded with 27 English recipes (rebuilt at startup, reset weekly), so they can click through every feature without touching real data. The owner's 4-digit PIN (`POST /auth/login`) sets a signed session cookie and switches every request to Postgres.

Routing happens in one place: the `get_db` dependency picks the session by who is asking. Background tasks and the recipe-import job never open a session themselves; they take a `session_factory`, so a demo request cannot reach Postgres. Demo uploads go to a separate Dropbox folder and demo never deletes from Dropbox.

Why not accounts, OAuth or 2FA? There is one user and the source is public, so the PIN is protected by a global rate limiter (3 failures per hour, then a doubling lockout) rather than by obscurity. The threat model, trade-offs and what was left out on purpose are written up in `app/auth/__init__.py`.

Routers: `app/routers/auth.py` (`/auth/login`, `/auth/logout`, `/auth/me`)

---

## Running locally

```bash
# Start app + Postgres
docker compose up

# Run tests (requires Postgres running)
pytest
```

Tests use a real Postgres container (`test_db`) — no mocks or SQLite fallback.

## Project layout

```
app/
  models.py          # SQLAlchemy ORM
  schemas.py         # Pydantic v2 request/response
  units.py           # multilingual unit normalisation
  routers/           # HTTP handlers (one file per domain)
  auth/              # PIN login, sessions, rate limiter (design notes in __init__.py)
  demo/              # SQLite demo database, seed and lifecycle
  services/
    meal_plan_generator.py
    unit_converter.py
    recipe_import/   # pipeline, job store, extractors
    fdc_linker.py
    fdc_lookup.py
    nutrition_estimator.py
tests/               # integration tests (pytest + real Postgres)
```
