# UOIG Investment Terminal

The UOIG Investment Terminal is the internal portfolio analytics, equity research,
and analyst-workflow application for the University of Oregon Investment Group. It
tracks the **Tall Firs** and **Alumni Fund** portfolios, compares each fund with its
policy benchmark, and gives members one place to review holdings, research companies,
test portfolio changes, and communicate weekly coverage updates.

The current application is a React/Vite frontend backed by FastAPI, Supabase
Postgres, WorkOS authentication, and scheduled GitHub Actions. Production uses
Vercel for the frontend and Render for the backend; the same application can also
run locally or as a single Docker container.

> The terminal is a decision-support and research system. It is not a brokerage,
> order-management system, or intraday trading feed. Portfolio values use finalized
> daily closes.

## Function, features, and user workflows

### Function

The terminal turns UOIG's holdings, market history, company research, coverage
assignments, and team submissions into a shared operating workspace. It serves four
primary jobs:

1. Monitor the combined endowment and each fund against its benchmark.
2. Research current holdings and discover off-portfolio ideas.
3. Evaluate portfolio risk, concentration, active weights, and proposed changes.
4. Route analyst coverage updates to the appropriate sector leaders and preserve
   acknowledgement history.

### Features

| Area | What it provides |
|---|---|
| **Funds dashboard** | Combined or per-fund AUM, indexed performance versus benchmarks, alpha, beta, Sharpe ratio, volatility, valuation, yield, top holdings, MTD contributors, and sector mix. |
| **Holdings** | Searchable and sortable positions with fund, sector, weight, market value, closing price, day/MTD change, cost basis, unrealized gain, valuation, trend, and CSV export. |
| **Sectors** | UOIG's five coverage groups—TMT, IME, Healthcare, Financial, and Consumer—with portfolio weights, holdings, MTD performance, fund mix, sector benchmark comparisons, and weekly movers. |
| **Stock research** | Price history, company and position facts, institutional holders, internal thesis, quarterly financials, earnings, current news, analyst research, and curated Kalshi prediction markets. |
| **Global equity search** | Search by company or ticker and open a research page for an equity even when UOIG does not own it. |
| **Market screener** | Preset and custom screens across company, trading, valuation, profitability, leverage, liquidity, financial-statement, short-interest, and ESG fields. Results open directly into stock research. |
| **Portfolio optimization** | Benchmark-relative diagnostics, tracking error, active share, beta, volatility, concentration, security/sector active-risk contribution, interactive what-if weights, and a constrained optimizer with portfolio views. |
| **My Coverage** | Analyst-specific company cards with price/MTD context, upcoming earnings, and relevant news based on assignments stored in the organization directory. |
| **Weekly submissions and Inbox** | Analysts flag articles or write summaries, submit a sector digest, and receive acknowledgement notices. Sector leaders review, comment on, and acknowledge routed submissions; admins can review all sectors. |
| **Organization administration** | Invite-only member directory, profiles, roles, company coverage, and independent sector-leadership assignments. Admins manage invitations and assignments. |
| **Claude co-pilot** | Context-aware chat about the current fund, holding, or sector, plus an asynchronous managed-agent run that receives the full portfolio snapshot for deeper market analysis. Requires Anthropic configuration. |
| **User preferences and routing** | Persistent landing page, default fund, default period, profile settings, and deep links for funds, stocks, sectors, optimization, coverage, inbox, and assistant views. |

### User workflows

#### 1. Review the portfolio

1. Sign in and select **All Funds**, **Tall Firs**, or **Alumni Fund**.
2. Review performance, benchmark comparison, risk statistics, sector mix, and MTD
   contributors on the Funds dashboard.
3. Open **Stocks** to filter, sort, inspect cost basis and unrealized gains, or export
   the current table to CSV.
4. Open a holding or sector for deeper attribution and research context.

#### 2. Research a current holding

1. Open a holding from the dashboard, holdings table, sector board, or My Coverage.
2. Review its finalized price chart, position weight/value, company metrics, and top
   institutional holders.
3. Move through Thesis, Financials, Earnings, News, Research, and Predictions.
4. From News, flag a relevant article for the current weekly sector submission.

Current holdings use the nightly database snapshot for prices and closed-company
data. Opening a holding therefore does not fan out into live Yahoo Finance requests;
only the News tab refreshes on demand.

#### 3. Research or screen an off-portfolio idea

1. Use the global search bar, or build a screen from a preset or custom filters.
2. Open a result to load its quote, chart, holders, financials, earnings, news, and
   analyst research on demand.
3. Compare the opportunity with owned names without adding it to the portfolio.

Off-portfolio equities use shared TTL caches to avoid repeating the same upstream
requests for every user.

#### 4. Test a portfolio change

1. Choose a fund in **Optimize** and review benchmark-relative diagnostics.
2. Use **What-if** to adjust position weights and see risk update without changing
   the stored portfolio.
