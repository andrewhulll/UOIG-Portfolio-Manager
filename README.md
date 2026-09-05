# UOIG Investment Terminal

A Bloomberg-style portfolio terminal for the **Tall Firs** and **Alumni Fund**
portfolios: live market data, P&L, holding-period returns, 3-year daily beta,
and per-stock / per-sector research views. React frontend + FastAPI backend over
the existing Python analytics.

See [`DESIGN.md`](DESIGN.md) for the original architecture and build plan.

> **Status: terminal complete.** Real data end-to-end; the legacy Streamlit
> dashboard has been retired. "Ask Claude" is built but stubbed (flip to the live
> Anthropic API when ready).

## Architecture
```
web/        React + Vite frontend (the terminal UI)
api/        FastAPI backend (serves data + the built frontend)
src/        analytics: pnl, returns, risk, series + ingest/model
data/       SQLite store (generated; git-ignored)
scripts/    seed / reconcile / refresh / fundamentals
```

## API
The frontend talks to these JSON endpoints (Vite proxies `/api` to `:8000` in dev):

| Endpoint | What |
|---|---|
| `GET /api/data` | Funds, holdings, sectors snapshot (DB-backed) |
| `GET /api/series/{ticker}?period=` | Price series — DB for holdings, **live yfinance fallback** for any other ticker |
| `GET /api/fund-series/{fund}?period=` | Synthetic fund index vs benchmark |
| `GET /api/search?q=` | **Yahoo Finance symbol search, equities only** (powers the global search box) |
| `GET /api/quote/{ticker}` | **Live overview for any equity** (price, P/E, sector, 52-wk, description); 404 for non-equities |
| `GET /api/stock/{ticker}` | Financials / earnings / news / analyst research (live yfinance) |
| `GET /api/predictions/{ticker}` | Kalshi prediction-market cards |
| `GET /api/thesis/{ticker}` | Team's written thesis |
| `POST /api/chat` | Ask-Claude turn (Anthropic API) |
| `GET /api/auth/login` | Begin Google OAuth (302 to WorkOS) |
| `GET /api/auth/callback` | OAuth return — sets the session cookie |
| `POST /api/auth/password-login` | Email + password sign-in (sets session cookie) |
| `POST /api/auth/verify-email` | Complete an email-verification challenge |
| `POST /api/auth/password-reset` | Request a reset / set-password email |
| `POST /api/auth/password-reset/confirm` | Set a new password from a reset token |
| `GET /api/auth/me` | Current user + role, or 401 |
| `POST /api/auth/logout` | Clear the session cookie |
| `POST /api/auth/invite` | Invite a teammate by email (**PM role only**) |

Every `/api/*` route except `/api/health` and `/api/auth/*` requires a valid session
(see **Authentication** below).

**Search any equity.** The header search box queries Yahoo Finance live: type a name
or ticker, pick a result, and the stock page populates for *any* equity — not just
portfolio holdings. Held names show a "Held" badge and the full position panel; an
off-portfolio name shows a "Not held" card with the same live price/fundamentals.
The search-and-lookup path (`src/ingest/lookup.py`) is yfinance only — it does **not**
use the Anthropic API.

## Authentication (WorkOS — invite-only; Google + email/password)
The terminal is **invite-only and fully gated**: the whole app sits behind sign-in, and
only people invited by email can get an account. Sign in with **Google** or
**email + password** (with a forgot/set-password reset flow — that reset email is also how
an invited user sets their first password). Auth is handled by **WorkOS User
Management / AuthKit**; the backend code lives in `src/auth/` (`workos_client`, `sessions`,
`invitations`) and the routes in `api/main.py`. Roles are read from WorkOS and surfaced;
only the invite action is role-gated (PM) so far.

**One-time WorkOS dashboard setup**
- Enable AuthKit / User Management; add a **Google OAuth** connection **and** enable the **Email + Password** auth method.
- Create an **Organization** (its membership is the invite gate) and define roles (e.g. `pm`, `analyst`).
- Add the OAuth redirect URI: dev `http://localhost:5173/api/auth/callback`, prod `https://<domain>/api/auth/callback`.
- Set the **password-reset redirect URL** to the app with a `reset` marker: dev `http://localhost:5173/?reset=1`, prod `https://<domain>/?reset=1` (WorkOS appends the `token`; the SPA shows the set-password form).
- Invite teammates by email (dashboard, or `POST /api/auth/invite` — PM only).

**Secrets / config** (env var first, else a git-ignored `*.txt` at repo root — same pattern as `anthropic.key.txt`):

| Variable | File fallback | Notes |
|---|---|---|
| `WORKOS_API_KEY` | `workos.key.txt` | secret |
| `WORKOS_CLIENT_ID` | `workos.client.txt` | |
| `WORKOS_COOKIE_PASSWORD` | `workos.cookie.txt` | 32+ chars; seals the session cookie |
| `WORKOS_ORG_ID` | `workos.org.txt` | the invite-only org |
| `WORKOS_REDIRECT_URI` | — | defaults to `http://localhost:5173/api/auth/callback` |
| `WORKOS_PM_ROLE` | — | role slug allowed to invite teammates (default `pm`) |
| `UOIG_COOKIE_SECURE` | — | set `1` in production (HTTPS) for Secure cookies |
| `UOIG_AUTH_DISABLED` | — | **dev only** — bypass the gate; never set in production |

