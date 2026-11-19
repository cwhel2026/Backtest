# Phase 2 — Genuine historical futures data

## Repository audit (current)

| Layer | Implementation |
|-------|------------------|
| Ingest | Databento 1m → `ingestion_runner.py`, Yahoo/Finz/IBKR fallbacks |
| Storage | Parquet under `OHLCV_STORE_DIR`, optional S3 mirror, `content_checksum` + `version_tag` |
| Validation | `validate_dataset.py` → READY/WARNING/BLOCKED + `video_readiness` |
| Lineage | `data_lineage.py` → `licensed_databento`, `user_csv`, `free_delayed`, `synthetic_test` |
| Backtest gate | `require_genuine_historical` (default true) + `data_lineage` required |
| Resample | `aggregate_bars` 1m→5m/15m/1h/**4h** |
| 4H lookahead | `bias_for_5m_bar` uses bar open + 4h close before exposing bias |

## PR dependencies (2026-11-19)

Open: #47, #48, #49, #50 — **none merged** on this branch snapshot.

## Recommended source (£0–£50 / month)

**Primary: Databento GLBX.MDP3 OHLCV-1m** on MNQ/MES/MGC continuous **unadjusted** (`MNQ.c.0`, etc.).

Public list rate (Dec 2024 unit pricing PDF): **$70 / GB** for GLBX OHLCV-1m (metered).  
Typical **14 calendar days** of micro index 1m is often **well under £50** but you **must** run `get_cost` with your API key before download (`POST /ingest/estimate-range`).

**Do not** treat Yahoo `=F` continuous as tradable outright prices.

## Provider comparison API

`GET /api/v1/market-data/provider-comparison?days=14`

## Operator workflow (genuine dataset)

1. Set `DATABENTO_API_KEY` on Railway (not done by agents).
2. Historical Data → **MNQ/MES/MGC**, Databento, **1m**, date range.
3. **Estimate cost** → approve → queue job.
4. Confirm dataset shows `data_lineage: licensed_databento`, `genuine_for_research: true`, quality **READY**.
5. Run backtest (assumptions default `require_genuine_historical: true`).
6. Strategy Debugger → verify candles + trades + checksum.

## E2E status on Cloud Agent VM

**Not operational for genuine history here:** `DATABENTO_API_KEY` length 0 on this VM.  
Automated tests use **synthetic CSV fixtures only** — not marketed as real performance.

## Manual setup remaining

- Railway: volume on `OHLCV_STORE_DIR`, `DATABENTO_API_KEY`, optional `GBP_USD_RATE`.
- Alembic migrations through 008 for simulation logs (debugger).
- Merge execution/debugger PRs before production research workflow.