3. Use **Optimizer** to add views and constraints, solve for proposed weights, and
   compare the result with the current book and benchmark.

Optimization outputs are analytical proposals only; they do not place trades or
write new holdings to the database.

#### 5. Submit the weekly analyst update

1. Open **My Coverage** to review assigned companies, recent news, and upcoming
   earnings.
2. Flag relevant News-tab articles and add a note, or write a standalone summary.
3. Review the draft for each assigned sector and submit it to the sector lead.
4. Monitor the Inbox for comments and acknowledgement.

Drafts are editable until submission. The weekly deadline is Thursday at 5:00 PM
America/Los_Angeles, and earlier weeks remain available read-only. See
[`SUBMISSIONS.md`](SUBMISSIONS.md) for the detailed state and permission model.

#### 6. Review a sector as a leader

1. Open **Inbox** to see new digests for assigned lead sectors.
2. Read the analyst's flagged items and notes, add comments, and acknowledge the
   submission.
3. Use the status board and weekly history to identify outstanding analysts.

Sector access comes from an explicit leadership assignment, independent of the
member's WorkOS role and personal ticker coverage. Admins can review every sector.

#### 7. Administer the organization

1. Invite a member from **Organization** and assign Analyst, Sector Leader, or Admin.
2. Assign covered companies and their UOIG sectors.
3. Assign sector-leadership responsibility separately from company coverage.
4. Use the directory and submission board to monitor ownership and workflow status.

## Market-data behavior

The application intentionally separates portfolio monitoring from exploratory
research to limit yfinance traffic and keep production stable on a single Render IP.

### Owned holdings

- Prices, dividends, fundamentals, benchmark data, and stock-tab snapshots refresh
  once nightly after the U.S. market close.
- Only finalized closing bars enter the portfolio price store; there is no backend or
  frontend intraday price poller.
- API routes for owned holdings read from Postgres and do not fall through to Yahoo
  when a snapshot is missing. The previous last-known-good snapshot remains usable if
  part of a nightly refresh is throttled.
- News is the only short-lived holding datum. It loads when the News tab is opened and
  uses a shared ten-minute cache.

### Unowned equities

- Quotes, price series, holders, financials, earnings, news, and research load from
  yfinance on demand.
- Shared database-backed TTL caches prevent repeated upstream requests across users
  and backend restarts.
- Typed rate-limit errors stop immediately instead of retrying a blocked IP; transient
  errors retain bounded retry/backoff and invalid Yahoo crumbs are reset.

### Scheduled jobs

[`nightly-refresh`](.github/workflows/refresh.yml) runs at 06:00 UTC and, in order:

1. Appends finalized prices and dividends and updates fund/benchmark history.
2. Refreshes fundamentals for current positive-share holdings.
3. Refreshes last-known-good financial, earnings, holder, and research snapshots.

The workflow requires the same `DATABASE_URL` used by the deployed backend. The
fundamentals and snapshot stages are intentionally non-fatal so a Yahoo issue cannot
invalidate a successful price refresh.

[`keep-alive`](.github/workflows/keepalive.yml) pings only `/api/health` every ten
minutes to reduce Render free-tier cold starts. It does not request market data or
affect yfinance usage.

## Architecture

```text
Browser
  └─ React + Vite frontend (Vercel)
       └─ FastAPI JSON API (Render)
            ├─ Supabase Postgres
            │    holdings, prices, dividends, fundamentals, caches,
            │    submissions, inbox messages
            ├─ WorkOS
            │    sessions, invitations, roles, directory metadata
            ├─ yfinance / Alpha Vantage / Kalshi
            │    market data, benchmark constituents, prediction markets
            └─ Anthropic
                 contextual chat and managed market-analysis agent

GitHub Actions
  └─ nightly refreshes write directly to the same Supabase database
```

The Docker image builds the React app and lets FastAPI serve both the SPA and API on
one port. The production split deployment instead serves `web/dist` from Vercel and
uses `VITE_API_BASE` to reach Render.

### Repository layout

```text
api/        FastAPI routes, auth gate, submissions API, and SPA mount
web/        React/Vite terminal UI
src/        analytics, authentication, ingestion, caching, and database model
scripts/    seed, migrate, reconcile, refresh, fundamentals, and snapshot jobs
tests/      backend unit and integration tests
data/       local SQLite database and generated data (git-ignored)
```

## Authentication and roles

The application is invite-only. WorkOS supports Google OAuth and email/password,
including verification and password reset. Except for health and authentication,
every API route requires a valid session.

| Role | Application permissions |
|---|---|
| **Analyst** (`member`) | Use the terminal, view assigned coverage, draft and submit weekly sector updates, and receive acknowledgement messages. |
| **Sector Leader** | Use the terminal and review submissions for explicitly assigned lead sectors. |
| **Admin** | Invite members, change roles, manage company coverage and leadership assignments, and review all sector submissions. |

