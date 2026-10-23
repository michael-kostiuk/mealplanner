# PIN Login + Public Demo Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Anonymous visitors use a self-refreshing English demo backed by a local SQLite file. The
owner logs in with a rate-limited 4-digit PIN and gets the real Postgres data.

**Architecture:** A signed HttpOnly session cookie identifies a user. With no valid cookie the
request is in demo mode. `get_db` (and every background task) picks the Postgres or SQLite session
factory from that auth state, so routers keep a single data model. The demo DB is built from a
committed seed at startup and lazily refreshed (weekly reset plus a current-week plan) on demo
requests.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (Postgres + SQLite), argon2-cffi, itsdangerous, pytest;
React 18 + TS + i18next (frontend).

**Spec:** `docs/superpowers/specs/2026-10-23-auth-and-demo-mode-design.md`. Read it first; this plan
argues from it.

## Global Constraints

- **Branches:** never commit to `main`. Backend work goes on `feature/auth-demo`, branched from
  `docs/auth-demo-design`. Frontend work goes on `feature/auth-demo` in
  `/Users/michael/Documents/mk/mp-ai-frontend`.
- **Line length** is 100. Run `ruff check app/` and `black .` before each backend commit, and
  `npm run lint && npm run build` before each frontend commit.
- **No secrets in the repo**: no PIN, PIN hash, signing key or default key. Tests generate their
  own values.
- **No default signing key.** Missing `SESSION_SECRET`, `OWNER_PIN_HASH` or `OWNER_USER_ID`
  means startup fails.
- **Rate limit:** global (not per IP). 3 failures per rolling hour, then a 1h lockout that doubles
  on each further failure (1h, 2h, 4h…). Correct PIN resets it. State lives in memory; restart
  unlocks.
- **Cookie:** name `mp_session`, `HttpOnly`, `Secure` (config flag `COOKIE_SECURE`, default
  `true`), `SameSite=Lax`, host-only (no `domain=`), `path=/`, max age 180 days.
- **No demo request may open a Postgres session.** That includes background tasks and the
  recipe-import job.
- **Demo never deletes from Dropbox.** Demo uploads go to `DROPBOX_DEMO_FOLDER` (default
  `/recipes-demo`).
- **No banner.** The UI shows only a small "Demo" label.
- **Frontend language** defaults to English when the visitor has no stored choice.
- **Prod DB access** (Task 9) is read-only and uses the `.env` `DATABASE_URL`. The raw dump is
  never committed.

## Review Focus

1. **Concurrent login burst.** 10 parallel wrong-PIN requests while unlocked → at most 3 are
   evaluated before the lockout. Login check, verify and record are serialized (Task 3,
   `test_parallel_wrong_pins_cannot_exceed_limit`).
2. **Forged, tampered or expired cookie, or a valid cookie whose user row doesn't exist** → treated
   as demo, never a 500 and never Postgres (Task 3 `test_tampered_cookie_is_demo`, Task 5
   `test_cookie_for_missing_user_is_demo`).
3. **First demo requests after a week boundary arriving concurrently** → exactly one current-week
   plan is generated (Task 4, `test_concurrent_freshness_generates_one_plan`).
4. **An owner reading or editing a meal plan id that belongs to another user** (e.g. the old
   `test@example.com` plans if `OWNER_USER_ID` differs) → 404, not leaked (Task 5,
   `test_other_users_plan_is_404`).
5. **A demo `PUT /recipes/{id}` that changes `image_url`.** This is the replace path, not delete,
   and it must not call Dropbox delete (Task 7, `test_demo_update_replacing_image_does_not_delete`).

---

### Task 1: Settings, fail-fast startup, CORS, repo hygiene

**Files:**
- Create: `app/config.py`, `.env.example`, `tests/test_config.py`
- Modify: `app/main.py:20-25` (CORS), `app/main.py` `startup_event`; `requirements.txt`;
  `.gitignore`; `tests/conftest.py` (test env)

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Settings`, with fields:
    - `session_secret: str`
    - `owner_pin_hash: str`
    - `owner_user_id: int`
    - `cors_origins: list[str]`
    - `cookie_secure: bool`
    - `demo_db_path: str`
    - `demo_seed_path: str`
    - `dropbox_demo_folder: str`
  - `load_settings() -> Settings`: reads env. Raises `RuntimeError` naming each missing required
    var. Required vars: `SESSION_SECRET`, `OWNER_PIN_HASH`, `OWNER_USER_ID`.
  - `get_settings() -> Settings`: an `lru_cache` wrapper.
- Env defaults:
  - `CORS_ORIGINS`: comma-separated, default `http://localhost:5173`.
  - `COOKIE_SECURE`: default `true`.
  - `DEMO_DB_PATH`: default `data/demo.sqlite`.
  - `DEMO_SEED_PATH`: default `app/demo/seed.json`.
  - `DROPBOX_DEMO_FOLDER`: default `/recipes-demo`.

