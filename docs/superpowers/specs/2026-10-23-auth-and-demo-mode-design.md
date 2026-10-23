# PIN Login + Public Demo Mode — Design

Date: 2026-10-23
Repos: backend `mealplanner` (this repo), frontend `../mp-ai-frontend` (the live one; CLAUDE.md's
`../frontend` path is stale)

## Intent

The app is used as a job-application showcase. Today it has no auth at all: anyone with the link
sees and can edit the owner's real recipes and plans. Two problems with that:

1. A curious reviewer can poke around and mess up the owner's real data.
2. A reviewer can conclude the owner "failed at auth", even though leaving it open was deliberate.

The owner is a backend engineer. What a reviewer should take away is that a lot of backend
automation sits behind one simple, useful result: a week's meal plan. The demo has to show that
engine working on meaningful English data, with no friction.

## Goals

- **Anonymous visitors land straight in a working demo.** There's no "try demo" button; being
  logged out *is* demo mode. The demo always has a meal plan for the current week.
- **Demo visitors can do everything**, including the real AI recipe import (Google/OpenRouter free
  tier; draining the quota for an hour or a day is acceptable). The one exception is deleting
  Dropbox files.
- **Owner login is a 4-digit PIN** with aggressive, global brute-force protection. A successful
  login switches that browser to the real data.
- **Security never relies on the code being private.** The code is public, and everything has to
  hold up with the source in hand.
- Keep the door open for more real users later (friends sharing the app), without building it now.

## Non-goals

- Multiple accounts, signup, password reset or user management.
- A background scheduler or cron.
- Per-visitor sandboxes. One shared demo is fine; reviewers seeing each other's changes is
  acceptable.
- Retrofitting an owner/tenant column onto every table.

## Anti-goals (things that count as failure even if they technically work)

- Any path where a demo request reads or writes the production Postgres.
- A demo that greets the visitor with an empty or stale week, or makes them wait on first load.
- Visible demo clutter: no banners or "data resets weekly" notices. A small "Demo" label is enough.
- Secrets, the PIN or its hash, or a default signing key anywhere in the repo.

## Decisions

### Two databases, routed per request by session

- **Owner session** → production Postgres (Supabase, `DATABASE_URL`), unchanged.
- **No valid session** → a local **SQLite** file inside the app container (gitignored, path set by
  config, for example `data/demo.sqlite`). There's no extra managed database.
- Routing happens in one place: the `get_db` dependency picks the session factory from the
  request's auth state. Routers keep the same data model and don't filter by tenant.
- **Every place that opens its own session has to follow the same routing.** Today these bypass
  `get_db` and would write demo data into production:
  - `app/services/recipe_import/service.py:68` (`SessionLocal()` inside the import job)
  - `app/routers/ingredients.py:48` (background nutrition estimation)
  - `app/routers/ingredients.py:120` (background FDC linking)

  The request's chosen session factory (or a demo/owner flag) is passed into these tasks. A test
  must prove a demo-mode import lands in SQLite and not in Postgres.
- The demo schema is built with `Base.metadata.create_all()` from `models.py`, **not** with the
  Alembic migrations. Migrations keep running only against Postgres on startup.
- SQLite compatibility: the only Postgres-specific construct found was `ilike` (recipes and
  ingredients search), which SQLAlchemy emulates on SQLite. A smoke test runs the meal plan
  generator and the shopping list aggregation against SQLite as part of the normal `pytest` run.
  There's no CI test workflow today (deploy.yml only deploys), and adding one is out of scope.
  The main test suite stays on Postgres.

### Demo data lifecycle

