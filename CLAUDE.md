# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Start the app + Postgres
docker compose up

# Run all tests (requires Postgres running via docker compose)
pytest

# Run a single test file
pytest tests/test_unit_conversion.py

# Run a single test
pytest tests/test_unit_conversion.py::test_normalize_unit

# Lint
ruff check app/

# Format
black .

# Create a new migration after model changes
alembic revision --autogenerate -m "description"
```

Tests connect to `postgresql://postgres:postgres@dbmp:5432/test_db` and create/drop the `test_db` database each session — the real Postgres container must be running. There is no SQLite/mock option for integration tests.

## Architecture

**FastAPI + PostgreSQL + SQLAlchemy ORM.** Alembic migrations run automatically on startup (`app/main.py:startup_event`). The app runs on port 8000 via uvicorn inside Docker.

### Layer structure

- `app/main.py` — FastAPI app, CORS, HTTP logging middleware, startup migration runner
- `app/models.py` — SQLAlchemy ORM models: `Recipe`, `Ingredient`, `RecipeIngredient`, `MealPlan`, `MealPlanEntry`, `ShoppingList`, `ShoppingListItem`, `IngredientPortion`, `User`, `Favorite`
- `app/schemas.py` — Pydantic v2 request/response schemas
- `app/database.py` — engine + `get_db` dependency
- `app/routers/` — HTTP handlers (one file per domain: recipes, meal\_plans, shopping\_lists, ingredients, nutrition, favorites, health)
- `app/services/` — business logic
- `app/units.py` — unit normalization with multilingual aliases (EN/UK/RU/ES)
- `app/fixtures/` — one-off data import scripts, excluded from ruff linting

### Key services

**`services/meal_plan_generator.py`** — `MealPlanGenerator` uses weighted-random recipe selection with calorie targets per meal type (breakfast 25%, lunch 35%, dinner remainder). Recipes have `breakfast_weight`, `lunch_weight`, `dinner_weight` float columns (0–1) that drive selection probability. Falls back through four progressively relaxed filters when few recipes are available. Penalises recipes used in the prior 7 days.

**`services/unit_converter.py`** — `aggregate_quantities()` merges multiple `(quantity, unit)` pairs for the same ingredient into one shopping list line. Conversion chain: static mass (g/kg) → FDC portion lookup → keep as unconvertible. Items in `UNCONVERTIBLE_UNITS` (pinch, to taste, as needed) are kept as separate lines.

**`services/recipe_import/`** — Pipeline-based recipe import (image or URL → AI parsing → ingredient matching). `recipe_from_image.py` is a legacy adapter that delegates to this new pipeline.

**`services/fdc_linker.py` + `fdc_lookup.py`** — FoodData Central integration. Uses a local SQLite snapshot at `data/fdc.sqlite` for offline nutrition and portion data lookups. `get_gram_weight(ingredient, unit)` is the key function for volume/count-to-gram conversion.

## Auth & demo

Logged-out visitors get a demo served from SQLite; the owner logs in with a PIN and gets Postgres. Design rationale (threat model, rate limiter, trade-offs) lives in the docstring of `app/auth/__init__.py`.

- `app/auth/` — `pin.py` (argon2), `rate_limit.py` (global limiter), `session.py` (signed `mp_session` cookie), `deps.py`, `current_user.py`; HTTP in `app/routers/auth.py` (`/auth/login`, `/auth/logout`, `/auth/me`)
- `app/demo/` — `database.py` (SQLite generation files), `lifecycle.py` (rebuild at startup, weekly reset), `seed.py` + `seed.json` (27 English recipes). Regenerate the seed with `app/fixtures/export_demo_candidates.py` and `build_demo_seed.py` (prod read-only via `PROD_DATABASE_URL`).
- **Routing rule:** `get_db` / `get_session_factory` (`app/database.py`, `app/db_core.py`) choose owner -> Postgres, anonymous -> demo SQLite. Never open `SessionLocal()` directly; take a `session_factory` (background tasks and the recipe-import job do). No demo request may open a Postgres session, and demo never deletes from Dropbox (uploads go to `DROPBOX_DEMO_FOLDER`).

### Auth environment variables

See `.env.example`. `SESSION_SECRET`, `OWNER_PIN_HASH` and `OWNER_USER_ID` are required; the app fails at startup without them (there is no default key). Optional: `CORS_ORIGINS` (comma-separated, default `http://localhost:5173`), `COOKIE_SECURE` (default `true`; set `false` for plain-http local dev), `DEMO_DB_PATH`, `DEMO_SEED_PATH`, `DROPBOX_DEMO_FOLDER`. Production `OWNER_USER_ID` is `1`.

### Changing the PIN / unlocking

```bash
python -m app.auth.pin <pin>                                  # prints an argon2 hash
dokku config:set mp-be OWNER_PIN_HASH='<hash>'                # single quotes: the hash contains `$`
```

Argon2 hashes contain `$`. Locally, docker compose interpolates `$` in `env_file` values, so escape each one as `$$` in `.env`. With `dokku config:set` the value must be single-quoted.

After too many wrong PINs the login is locked out (global, in memory). Unlock with `dokku ps:restart mp-be`. Sessions are stateless cookies; to revoke all of them, rotate `SESSION_SECRET`.

### Unit normalization

`app/units.py` exports `normalize_unit(str) -> str | None` which maps multilingual aliases to canonical `BaseUnit` values before any comparison or storage. Always call this before storing or comparing units. `UNCONVERTIBLE_UNITS`, `COUNT_UNITS`, and `MASS_UNITS` dicts drive the aggregation logic.

### Tooling

- Line length: 100 (both ruff and black)
- `app/fixtures/` is excluded from ruff (one-off scripts)
- `alembic/versions/` and `app/schemas.py` have per-file ruff ignores

## Deployment

**Backend** is deployed to a Dokku instance (app name `mp-be`) via GitHub Actions on every push to `main` (`.github/workflows/deploy.yml`). The host is stored in the `DOKKU_HOST` GitHub Actions secret. The workflow does a force-push to the Dokku git remote using `DOKKU_SSH_KEY` from repo secrets.

Locally the backend runs via `docker compose up` (see `docker-compose.yml`): a `web` service on port 8000 and a `dbmp` Postgres 15 service on port 5432. Both read credentials from a `.env` file (`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`).

## Frontend

Located at `../mp-ai-frontend` (sibling repo). **React 18 + TypeScript + Tailwind CSS + React Router**, built with Vite, served by nginx in production.

```bash
cd ../mp-ai-frontend
npm install
npm run dev        # dev server (default port 5173)
npm run build      # production build → dist/
npm run lint       # ESLint
npm run test:e2e   # Playwright end-to-end tests
```

The frontend connects to the backend via the `VITE_API_URL` env var (default `http://localhost:8000`). In production the Docker image injects this at container startup via `docker-entrypoint.sh`, so it can be overridden without rebuilding the image.

The frontend is deployed on Netlify. The `../mp-ai-frontend/Dockerfile` and `nginx.conf` exist but are not used in production — Netlify builds directly from source.