- [ ] **Step 1: Create branch** — `git checkout -b feature/auth-demo` (from `docs/auth-demo-design`).
- [ ] **Step 2: Write failing tests** in `tests/test_config.py`:
  - `test_missing_required_vars_raise`: with `SESSION_SECRET`, `OWNER_PIN_HASH` and
    `OWNER_USER_ID` removed via `monkeypatch.delenv`, `load_settings()` raises `RuntimeError`, and
    the message contains all three names.
  - `test_cors_origins_parsed`: `CORS_ORIGINS="https://mplanner.online, http://localhost:5173"` →
    `["https://mplanner.online", "http://localhost:5173"]`.
  - `test_cookie_secure_false`: `COOKIE_SECURE=false` → `False`.
- [ ] **Step 3: Run** `pytest tests/test_config.py -v`. Expected: FAIL (module missing).
- [ ] **Step 4: Implement** `app/config.py`.
  - Call `get_settings()` first thing in `startup_event`, before `run_migrations()`, so a
    misconfigured deploy fails at boot.
  - Replace CORS `allow_origins=["*"]` with `get_settings().cors_origins` and keep
    `allow_credentials=True`. Settings are read at module import for the middleware, which is
    fine because tests set env in conftest first.
- [ ] **Step 5: Test env.** At the top of `tests/conftest.py`, before importing `app`, use
  `os.environ.setdefault` to set:
  - `SESSION_SECRET="test-secret-not-for-prod"`
  - `OWNER_PIN_HASH`: an argon2 hash of `"1234"` computed in conftest with
    `argon2.PasswordHasher().hash`
  - `OWNER_USER_ID="1"`
  - `COOKIE_SECURE="false"`
  - `DEMO_DB_PATH`: a path under `tempfile.gettempdir()`
  - `DEMO_SEED_PATH="tests/fixtures/demo_seed_small.json"` (created in Task 4)
- [ ] **Step 6: Dependencies, gitignore, `.env.example`.**
  - Add `argon2-cffi>=23.1.0` and `itsdangerous>=2.1.0` to `requirements.txt`.
  - Add `data/demo.sqlite*` and `data/prod_dump*` to `.gitignore`.
  - Write `.env.example` listing every var the app reads (`grep -rn getenv app/` and
    `app/config.py`), with placeholder values and a one-line comment each.
- [ ] **Step 7: Run** `pytest tests/test_config.py -v` → PASS. Then run `pytest` (full suite) →
  same pass/fail as on `main`.
- [ ] **Step 8: Commit** — `feat: add settings with fail-fast secrets and explicit CORS origins`.

### Task 2: PIN hashing and global login limiter

**Files:**
- Create: `app/auth/__init__.py`, `app/auth/pin.py`, `app/auth/rate_limit.py`,
  `tests/test_auth_units.py`

**Interfaces:**
- Produces:
  - `hash_pin(pin: str) -> str` and `verify_pin(pin: str, pin_hash: str) -> bool` (argon2-cffi
    `PasswordHasher`; `verify_pin` returns False on `VerifyMismatchError` or `InvalidHashError`).
    `python -m app.auth.pin 1234` prints a hash.
  - `class LoginLimiter(clock: Callable[[], float] = time.monotonic)`, with:
    - `locked_for() -> float`: seconds remaining, `0.0` if attempts are allowed.
    - `record_failure() -> None`
    - `record_success() -> None`
    - `lock: asyncio.Lock`, for the caller to serialize the whole attempt.
  - `login_limiter: LoginLimiter`: the module-level singleton.
- Algorithm:
  - Keep the failure timestamps from the last 3600s, plus `level: int = 0` and
    `locked_until: float = 0`.
  - On a failure: prune, then append. If `level > 0`, then `level += 1` and
    `locked_until = now + 3600 * 2 ** (level - 1)`. Otherwise, if the window holds ≥3 failures,
    `level = 1` and `locked_until = now + 3600`.
  - On success: reset everything.
  - The level does not decay without a success or a restart. That's intended (the owner unlocks
    by restarting).

