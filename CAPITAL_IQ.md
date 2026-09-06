# Capital IQ price data setup

The dashboard's price boundary is the `daily_prices` table. Held securities,
benchmarks, returns, risk, and charts read that table only. The nightly workflow
fills it from S&P Global Capital IQ; non-held search results use Capital IQ live
and carry a five-minute HTTP cache header without being written to the database.

## Required secrets

Configure these GitHub Actions repository secrets:

- `DATABASE_URL`: the Supabase Postgres connection already used by the app.
- `SDK_USERNAME` and `SDK_PASSWORD`: Capital IQ API credentials.
- `CIQ_SDK_URL`: a private, directly downloadable URL for the extracted
  `spgmi_api_sdk_python-3.0.0.tar.gz` archive. Do not use the public PyPI
  `SPGMICIQ` project; it is a placeholder, not the licensed SDK.

Set the same three Capital IQ variables on the backend host. The container
installs `CIQ_SDK_URL` at startup so `/api/search`, off-portfolio `/api/quote`,
and off-portfolio `/api/series` can use the SDK. Keep the archive private and
confirm that your S&P license permits hosting it at the chosen private URL.

For local development, extract the SDK zip from S&P's support portal, then run:

```powershell
python -m pip install C:\path\to\spgmi_api_sdk_python-3.0.0.tar.gz
$env:SDK_USERNAME = "your-api-username"
$env:SDK_PASSWORD = "your-api-password"
```

## First deployment

Run the `nightly-refresh` workflow manually with `full` enabled. This creates
the schema idempotently and backfills the configured history. Subsequent runs
upsert from each ticker's latest cached date.

Every attempt writes a `price_refresh_runs` row with its status, counts, UTC
timestamps, and per-ticker errors. A partial run exits non-zero so GitHub marks
the workflow as failed instead of hiding missing prices behind a green check.