See [`AUTH_SETUP.md`](AUTH_SETUP.md) for WorkOS provisioning and
[`DEPLOYMENT_PLAN.md`](DEPLOYMENT_PLAN.md) for the Vercel/Render/Supabase setup.

For local UI development only, `UOIG_AUTH_DISABLED=1` bypasses authentication. Never
set it in production.

## Development

### Prerequisites

- Python 3.12
- Node.js 20+
- npm
- A local SQLite database or Supabase `DATABASE_URL`

### Run with hot reload

```bash
python -m pip install -r requirements.txt
python -m uvicorn api.main:app --port 8000

npm --prefix web install
npm --prefix web run dev
```

Open `http://localhost:5173`. Vite proxies `/api` to `http://localhost:8000`.

### Run as one production-style server

```bash
npm --prefix web run build
python -m uvicorn api.main:app --port 8000
```

Open `http://localhost:8000`.

### Run with Docker

```bash
docker build -t uoig-terminal .
docker run --rm -p 8000:8000 \
  -e DATABASE_URL=postgresql://... \
  -e WORKOS_API_KEY=... \
  -e WORKOS_CLIENT_ID=... \
  -e WORKOS_COOKIE_PASSWORD=... \
  -e WORKOS_ORG_ID=... \
  uoig-terminal
```

## Data and operations

SQLite is the local default at `data/portfolio.db`. Setting `DATABASE_URL`—or using
the git-ignored `supabase.url.txt` fallback—switches the same query layer to Postgres.
Use a Supabase pooler URI in hosted environments.

```bash
python -m scripts.seed_db                 # seed holdings from Portfolio Holdings.xlsx
python -m scripts.migrate_to_postgres     # copy the local store to Postgres/Supabase
python -m scripts.refresh                 # incremental closing prices and dividends
python -m scripts.refresh --full          # full price-history backfill
python -m scripts.fundamentals            # current-holding fundamentals
python -m scripts.snapshots               # current-holding stock-tab snapshots
python -m scripts.reconcile               # compare the DB with the source workbook
```

The current holdings table remains the source of truth for positions. The transaction
schema exists for future ledger work, but the terminal does not currently provide
trade execution or a complete transaction-derived book.

## Configuration

`config.yaml` defines funds, benchmarks, sector mappings, risk parameters, market-data
pacing, and the default managed-agent ID.

Important deployed variables:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Supabase/Postgres connection shared by Render and GitHub Actions. |
| `WORKOS_API_KEY`, `WORKOS_CLIENT_ID`, `WORKOS_COOKIE_PASSWORD`, `WORKOS_ORG_ID` | Invite-only authentication and organization membership. |
| `WORKOS_REDIRECT_URI`, `FRONTEND_URL` | OAuth callback and post-login destination. |
| `CORS_ORIGINS`, `UOIG_COOKIE_SAMESITE`, `UOIG_COOKIE_SECURE` | Cross-origin session configuration for Vercel → Render. |
| `ANTHROPIC_API_KEY` | Claude chat and managed-agent access. |
| `ANTHROPIC_AGENT_ID` | Optional override for the managed market-analysis agent. |
| `ALPHAVANTAGE_API_KEY` | Optional benchmark-constituent refresh used by optimization. |
| `VITE_API_BASE` | Public Render backend URL embedded in the Vercel frontend build. |

Local secret-file fallbacks are supported and git-ignored. Do not commit API keys,
database credentials, or WorkOS secrets.

## API overview

The frontend consumes the following main route groups:

| Routes | Purpose |
|---|---|
| `/api/data`, `/api/series/*`, `/api/fund-series/*`, `/api/sector-series/*` | Portfolio snapshot and historical analytics. |
| `/api/search`, `/api/quote/*`, `/api/holders/*`, `/api/stock/*` | Owned and off-portfolio equity research. |
| `/api/screener/*` | Screener field catalog and market queries. |
| `/api/optimize/*` | Diagnostics, what-if calculations, and optimizer solves. |
| `/api/coverage/me` | Authenticated analyst coverage dashboard. |
| `/api/flags/*`, `/api/submissions/*`, `/api/inbox/*` | Weekly coverage workflow and messaging. |
| `/api/organization/*`, `/api/profile` | Directory, assignments, roles, and profile management. |
| `/api/chat`, `/api/agent/run*` | Claude chat and asynchronous managed-agent analysis. |
| `/api/auth/*` | Google OAuth, password authentication, invitations, reset, session, and logout. |
| `/api/health` | Public backend health/configuration check. |

## Validation

```bash
python -m pytest -q
npm --prefix web run build
```

Tests use temporary databases and mocked external services where applicable; they do
not submit real WorkOS messages or execute trades.