- [ ] **Step 1: Write failing tests** (fake clock: a list-backed callable):
  - `test_verify_pin_roundtrip`: `verify_pin("1234", hash_pin("1234"))` is True;
    `verify_pin("0000", ...)` is False; `verify_pin("1234", "garbage")` is False.
  - `test_three_failures_lock_one_hour`: after 2 failures `locked_for() == 0`; after the 3rd,
    `locked_for() == 3600`.
  - `test_backoff_doubles`: lock at t=0; move to t=3600, fail → `locked_for() == 7200`; move to
    t=3600+7200, fail → `14400`.
  - `test_failures_outside_window_dont_count`: fail at t=0 and t=1; move to t=3700, fail →
    `locked_for() == 0`.
  - `test_success_resets`: lock, move past it, `record_success()`, then 2 failures →
    `locked_for() == 0`.
- [ ] **Step 2: Run** `pytest tests/test_auth_units.py -v` → FAIL.
- [ ] **Step 3: Implement** `pin.py` and `rate_limit.py`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** — `feat: add argon2 PIN verification and global login limiter`.

### Task 3: Session cookie, `get_auth`, `/auth` routes

**Files:**
- Create: `app/auth/session.py`, `app/auth/deps.py`, `app/routers/auth.py`, `tests/test_auth_api.py`
- Modify: `app/main.py` (include router), `app/schemas.py` (`LoginRequest`, `AuthStatus`)

**Interfaces:**
- Consumes: `get_settings()`, `verify_pin`, `login_limiter` (Tasks 1–2).
- Produces:
  - `SESSION_COOKIE = "mp_session"` and `SESSION_MAX_AGE = 180 * 24 * 3600`.
  - `encode_session(user_id: int) -> str` and `decode_session(token: str) -> int | None`
    (itsdangerous `URLSafeTimedSerializer(settings.session_secret, salt="mp-session")`,
    `max_age=SESSION_MAX_AGE`; returns None on any bad, expired or tampered value).
  - `@dataclass(frozen=True) class AuthContext: mode: Literal["owner", "demo"]; user_id: int`.
  - `DEMO_USER_ID = 1`.
  - `get_auth(request: Request) -> AuthContext`: a valid cookie gives
    `AuthContext("owner", <decoded id>)`; anything else gives `AuthContext("demo", DEMO_USER_ID)`.
    Task 5 adds the missing-user fallback.
  - `LoginRequest(pin: str = Field(pattern=r"^\d{4}$"))`.
  - `AuthStatus(mode: Literal["owner", "demo"], login_locked_for: int)`: seconds, rounded up.
- Endpoints:
  - `POST /auth/login`, in this order inside `async with login_limiter.lock:`:
    1. If `locked_for() > 0`, return **429** with the `Retry-After` header and body
       `{"detail": "Too many attempts", "retry_after": <int>}`.
    2. Otherwise `ok = await run_in_threadpool(verify_pin, ...)`.
    3. On failure, `record_failure()` and return **401** `{"detail": "Wrong PIN"}`.
    4. On success, `record_success()`, set the cookie per Global Constraints with
       `encode_session(settings.owner_user_id)`, and return `AuthStatus("owner", 0)`.
  - `POST /auth/logout`: delete the cookie and return `AuthStatus("demo", ...)`.
  - `GET /auth/me`: returns `AuthStatus`.

