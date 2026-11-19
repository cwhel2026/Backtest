# Historical Data Engine 3.0 — implementation report

## Provider audit (classification)

| Provider | Tier | Serious intraday | Notes |
|----------|------|------------------|-------|
| **Databento** | Primary | Yes | `GLBX.MDP3` `ohlcv-1m`, continuous `ROOT.c.0`, official `metadata.get_cost` |
| **CSV import** | Primary | Yes | User files → parquet + quality validation |
| **FinzData** | Fallback | Yes (paid) | HTTP API; free tier daily-only |
| **Yahoo** | Fallback | No | Free delayed; 1m ~7d cap |
| **IBKR** | Experimental | Yes | Gateway historical; network-bound |

## Workflow

1. **Historical Data** dashboard (`/market-data`) → pick MNQ/MES/MGC, Databento, timeframe, days.
2. **Get cost estimate** → `POST /api/v1/market-data/ingest/estimate-range` (Databento `get_cost` when `DATABENTO_API_KEY` set).
3. Check **Approve paid download** → **Queue download** (`confirm_paid: true`).
4. Budget reserved in `research_data_budget_months` (default £50/month via `RESEARCH_DATA_BUDGET_GBP`).
5. Worker ingests 1m, aggregates 5m/15m/30m/1h locally, writes **new dataset version** (parquet + checksum).
6. Quality → `READY` / `WARNING` / `BLOCKED`; video readiness in dataset meta.
7. **Strategy** → run backtest on dataset; BLOCKED datasets rejected.

## Environment variables

- `DATABENTO_API_KEY` — required for licensed downloads and real cost quotes.
- `RESEARCH_DATA_BUDGET_GBP` — monthly cap (default 50).
- `GBP_USD_RATE` — optional; enables GBP display on estimates (not a live FX feed).
- `OHLCV_STORE_DIR` — parquet root (use a volume in production).

## Limitations

- No live FX for GBP — set `GBP_USD_RATE` manually.
- Databento integration tests use mocks; live `get_cost` only when `DATABENTO_LIVE_SMOKE=true` (skipped in CI).
- `exchange_calendars` **CMES** covers exchange schedules; RTH window still comes from instrument `trading_hours`.
- S3 object store hook (`OHLCV_S3_BUCKET`) is metadata-only until a backend driver is added — use Railway volume today.
- Roll metadata is best-effort from Databento symbology; prices are **not** back-adjusted across rolls.
- Yahoo/FinzData/IBKR paths unchanged in structure.

## Hardening pass (calendar, rollover, health)

- **Calendar:** `exchange_calendar.py` + `sessions.py` — CMES holidays/early close, configurable RTH/ETH from instrument hours.
- **Rollover:** `contract_series.py` — continuous unadjusted (default), adjusted/outright flags, roll-gap detection in quality.
- **Databento spec tests:** `test_databento_api_spec.py` asserts SDK params; optional `test_databento_live_smoke.py`.
- **Persistence:** `storage_health.py` + `OHLCV_PERSISTENT_REQUIRED` warns on Railway if store is repo-local.
- **Health API:** `GET /api/v1/market-data/health` + dashboard panel.
- **Video strategies:** session keys from calendar RTH; readiness counts `rth:` sessions; limit rules unchanged in `video_strategies.py`.

## Video strategies

Entry types: `video_liquidity_sweep`, `video_anchor_bos`. Readiness requires multi-session history (sweep) and pivot warm-up (anchor). Zero-trade backtests append diagnostic warnings when data is thin.