- **Seed:** a committed English JSON seed file with about 30–40 of the owner's recipes (plus their
  ingredients, portions and nutrition), translated **once**, offline, using the existing AI
  translator. Nothing is translated at runtime.
  - Source data: dump from the prod database using the credentials in the local `.env` (the owner
    approved this). The same dump can populate local development. The dump is read-only against
    prod and the raw dump is never committed; only the translated, reviewed seed subset is.
  - *Builder's call (set by design author):* the existing `ingredient_translator.py` only handles
    ingredient names, so a one-off script in `app/fixtures/` translates recipe names, instructions
    and categories too. The builder proposes the subset (balanced across meal types, recipes with
    images preferred) and the owner approves it before merge. The backend work doesn't wait on
    that approval: it can be built and tested against a draft seed.
  - The subset has to give the generator a real choice for breakfast, lunch and dinner (sensible
    `*_weight` values and calories).
  - The owner reviews and approves the subset, and it's checked for anything personal before
    committing. It's public.
  - Recipes reuse the owner's existing Dropbox image URLs. These are already publicly fetchable
    through today's open API, so nothing new is exposed.
- **Build at startup:** on app start the demo DB is (re)created from the seed and a plan for the
  current week is generated with the real `MealPlanGenerator`. A deploy is therefore also a clean
  demo reset (Dokku containers have ephemeral filesystems).
- **Lazy freshness check on demo requests** (cheap, no scheduler):
  - if the last reset is more than 7 days old → rebuild from seed;
  - if there's no meal plan covering the current week → generate one.

  This must be cheap on the hot path (for example, a cached "current week / reset timestamp" in
  memory) and safe if two requests trigger it at once (a lock).
- **The demo user** is a user row in the demo DB, created by the seed.

### Dropbox in demo mode

- Demo requests **never delete** from Dropbox. That covers deleting a recipe and replacing a
  recipe's image, both of which delete the old file today (`app/routers/recipes.py:186-189`,
  `:221-226`).
- Demo uploads go to a separate Dropbox folder, so they're never mixed with real images.
- Accepted risk: if the owner deletes a real recipe whose image the demo seed also points to, the
  demo shows a broken image. The owner will notice and refresh the seed.

### Owner login

- `POST /auth/login` takes `{pin}`. On success it sets a session cookie and resets the failure
  counter.
- `POST /auth/logout` clears the cookie.
- `GET /auth/me` returns `{mode: "owner" | "demo", ...}` and, when locked out, the lockout state
  (seconds until the next attempt is allowed), so the UI can show it.
- **The PIN is stored only as an argon2 hash in an env var** (Dokku `config:set`) and is verified
  in constant time. A small helper script (or documented one-liner) generates the hash.
- **Rate limit is global, across all visitors, not per IP.** The app runs uvicorn with
  `--forwarded-allow-ips=*`, so client IP headers are forgeable, and a global limit makes that
  irrelevant.
  - 3 failed attempts per hour are allowed.
  - After that, exponential backoff: the lockout doubles on each further failure (1h, 2h, 4h…).
  - A correct PIN resets everything.
  - The exact accounting (rolling window vs fixed) is the builder's call, as long as it meets
    these numbers.
- **Lockout state is in memory.** That's valid because the app runs as a single uvicorn process
  (the in-memory recipe-import job store already depends on this). Restarting the app is the
  owner's documented unlock. Changing the PIN = set a new hash env var.
- Accepted risk: an attacker can lock the owner out of *new* logins. Existing sessions keep
  working, and the owner has server access.

### Session

- A signed cookie, `HttpOnly`, `Secure`, `SameSite=Lax`, host-only on `api.mplanner.online`.
  Frontend `mplanner.online` and API `api.mplanner.online` are the same site, so the cookie works
  in every browser, Safari included.
- Long-lived (months); exact length is the builder's call.
- **The payload identifies a user** (`user_id`), not just "owner". The owner's PIN maps to the
  owner's existing user row in Postgres. This keeps multi-user possible later (another PIN →
  another user) without redesign. Out of scope now: one PIN, one user.
- *Design author's call:* the owner's user id comes from an `OWNER_USER_ID` env var (required, no
  default). Today all real plans and favorites were created as user 1 (`test@example.com`, the
  auto-create in `get_user()`). The builder confirms this against the prod dump before relying on
  it.
- Signing key comes from an env var. **If it's missing, the app refuses to start**; there's no
  fallback default.