- [ ] **Step 1: Write failing tests** with `TestClient(app)`. Each test calls a fixture that
  replaces `app.auth.rate_limit.login_limiter` with a fresh instance (monkeypatch both the module
  attribute and the router's reference).
  - `test_me_without_cookie_is_demo` → `{"mode": "demo", "login_locked_for": 0}`.
  - `test_login_correct_pin_sets_cookie`: 200, `mp_session` in `response.cookies`; the
    `set-cookie` header contains `HttpOnly`, `SameSite=lax` and `Max-Age=15552000`; then
    `/auth/me` gives mode `owner`.
  - `test_wrong_pin_401_then_429_after_three`: 3× wrong → 401, 401, 401; 4th (even the correct
    PIN) → 429 with `retry_after == 3600`.
  - `test_malformed_pin_422_not_counted`: `"12a4"` → 422; then 3 wrong → the third is still 401.
  - `test_tampered_cookie_is_demo`: set `mp_session` to a valid token with its last char changed →
    `/auth/me` mode `demo`, status 200.
  - `test_logout_clears_cookie`: login, logout, `/auth/me` → demo.
  - `test_parallel_wrong_pins_cannot_exceed_limit`: an async test using
    `httpx.AsyncClient(transport=ASGITransport(app))`, `asyncio.gather` 10 wrong-PIN posts →
    exactly 3 are 401 and 7 are 429.
- [ ] **Step 2: Run** `pytest tests/test_auth_api.py -v` → FAIL.
- [ ] **Step 3: Implement** `session.py`, `deps.py`, `routers/auth.py`, the schemas, and the
  router include.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** — `feat: add PIN login, session cookie and auth status endpoints`.

### Task 4: Demo database: engine, seed loader, lifecycle, SQLite smoke test

**Files:**
- Create: `app/demo/__init__.py`, `app/demo/database.py`, `app/demo/seed.py`,
  `app/demo/lifecycle.py`, `app/demo/seed.json` (placeholder: a copy of the small fixture until
  Task 9), `tests/fixtures/demo_seed_small.json`, `tests/test_demo.py`
- Modify: `app/main.py` `startup_event`

**Interfaces:**
- Consumes: `get_settings().demo_db_path / demo_seed_path`, `MealPlanGenerator`,
  `generate_shopping_list(meal_plan, db)` (`app/routers/shopping_lists.py:18`), `DEMO_USER_ID`.
- Produces:
  - `get_demo_session_factory() -> sessionmaker`: lazily creates a SQLite engine at
    `demo_db_path` with `check_same_thread=False`.
  - `load_seed(db: Session, seed: dict) -> None`: creates the demo user (`id=DEMO_USER_ID`,
    `email="demo@mplanner.online"`), then the ingredients (with portions), then the recipes (with
    recipe-ingredients).
  - `rebuild_demo_db() -> None`: dispose the engine, delete the file, run
    `Base.metadata.create_all`, `load_seed`, ensure the current-week plan, and set
    `_last_reset = time.time()`.
  - `ensure_demo_fresh() -> None`: the cheap check.
    - If `time.time() - _last_reset > 7 * 86400`, call `rebuild_demo_db()`.
    - Else if the cached ISO week `!= date.today().isocalendar()[:2]`, ensure the current-week
      plan.
    - Do the work under a module `threading.Lock`, double-checking inside the lock. The fast path
      takes no lock.
  - `ensure_current_week_plan(db) -> MealPlan`: if no `MealPlan` for `DEMO_USER_ID` with
    `start_date` = this Monday 00:00, call
    `MealPlanGenerator(db).generate_meal_plan(start_date=monday, days=7, target_calories=2000, people_count=2, dietary_preferences=[], user_id=DEMO_USER_ID)`,
    then `generate_shopping_list(plan, db)`, then commit.
- **Seed JSON format**, shared with Task 9:
  ```json
  {"version": 1,
   "ingredients": [{"key": "<orig id>", "<Ingredient column>": "...", "portions": [{"<IngredientPortion column>": "..."}]}],
   "recipes": [{"<Recipe column>": "...", "ingredients": [{"ingredient_key": "<orig id>", "<RecipeIngredient column>": "..."}]}]}
  ```
  - Column names match the models exactly.
  - Exclude `id`, `created_at` and foreign-key ids (keys resolve them).
  - `load_seed` rejects unknown keys with `ValueError`.

- [ ] **Step 1: Hand-write** `tests/fixtures/demo_seed_small.json`: 3 English recipes (one each
  with `breakfast_weight`, `lunch_weight` or `dinner_weight` = 1.0, plus calories) and 3
  ingredients with nutrition. Copy it to `app/demo/seed.json`.
- [ ] **Step 2: Write failing tests** in `tests/test_demo.py`. These use SQLite only (no Postgres
  fixture). A `demo_env` fixture sets `DEMO_DB_PATH` to `tmp_path / "demo.sqlite"`, calls
  `get_settings.cache_clear()`, resets the cached demo engine, and undoes all three afterwards.
  - `test_rebuild_loads_seed_and_current_week_plan`: after `rebuild_demo_db()`, the demo session
    has 3 recipes, 1 user, 1 `MealPlan` with `start_date` = this Monday, its entries are non-empty,
    and a `ShoppingList` with items exists. This is the SQLite smoke test for the generator plus
    aggregation.
  - `test_unknown_seed_key_rejected`: `load_seed(db, {"version": 1, "ingredients": [{"key": "1", "bogus": 1}], "recipes": []})`
    raises `ValueError`.
  - `test_stale_reset_triggers_rebuild`: rebuild, add a recipe, set `_last_reset -= 8 * 86400`,
    `ensure_demo_fresh()` → recipe count is back to 3.
  - `test_new_week_generates_plan`: rebuild, delete all meal plans, reset the cached week to
    `None`, `ensure_demo_fresh()` → 1 plan.
  - `test_concurrent_freshness_generates_one_plan`: as above, but 8 threads call
    `ensure_demo_fresh()` together → exactly 1 plan.
- [ ] **Step 3: Run** `pytest tests/test_demo.py -v` → FAIL.
- [ ] **Step 4: Implement**, and call `rebuild_demo_db()` in `startup_event` after migrations.
- [ ] **Step 5: Run** `tests/test_demo.py` and the full `pytest` → PASS (app startup in other
  TestClient tests now also builds the demo DB from the small seed).
- [ ] **Step 6: Commit** — `feat: add self-refreshing SQLite demo database`.

### Task 5: Route DB sessions by auth; single current user; scope plans and favorites

**Files:**
- Modify:
  - `app/database.py`: add the factory selection.
  - `app/auth/deps.py`: missing-user fallback, `get_current_user`.
  - `app/routers/meal_plans.py:15-22,40-48,52-54,76-135,157-277`
  - `app/routers/favorites.py:14-22` and its routes
- Test: `tests/test_db_routing.py`

**Interfaces:**
- Consumes: `get_auth`, `AuthContext`, `get_demo_session_factory`, `ensure_demo_fresh`.
- Produces:
  - `get_owner_session_factory() -> sessionmaker` returns `SessionLocal`. It's the single seam
    tests override to point the owner path at `test_db`.
  - `get_session_factory(auth: AuthContext = Depends(get_auth), owner_factory = Depends(get_owner_session_factory)) -> sessionmaker`:
    owner gives `owner_factory`; demo calls `ensure_demo_fresh()` and then gives
    `get_demo_session_factory()`.
  - `get_db(factory = Depends(get_session_factory))` yields a session from `factory`. Same name
    and import path as today, so existing `dependency_overrides[get_db]` in tests keep working.
  - `get_current_user(auth = Depends(get_auth), db = Depends(get_db)) -> models.User` returns
    `db.get(User, auth.user_id)`.
  - **Missing-user fallback:** if an owner cookie's user row doesn't exist in Postgres, `get_auth`
    must treat the request as demo. Implement this in `get_auth`, which gains
    `owner_factory = Depends(get_owner_session_factory)`. For an owner cookie it checks that the
    user exists with a short lookup through `owner_factory()`. Only hits are cached, per user id,
    in memory.
- Behaviour changes:
  - Delete both `get_user()` copies, and the router-level `dependencies=[Depends(get_user)]`.
  - `GET /meal-plans/` loses `user_id`; it filters by `current_user.id`.
  - `POST /meal-plans/` uses `user_id=current_user.id`.
  - `/auto-generate` loses the `user_id` query param and its entry in `missing_params`; it passes
    `current_user.id`.
  - Every `/{meal_plan_id}` route, including regenerate via `?id=` and `/shopping-list`, loads the
    plan through `_get_owned_plan(db, meal_plan_id, user) -> MealPlan`, which gives 404 unless
    `plan.user_id == user.id`.
  - Favorites use `get_current_user`.
  - Unknown query params sent by the old frontend (`user_id=1`) are ignored by FastAPI, so the
    backend can deploy before the frontend.
  - Shopping lists stay unscoped. Out of scope; owner and demo are already in separate DBs.

- [ ] **Step 1: Write failing tests** in `tests/test_db_routing.py`.
  - Setup: the Postgres `db_session` with a user id 1, plus the demo DB rebuilt in `tmp_path`.
    Override `get_owner_session_factory` with a sessionmaker bound to `db_engine`. Do **not**
    override `get_db`. Put this override in a shared conftest fixture `owner_db`; Task 3's owner
    tests start using it too.
  - `test_anonymous_sees_demo_recipes`: `GET /recipes/` → the 3 seed recipe names, and none of the
    Postgres recipes created in setup.
  - `test_owner_sees_postgres_recipes`: log in with PIN `1234` → Postgres recipe names only.
  - `test_cookie_for_missing_user_is_demo`: a cookie from `encode_session(999)` → demo recipes,
    status 200.
  - `test_meal_plans_scoped_to_user`: Postgres plans for user 1 and user 2; owner (`user 1`)
    `GET /meal-plans/` → only user 1's plans.
  - `test_other_users_plan_is_404`: owner `GET /meal-plans/{user2_plan_id}` → 404, and the same for
    `PUT` and `DELETE`.
  - `test_demo_auto_generate_needs_no_user_id`: anonymous
    `POST /meal-plans/auto-generate?start_date=...&days=7&target_calories=2000&people_count=2` →
    200, and the plan's `user_id == 1` in the demo DB.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `tests/test_db_routing.py` and the full `pytest` → PASS. Update existing
  meal-plan tests that pass `user_id` or rely on the auto-create of `test@example.com`.
- [ ] **Step 5: Commit** — `feat: route DB by session and scope meal plans to current user`.

### Task 6: Background tasks and recipe import follow the routing

**Files:**
- Modify:
  - `app/routers/ingredients.py:10,42-160,284-320`
  - `app/services/recipe_import/service.py:20-28,36,68`
  - `app/services/recipe_from_image.py` (`start_job`)
  - `app/routers/recipes.py:17-27`
- Test: `tests/test_background_routing.py`; update `tests/test_recipe_from_image.py` call sites.

**Interfaces:**
- Consumes: `get_session_factory` (Task 5).
- Produces:
  - `_estimate_nutrition_background_sync(ingredient_id: int, session_factory: sessionmaker) -> None`
  - `_link_fdc_background_sync(ingredient_id: int, session_factory: sessionmaker) -> None`
  - `RecipeImportService.start_job(source_type: str, input_data: Any, *, session_factory: sessionmaker, **kwargs)`
    (**required**, no default). `_run_job` receives it and opens `session_factory()` where it
    called `SessionLocal()`.
  - `LegacyRecipeFromImageService.start_job(image_bytes, mime_type, session_factory)`.
  - The routes get the factory via `Depends(get_session_factory)` and pass it on.
  - Remove the `SessionLocal` imports from both files.

- [ ] **Step 1: Write failing tests:**
  - `test_demo_ingredient_background_tasks_use_demo_db`: anonymous `POST /ingredients/` with no
    nutrition. Monkeypatch the FDC/AI calls inside the two background functions to no-ops that
    record which session's `bind.url` they got → both recorded URLs are SQLite.
  - `test_demo_import_job_uses_demo_db`: anonymous `POST /recipes/parse-from-image` with a stubbed
    extractor (reuse the stubbing pattern in `tests/test_recipe_from_image.py`) and a
    `RecipeImportPipeline` stub that records `db.bind.url` → SQLite.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Update the `recipe_import_service.start_job(...)` calls in
  `tests/test_recipe_from_image.py` to pass
  `session_factory=sessionmaker(bind=db_session.get_bind())`. This also fixes that file's
  pre-existing failure, where it queried the real DB.
- [ ] **Step 4: Run** the full `pytest` → PASS.
- [ ] **Step 5: Commit** — `fix: background tasks and recipe import use the request's database`.

### Task 7: Dropbox guard for demo

**Files:**
- Modify: `app/services/dropbox_service.py:81-85` (`upload_image`),
  `app/routers/recipes.py:175-275`
- Test: `tests/test_demo_dropbox.py`

**Interfaces:**
- Consumes: `get_auth`, `get_settings().dropbox_demo_folder`.
- Produces: `upload_image(file_data: bytes, filename: str, folder: str | None = None) -> str | None`.
  `None` means `DROPBOX_UPLOAD_FOLDER`.
- Routes:
  - `update_recipe`, `delete_recipe` and `upload_recipe_image` take
    `auth: AuthContext = Depends(get_auth)`.
  - In demo mode, skip every `delete_image` call and upload with
    `folder=settings.dropbox_demo_folder`.

- [ ] **Step 1: Write failing tests.** Monkeypatch `dropbox_service.delete_image` and
  `upload_image` with recorders.
  - `test_demo_delete_recipe_does_not_delete_image`: anonymous delete of a seed recipe that has
    `image_url` → 200, delete never called.
  - `test_demo_update_replacing_image_does_not_delete`: anonymous `PUT` with a different
    `image_url` → delete never called.
  - `test_demo_upload_goes_to_demo_folder`: the upload recorder received
    `folder == "/recipes-demo"`.
  - `test_owner_delete_still_deletes`: owner delete → delete called once.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** the full `pytest` → PASS.
- [ ] **Step 5: Commit** — `feat: demo mode never deletes Dropbox images`.

### Task 8: `/health/extended` details for owner only

**Files:**
- Modify: `app/routers/health.py:50-80`
- Test: `tests/test_health.py`

**Interfaces:**
- Consumes: `get_auth`, `ensure_demo_fresh`'s module state (`_last_reset`, cached week).
- Behaviour:
  - Same status code and shape as today. Anonymous responses carry no `details` keys.
  - Owner responses include `details` plus `"demo": {"last_reset": <iso>, "current_week_plan": <bool>}`.

- [ ] **Step 1: Write failing tests**, monkeypatching `_check_database` to return
  `(False, "host=secret")`:
  - `test_extended_anonymous_has_no_details`: no `"details"` anywhere in the JSON, and no
    `"secret"` in the body text.
  - `test_extended_owner_has_details`: `services.database.details == "host=secret"`, and the
    `demo` key is present.
- [ ] **Step 2–4:** Run → FAIL, implement, then run the full `pytest` → PASS.
- [ ] **Step 5: Commit** — `fix: hide health check error details from anonymous callers`.

### Task 9: Real demo seed (owner in the loop)

**Files:**
- Create:
  - `app/fixtures/export_demo_candidates.py`: read-only prod export.
  - `app/fixtures/build_demo_seed.py`: turns approved ids plus translations into seed JSON.
- Modify: `app/demo/seed.json`
- Output (gitignored, not committed): `data/demo_candidates.md`, `data/demo_raw.json`,
  `data/prod_dump.sql`

**Interfaces:**
- Consumes: the seed JSON format (Task 4). `DATABASE_URL` comes from `.env` via `python-dotenv`.
- `export_demo_candidates.py`:
  - Opens a connection with `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY`.
  - Writes `data/demo_raw.json`: all recipes with ingredients and portions, in seed format, still
    Ukrainian.
  - Writes `data/demo_candidates.md`: a proposed 30–40 recipes, at least 10 per meal type by
    highest weight, image first. One row per recipe: id, name, category, the three weights,
    calories, has image.
  - Prints the user ids that own meal plans and favorites.

- [ ] **Step 1: Write and run** `python app/fixtures/export_demo_candidates.py`. Confirm the
  printed owner of the real plans and favorites. Expected: user 1. Record the result in the PR
  description as the `OWNER_USER_ID` value.
- [ ] **Step 2 (optional, local dev data):** `pg_dump` prod into `data/prod_dump.sql`, using the
  `postgres` image matching prod's server version (`docker run --rm postgres:<ver> pg_dump "$DATABASE_URL"`),
  and restore it into the local `dbmp` database named in `.env` `POSTGRES_DB`. Never restore into
  `test_db`.
- [ ] **Step 3: STOP. Show the owner `data/demo_candidates.md` and wait** for their veto list. Do
  not translate before approval.
- [ ] **Step 4: Translate** the approved recipes with a Haiku subagent (`model: "haiku"`):
  - Batches of about 10 recipes.
  - Fields: `name`, `instructions`, `category` and ingredient `name`, into natural English.
  - Units and numbers stay unchanged.
  - Output is JSON keyed by id.
  - Then `python app/fixtures/build_demo_seed.py --approved <ids> --translations <file>` writes
    `app/demo/seed.json`.
- [ ] **Step 5: Final check.**
  - Grep the seed for Cyrillic (`grep -P '[\x{0400}-\x{04FF}]' app/demo/seed.json` → no output).
  - Spot-read 5 recipes for anything personal.
  - Run `DEMO_SEED_PATH=app/demo/seed.json pytest tests/test_demo.py::test_rebuild_loads_seed_and_current_week_plan`
    → PASS.
  - Run a one-off `python -c` that rebuilds the demo DB from the real seed and prints the number
    of distinct recipes in the week's plan. Expected: ≥10. Otherwise, rebalance the weights in
    the subset with the owner.
- [ ] **Step 6: Commit** — `feat: add English demo seed from approved recipe subset`. Commit only
  the two scripts and `app/demo/seed.json`.

### Task 10: Backend docs and deploy checklist

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update CLAUDE.md:**
  - The frontend path is `../mp-ai-frontend`.
  - Auth and demo architecture: a short "Auth & demo" section naming `app/auth/`, `app/demo/`
    and the `get_db` routing rule ("never open `SessionLocal()` directly; take a
    `session_factory`").
  - New env vars.
  - How to change the PIN (`python -m app.auth.pin <pin>` then `dokku config:set mp-be OWNER_PIN_HASH=...`)
    and how to unlock (`dokku ps:restart mp-be`).
- [ ] **Step 2: Run** `ruff check app/`, `black --check .` and `pytest` → all clean.
- [ ] **Step 3: Commit** — `docs: document auth, demo mode and PIN management`.
- [ ] **Step 4: Hand the owner the deploy checklist.** Do not run it; it's outward-facing.
  1. `dokku config:set mp-be SESSION_SECRET=<random 64 hex> OWNER_PIN_HASH=<hash> OWNER_USER_ID=<from Task 9> CORS_ORIGINS=https://mplanner.online`
  2. Merge the backend PR. `main` auto-deploys.
  3. Check that `https://api.mplanner.online/auth/me` returns demo.
  4. Merge the frontend PR.

### Task 11: Frontend: send cookies, drop `user_id`, default to English

**Repo:** `/Users/michael/Documents/mk/mp-ai-frontend`, branch `feature/auth-demo`

**Files:**
- Modify:
  - `src/api/apiClient.ts`: the 5 `fetch(` calls.
  - `src/components/layout/Header.tsx:48`
  - `src/api/mealPlanApi.ts:7-8,45`
  - `src/pages/MealPlans.tsx:19-20`
  - `src/components/mealPlans/CreateMealPlanModal.tsx:25,81,90,123,298,515`
  - `src/i18n/index.ts:28`

**Interfaces:**
- Produces: `getMealPlans(): Promise<MealPlan[]>` (no argument).
- Every request sends `credentials: 'include'`.
- The `MealPlan.user_id` response type in `src/types/index.ts:147` stays.

- [ ] **Step 1: Create branch.** Add `credentials: 'include'` to every `fetch` in `apiClient.ts`
  and to the Header connection check.
- [ ] **Step 2: Remove the `userId`/`user_id: 1` request plumbing** from `mealPlanApi.ts`,
  `MealPlans.tsx` and `CreateMealPlanModal.tsx`, including the auto-generate params.
- [ ] **Step 3: Language default.** Set the i18next detection to `order: ['localStorage']`, so a
  visitor with no stored choice gets `fallbackLng: 'en'` instead of the browser language.
- [ ] **Step 4: Run** `npm run lint && npm run build` → no new errors. The repo already has
  known TS/ESLint errors; compare counts with `main` and require no increase.
- [ ] **Step 5: Commit** — `feat: send session cookie, drop hard-coded user id, default to English`.

### Task 12: Frontend: Demo label, PIN login, logout

**Files:**
- Create: `src/api/authApi.ts`, `src/context/AuthContext.tsx`, `src/components/auth/LoginModal.tsx`
- Modify:
  - `src/App.tsx`: wrap the app in `AuthProvider`.
  - `src/components/layout/Header.tsx`
  - `src/i18n/locales/en.json` and `uk.json`: an `auth.*` group.

**Interfaces:**
- Consumes: `/auth/login`, `/auth/logout`, `/auth/me` (Task 3; `AuthStatus` =
  `{mode: 'owner' | 'demo', login_locked_for: number}`. A 401 means a wrong PIN; a 429 body has
  `retry_after` seconds).
- Produces:
  - `authApi.me(): Promise<AuthStatus>`, `authApi.login(pin: string): Promise<AuthStatus>`,
    `authApi.logout(): Promise<AuthStatus>`.
  - `useAuth(): {mode: 'owner' | 'demo' | 'loading', lockedFor: number, login(pin): Promise<'ok' | 'wrong' | {lockedFor: number}>, logout(): Promise<void>}`.
- UI:
  - **Demo mode:** a small muted "Demo" pill next to the logo, plus a "Log in" text button.
  - **Owner mode:** "Log out".
  - **`LoginModal`:** one 4-digit numeric input (`inputMode="numeric"`, `maxLength=4`,
    autofocus, submits on the 4th digit). It shows "Wrong PIN" or "Too many attempts, try again
    in N min".
  - After a successful login or logout, run `window.location.reload()` to refetch everything.

- [ ] **Step 1: Implement** `authApi.ts` and `AuthContext.tsx`.
- [ ] **Step 2: Implement** `LoginModal.tsx` and the Header changes, with translation keys in
  both locale files.
- [ ] **Step 3: Run** `npm run lint && npm run build` → no new errors.
- [ ] **Step 4: Manual check** against the local backend (`docker compose up` with
  `COOKIE_SECURE=false`; `npm run dev`):
  1. Fresh browser profile → the Demo pill shows, English UI, this week's plan.
  2. Wrong PIN ×3 → the lockout message.
  3. Restart the backend, then correct PIN → real data and "Log out".
  4. Log out → demo.
  5. Run `npm run test:e2e` if the local Playwright setup works; note any failures that are
     pre-existing.
- [ ] **Step 5: Commit** — `feat: add demo label and PIN login to header`.