**Profile menu.** The nav-rail avatar opens a profile menu: Google photo (initials
fallback), name, email, role badge, and Sign out. Users whose role is the PM role
(`WORKOS_PM_ROLE`) also get an inline **Invite teammate** form — invite is the one
role-gated action and is enforced server-side (`POST /api/auth/invite` returns `403`
for non-PMs), not just hidden in the UI.

Until the three secrets are set, the app stays locked: the sign-in page shows and every
data route returns `401`. For local UI work without WorkOS, set `UOIG_AUTH_DISABLED=1`.

## Run it (development — hot reload)
Two processes; the Vite dev server proxies `/api` to the backend.
```bash
python -m pip install -r requirements.txt
python -m uvicorn api.main:app --port 8000        # backend  -> :8000
npm --prefix web install
npm --prefix web run dev                          # frontend -> :5173
```
Open http://localhost:5173.

## Run it (single server — production style)
Build the frontend once; FastAPI then serves the API **and** the built app on one port.
```bash
npm --prefix web run build
python -m uvicorn api.main:app --port 8000
```
Open http://localhost:8000.

## Run it (Docker — one command, reproducible)
Requires Docker Desktop. Builds the frontend and backend into one image.
```bash
docker build -t uoig-terminal .
docker run -p 8000:8000 \
  -e WORKOS_API_KEY=... -e WORKOS_CLIENT_ID=... -e WORKOS_COOKIE_PASSWORD=... \
  -e WORKOS_ORG_ID=... -e WORKOS_REDIRECT_URI=https://<domain>/api/auth/callback \
  -e UOIG_COOKIE_SECURE=1 \
  -e DATABASE_URL=postgresql://...        # Supabase pooler (omit to use bundled SQLite) \
  uoig-terminal
```
Open http://localhost:8000. (Pass the `WORKOS_*` env at run time — see **Authentication**.)

## Data
```bash
python -m scripts.seed_db        # build data/portfolio.db from the workbook
python -m scripts.refresh        # pull latest prices + dividends (yfinance)
python -m scripts.fundamentals   # pull P/E, P/B, sector, 52-wk, descriptions
python -m scripts.reconcile      # verify DB == source workbook
```
Tests: `python tests/test_reconcile.py && python tests/test_pnl.py && python tests/test_returns.py && python tests/test_risk.py`

### Database backend (SQLite or Postgres/Supabase)
The store runs on **SQLite by default** (`data/portfolio.db`) and switches to
**Postgres** automatically when a connection string is set — env `DATABASE_URL`, or a
git-ignored `supabase.url.txt` at the repo root (raw password is fine; we parse the URL).
Use a Supabase **pooler** URI (host `…pooler.supabase.com`), not the direct connection.
`src/model/db.py` papers over the dialect differences; the same query code runs on both.
```bash
# one-time copy of the local SQLite store into Supabase/Postgres
python -m scripts.migrate_to_postgres
```
All `data/` scripts (`seed_db`/`refresh`/`fundamentals`) target whichever backend is
configured, so after migrating you can run nightly refreshes straight against Supabase.

## Roadmap
| Phase | Status | What |
|---|---|---|
| 0 Foundation | done | Schema, importer, reconciliation |
| 1 Live prices & P&L | done | yfinance feed, market value, unrealized P&L |
| 2 Returns | done | Holding-period returns, benchmark-relative |
| 3 Risk | done | 3-yr daily beta vs Russell, vol, R² |
| A Backend API | done | FastAPI + fundamentals enrichment |
| B–D Terminal UI | done | Pixel-faithful React terminal; Ask-Claude stubbed |
| E Packaging | done | Single-container Docker, this runbook, Streamlit retired |
| F Global search | done | Yahoo Finance search + live quote/series; any equity opens a stock page (`src/ingest/lookup.py`) |
| G Auth — sign-in | done | WorkOS invite-only Google OAuth; whole app gated; roles tracked (`src/auth/`) |
| G2 Auth — profile menu | done | Profile dropdown (photo/name/email/role, sign out) + PM-only invite (`src/auth/`) |
| G3 Auth — email/password | done | Email + password sign-in + forgot/set-password reset, alongside Google |
| H Database — Supabase | done | Dual-backend SQLite/Postgres; one-command migrate (`src/model/db.py`, `scripts/migrate_to_postgres.py`) |
| Later | | Live Ask-Claude (Anthropic API); deploy backend host + frontend to Vercel |

## Handoff notes (for the next PM)
- Config lives in `config.yaml` (funds, benchmarks, beta window).
- The DB is reproducible: `seed_db` → `refresh` → `fundamentals`.
- Frontend API base is configurable via `VITE_API_BASE` (empty = same origin).
  When the frontend later moves to Vercel, point it at the hosted backend.
- Secrets (e.g. Kalshi keys) are git-ignored; keep them out of the repo.