- `Secure` has to be switchable off for local http development (config flag).
- Implementation (Starlette `SessionMiddleware`/itsdangerous vs a hand-rolled signed token) is the
  builder's call.

### CORS

- Replace `allow_origins=["*"]` with an explicit list from config: `https://mplanner.online` in
  prod and `http://localhost:5173` for dev. `allow_credentials=True` (the current wildcard plus
  credentials combination doesn't work with cookies).

### Current-user cleanup

- Remove the copy-pasted `get_user()` that hard-codes id=1 and auto-creates `test@example.com`
  (`app/routers/meal_plans.py:15-22`, `app/routers/favorites.py:14-22`).
- Remove the hard-coded `user_id=1` in `create_meal_plan` (`meal_plans.py:54`).
- Replace them with one `get_current_user` dependency based on the session: the demo user for
  demo, the session's user for owner.
- Remove the `user_id` query params on `GET /meal-plans/` and `/meal-plans/auto-generate`. Meal
  plans and favorites are filtered by the current user. Recipes and ingredients stay shared, as
  today.

### Health endpoints

- `GET /health` stays public and returns only `{"status": "ok"}`.
- `GET /health/extended` currently returns raw DB, Dropbox and AI error strings to anyone, which
  can leak hosts and config.
  - **It stays public** and keeps the same response shape and status codes, because the owner
    isn't sure whether a server-side Dokku check or monitor uses it.
  - Anonymous callers get per-service `status` and `provider` only, with no `details`.
  - Only an owner session sees `details`.
  - For an owner session it also reports the demo DB state (last reset, current-week plan
    present). This is the *builder's optional extra*.

### Public-repo hygiene

- Add `.env.example` with every required variable name (`DATABASE_URL`, Dropbox, AI keys,
  `OWNER_PIN_HASH`, `SESSION_SECRET`, `CORS_ORIGINS`, demo DB path, a cookie-secure flag) and
  placeholder values.
- Gitignore the demo SQLite file.
- No real secrets in tests or fixtures; tests generate their own hash and key.

### Frontend (`mp-ai-frontend`)

- `src/api/apiClient.ts` sends `credentials: "include"` on every request. Route the one stray
  direct `fetch` (`src/components/layout/Header.tsx:48`) through the client, or give it the same
  option.
- On load, call `/auth/me` to learn the mode.
- **Header:**
  - In demo mode, a small, unobtrusive "Demo" label and a "Log in" button.
  - In owner mode, "Log out".
- **Login:** a 4-digit PIN entry (modal or small popover; the builder's call). It shows "wrong
  PIN" and, when locked, the time until the next attempt. On success, it reloads the data.
- Remove `const userId = 1` in `src/pages/MealPlans.tsx:19-20` and stop sending `user_id`.
- **Language:** if the visitor hasn't explicitly chosen a language (nothing in localStorage),
  default to English instead of the browser language. The language switcher stays.
- Frontend deploys on Netlify from source.

## Tests (backend)

- Login: correct PIN sets the cookie; a wrong PIN fails; the 4th failure within an hour is
  locked; the backoff doubles; success resets it.
- No cookie / bad or forged cookie → demo DB. A demo request can never touch Postgres, including
  the three background tasks above.
- Owner cookie → Postgres, and the right user's meal plans only.
- Demo mode never calls Dropbox delete; demo uploads go to the demo folder.
- `/health/extended` returns no `details` without an owner session.
- The app fails to start without `SESSION_SECRET`.
- SQLite smoke test: build the demo DB from the seed and generate a week. Shopping list
  aggregation works.
- Lazy freshness: a stale reset triggers a rebuild, and a missing current-week plan triggers
  generation.

## Left to the builder

- Library choices (argon2-cffi / passlib, session mechanism) and module layout (for example
  `app/auth/`, `app/demo/`).
- The seed file format and the one-off translation script (it can live in `app/fixtures/`).
- Exact cookie lifetime, the rate-limit window mechanics within the stated numbers, and the lock
  implementation for the freshness check.
- Login UI details, within "really simple".
- Updating CLAUDE.md (frontend path, new env vars, how to change the PIN or unlock).
