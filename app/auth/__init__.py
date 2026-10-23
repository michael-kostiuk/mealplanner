"""Owner PIN login and public demo mode: design rationale.

Threat model. There is exactly one owner. The app is a public showcase and its source is public,
so nothing here relies on obscurity. What needs protecting is the owner's data and the AI quota
(recipe import, translation). Anonymous visitors are welcome; they get the demo, which runs on a
separate SQLite database and never touches the owner's data.

Why a 4-digit PIN is enough here. There are only 10,000 combinations, but the limiter is global,
not per IP, so forged X-Forwarded-For headers and IP rotation do not help an attacker. It allows
3 failures per rolling hour, then locks for 1h, doubling on every further failure (1h, 2h, 4h...).
That puts exhaustive search at years. The PIN is stored as an argon2 hash in an environment
variable and checked with argon2's constant-time verification.

Deliberately left out, and why:
- Accounts and signup: there is one user.
- OAuth: a third-party dependency and redirect flow to protect a single login.
- 2FA: the PIN guards a meal planner, and the owner already has server access.
- Password reset: the owner changes the environment variable.
- Distributed rate limiting: the app runs as a single process, so in-memory state is accurate.

Accepted trade-offs:
- An attacker can lock out new owner logins by burning the failure budget. Existing sessions
  (180-day signed cookies) keep working.
- Lockout state lives in memory. The escalation level resets only on a correct PIN or an app
  restart; that restart is the owner's unlock.
- Sessions are stateless signed cookies: logout clears the browser cookie, and revoking every
  session means rotating SESSION_SECRET.

If this ever needs multiple users: the session cookie already carries user_id, so the change is a
PIN (or other credential) per user mapped to a user row. Meal plans and favorites are already
scoped by user.

Where the pieces live:
- pin.py: argon2 hashing and verification
- rate_limit.py: the global login limiter
- session.py: signed session cookie
- deps.py: FastAPI dependencies (owner vs demo routing)
- routers/auth.py: login and logout endpoints
"""
