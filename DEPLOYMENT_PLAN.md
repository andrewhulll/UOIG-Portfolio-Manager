# Deployment Setup Plan — Vercel, Supabase, WorkOS

A step-by-step setup guide for taking the UOIG Investment Terminal from local dev to
a hosted deployment. Written against the current codebase so the steps line up with
the code you already have.

## How the pieces fit your codebase today

| Concern | Today | After this plan |
|---|---|---|
| Frontend (React/Vite, `web/`) | Built into the backend container (`Dockerfile` stage 1 → served by FastAPI's static mount in `api/main.py:317`) | Hosted on **Vercel**, talks to the backend via `VITE_API_BASE` (`web/src/api.js:4`) |
| Backend (FastAPI, `api/main.py`) | Single container serving API **and** SPA | Container host (Render/Railway/Fly) — keeps `yfinance`, in-process caches, Anthropic, sessions |
| Database | **SQLite** `data/portfolio.db` (`src/model/schema.py`) | **Supabase** (Postgres) |
| Auth | **WorkOS** invite-only Google OAuth, already coded (`src/auth/`) | Same code, provisioned + env vars set |
| LLM | Anthropic (`ANTHROPIC_API_KEY`) | unchanged |

> **Key architectural note.** Vercel is great for the React frontend but a poor fit
> for *this* backend: it's long-running, keeps in-process caches (`stock_research`),
> shells out to `yfinance`, and holds sealed WorkOS sessions. Don't try to cram
> FastAPI into Vercel serverless functions. Use **Vercel for the frontend** and a
> **container host for the backend** (your `Dockerfile` already builds it). The rest
> of this doc assumes that split.

**Recommended order:** WorkOS first (it's already coded and unblocks login), then the
backend host + Supabase, then Vercel for the frontend last (it needs the backend URL).

---

## 1. WorkOS (auth) — already coded, just provision

The whole flow is implemented in `src/auth/` and gated in `api/main.py`. You only need
to create the WorkOS resources and supply secrets. Secrets resolve **env var first,
then a git-ignored repo-root file** (`src/auth/workos_client.py`) — use env vars in the
cloud, files only for local dev.

### 1.1 Create the WorkOS account + application
1. Sign up at https://dashboard.workos.com and create an **Application** (e.g. "UOIG Terminal").
2. You'll have a **Staging** and a **Production** environment — set up Staging first, repeat for Production at go-live.

### 1.2 Enable AuthKit + sign-in methods
1. In the dashboard, go to **Authentication → AuthKit** and enable it (this is WorkOS User Management, which the SDK in `requirements.txt` (`workos>=5.0`) uses).
2. Under **Authentication → Google OAuth**, enable Google and follow WorkOS's wizard (it walks you through creating a Google Cloud OAuth client and pasting the client ID/secret into WorkOS). Your code requests `provider="GoogleOAuth"` in `src/auth/sessions.py`.
3. Also enable the **Email + Password** auth method — the app offers email/password sign-in alongside Google (`authenticate_with_password` in `src/auth/sessions.py`).

### 1.3 Configure redirect URIs
The callback path is `/api/auth/callback` (`api/main.py:91`). Add a redirect URI in
**Redirects** for each environment:
- Local dev: `http://localhost:5173/api/auth/callback` (the default in `src/auth/workos_client.py:70`; Vite proxies `/api` to the backend).
- Production: `https://<your-backend-host>/api/auth/callback` (the backend's public URL, **not** the Vercel domain — the OAuth handshake is server-side).

Also set the AuthKit **redirect/return** to your frontend origin so users land back on the app.

For the **email/password reset** flow, set the **Password reset redirect URL** with a `reset` marker
so the emailed link lands on the app's set-password form (`web/src/App.jsx` reads `?reset=1&token=`):
- Local dev: `http://localhost:5173/?reset=1`
- Production: `https://<frontend-origin>/?reset=1`

### 1.4 Create the Organization (this is your invite-only gate)
1. **Organizations → Create Organization** (e.g. "University of Oregon Investment Group").
2. Copy its **Organization ID** (`org_...`). `is_member()` in `src/auth/sessions.py:70` only lets users in if they belong to this org — that's your invite-only enforcement.
3. Invite your teammates: either from the dashboard (**Organization → Members → Invite**) or via the in-app endpoint `POST /api/auth/invite` (`api/main.py:132`).

### 1.5 Gather the secrets / config values
From **API Keys** and **Configuration**:

| Env var | Where to get it | Notes |
|---|---|---|
| `WORKOS_API_KEY` | API Keys (`sk_...`) | secret |
| `WORKOS_CLIENT_ID` | API Keys (`client_...`) | secret |
| `WORKOS_COOKIE_PASSWORD` | **you generate** | 32 random bytes encoded as URL-safe base64; seals the session cookie. `python -c "import secrets;print(secrets.token_urlsafe(32))"` |
| `WORKOS_ORG_ID` | the org from 1.4 (`org_...`) | the invite-only gate |
| `WORKOS_REDIRECT_URI` | your backend callback URL | e.g. `https://<backend>/api/auth/callback` |
| `UOIG_COOKIE_SECURE` | set to `1` in prod | required for HTTPS cookies (`src/auth/workos_client.py:73`) |

`configured()` (`workos_client.py:83`) returns true once the first three are present;
until then `/api/auth/login` returns 503.

### 1.6 Local-dev test
- Drop the secrets in repo-root files for local dev (all git-ignored per `.gitignore`):
  `workos.key.txt`, `workos.client.txt`, `workos.cookie.txt`, `workos.org.txt`.
- Or set `UOIG_AUTH_DISABLED=1` to bypass auth entirely while developing (`workos_client.py:78`) — **never** in production.
- Run backend + frontend, visit the app, confirm the Google sign-in redirect and that a non-invited Google account is rejected with `?auth_error=not_invited`.

---

## 2. Supabase (database) — migrate off SQLite

> **Status: implemented (Option B done).** The code is now dual-backend: SQLite by default,
> Postgres when `DATABASE_URL` / `supabase.url.txt` is set. `src/model/db.py` handles the
> dialect (paramstyle, upserts, identity PKs); `scripts/migrate_to_postgres.py` copies the
> local DB into Supabase. The session-pooler URI works; raw passwords are parsed (no manual
> URL-encoding needed). The steps below are kept for reference / re-seeding from scratch.

Today everything goes through `sqlite3` (`get_connection` in `src/model/schema.py:110`)
against `data/portfolio.db`, seeded from the workbook by `scripts/seed_db.py`. Supabase
is hosted Postgres, so this is a real (but contained) migration. Two options:

### Option A — Interim: keep SQLite, just host the backend (fastest)
If you only need to *deploy* soon, you can ship the SQLite file in the container
(the `Dockerfile` already does `COPY data/portfolio.db`). This works because the data
is read-mostly and reproducible from the workbook. **Caveat:** a container filesystem is
ephemeral — any writes (e.g. `transactions`) are lost on redeploy. Fine for a read-only
dashboard, not for durable writes. Use this to unblock, then do Option B.

### Option B — Migrate to Supabase Postgres (durable)
1. **Create the project.** https://supabase.com → New Project. Pick a region close to your backend host. Save the **database password**.
2. **Get connection details.** Project **Settings → Database**:
   - Use the **Session pooler** / connection string for a long-running backend (`postgresql://...:6543/postgres`), or the direct connection for migrations.
   - Copy the `DATABASE_URL`.
3. **Add the Postgres driver.** Add `psycopg[binary]>=3.1` (and optionally `sqlalchemy>=2.0`) to `requirements.txt`.
4. **Port the schema.** Translate `SCHEMA` in `src/model/schema.py` to Postgres dialect:
   - `INTEGER PRIMARY KEY AUTOINCREMENT` → `BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY` (or `BIGSERIAL`).
   - `executescript()` has no Postgres equivalent — run statements individually or via a `.sql` file.
   - `CHECK (... IN (...))` constraints carry over fine.
   - Run the DDL once in the Supabase **SQL Editor** to create tables.
5. **Add a Postgres connection path.** Introduce a `get_connection` that returns a psycopg connection when `DATABASE_URL` is set, falling back to SQLite locally. Note the parameter-style change: SQLite uses `?` placeholders, psycopg uses `%s` — audit every query in `src/analytics/` and `src/ingest/` (or adopt SQLAlchemy to abstract it).
6. **Seed the data.** Adapt `scripts/seed_db.py` to point at `DATABASE_URL` and load from the workbook, or `pg_dump`-style import a one-time SQLite→Postgres dump (e.g. `pgloader`).
7. **Set the env var** `DATABASE_URL` on the backend host (step 3).
8. **Verify** `/api/health` then `/api/data` return real data against Supabase.

> Scope estimate: schema port + connection swap + parameter-style audit is the bulk of
> the work. If you want, this can be its own task — say the word and I'll do the migration.

---

## 3. Backend host (prereq for Vercel)

The frontend needs a public backend URL, so host the backend before Vercel. Your
`Dockerfile` is ready to deploy as-is to any container host.

1. **Pick a host:** Render, Railway, or Fly.io (all take a Dockerfile directly).
2. **Create a Web Service** from this repo / the Dockerfile. Expose port 8000 (`Dockerfile:24`).
3. **Set environment variables** (everything from §1.5, plus):
   - `ANTHROPIC_API_KEY` — for the Ask-Claude co-pilot (`api/main.py:300`).
   - `DATABASE_URL` — if you did Supabase Option B.
   - `UOIG_COOKIE_SECURE=1`.
   - `WORKOS_REDIRECT_URI=https://<this-host>/api/auth/callback`.
4. **Note the public URL** (e.g. `https://uoig-terminal.onrender.com`) — you'll need it for Vercel and for the WorkOS redirect URI (§1.3).
5. **Cross-origin (implemented — just set env vars).** The split-deploy plumbing is
   built and env-driven, so no code edits are needed. For a Vercel frontend on a
   different origin than the Render backend, set on the **backend**:
   - `CORS_ORIGINS=https://<your-app>.vercel.app` — exact frontend origin(s), comma-separated. Turns on `allow_credentials=True` (replacing the wildcard).
   - `UOIG_COOKIE_SAMESITE=none` — lets the session cookie ride cross-site (auto-forces `Secure`).
   - `FRONTEND_URL=https://<your-app>.vercel.app` — where the OAuth callback returns the user after sign-in.
   The frontend already sends `credentials:'include'` on every call (`web/src/api.js`).
   Local dev needs none of these — defaults stay same-origin (`SameSite=lax`, wildcard CORS).
   - **Alternative (custom domain):** put both on one parent domain (`app.uoig.org` + `api.uoig.org`); then you can leave `UOIG_COOKIE_SAMESITE` at `lax`.

---

## 4. Vercel (frontend)

Hosts the React app in `web/`. The client already supports a remote backend via
`VITE_API_BASE` (`web/src/api.js:4`).

1. **Import the project.** https://vercel.com → Add New → Project → import this Git repo.
2. **Set the Root Directory** to `web/` (so Vercel builds the Vite app, not the repo root).
3. **Framework preset:** Vite (auto-detected). Build command `npm run build`, output `dist` — matches `web/package.json`.
4. **Environment variable:**
   - `VITE_API_BASE = https://<your-backend-host>` (from §3.4). This makes every `fetch` in `api.js` hit the remote backend. Leave it blank only if frontend and backend are same-origin (they won't be on Vercel).
   - Set it for **Production** and **Preview** (preview deploys can point at the same backend or a staging one).
5. **Deploy.** Vercel gives you a `https://<project>.vercel.app` URL (and you can add a custom domain).
6. **Wire the URL back into WorkOS + backend CORS:**
   - Add the Vercel origin to the backend CORS allowlist (§3.5).
   - Confirm AuthKit's return/redirect (§1.3) sends users back to the Vercel origin.
7. **Verify end to end:** open the Vercel URL → click sign in → Google → land back authenticated → confirm `/api/data` loads and Ask-Claude responds.

---

## Consolidated environment variables

**Backend host (Render/Railway/Fly):**
```
WORKOS_API_KEY=sk_...
WORKOS_CLIENT_ID=client_...
WORKOS_COOKIE_PASSWORD=<43-char token_urlsafe(32) value>
WORKOS_ORG_ID=org_...
WORKOS_REDIRECT_URI=https://<backend-host>/api/auth/callback
ANTHROPIC_API_KEY=sk-ant-...
DATABASE_URL=postgresql://...               # Supabase pooler URI
CORS_ORIGINS=https://<app>.vercel.app       # split deploy: exact frontend origin
FRONTEND_URL=https://<app>.vercel.app       # post-OAuth redirect target
UOIG_COOKIE_SAMESITE=none                   # cross-site cookie (auto-forces Secure)
```

**Vercel (frontend):**
```
VITE_API_BASE=https://<backend-host>
```

## Suggested sequencing
1. Provision WorkOS (§1), test locally with `UOIG_AUTH_DISABLED=1` off.
2. Deploy the backend container (§3) with WorkOS + Anthropic env vars, SQLite for now (Supabase Option A).
3. Deploy the frontend to Vercel (§4), pointed at the backend.
4. Apply the cross-origin changes (§3.5) and confirm login works on the Vercel domain.
5. Migrate to Supabase (§2 Option B) when you need durable writes.
