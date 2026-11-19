# Databento — MNQ, MES, MGC (five-year research prep)

## Status (honest)

PROP EDGE AI is **prepared** to import licensed GLBX.MDP3 `ohlcv-1m` for **MNQ.c.0**, **MES.c.0**, **MGC.c.0**, validate, persist to Railway `/data` parquet, derive 5m/15m/1h/4h, and gate backtests on `genuine_for_research`.

**E2E success is not claimed until you complete a real import and backtest on Railway** with `DATABENTO_API_KEY` set.

## Import after purchase (recommended)

**Option A — retrieve batch (preferred)**  
`/market-data/import` → **Databento purchase** → pick a **done** batch job → **Import selected batch**. Uses `batch.list_jobs` + `batch.download` only (no `submit_job`).

**Option B — upload from iPhone**  
Save `.dbn` / `.dbn.zst` files to Files → same page → **Upload from iPhone** → chunked upload → processing job.

## Mobile setup (new paid API stream)

1. Sign in → **More** → **Buy via API estimate** (`/market-data/setup`).
2. Confirm Databento + three micros + ~5-year range.
3. Tap **Get Databento estimate** (`metadata.get_cost` per symbol).
4. Check the total (~$36 was quoted externally; your key’s `get_cost` is authoritative).
5. Tick **I approve** → **Start import** (queues one worker job per symbol).
6. Watch jobs in **AI Research**; datasets appear under **Market Data** when `quality_class` is `ready`.

## Railway checklist

| Step | Action |
|------|--------|
| API key | Set `DATABENTO_API_KEY` on the **backend** service (never in the browser). |
| Volume | Mount persistent volume at **`/data`** (see Historical Data Engine docs). |
| Worker | Celery worker must share the same volume + env as API. |
| Postgres | Metadata only; bars live in parquet under `/data/ohlcv/{dataset_id}/`. |
| Budget | Optional `RESEARCH_DATA_BUDGET_GBP` (default £50/mo); use approve + `budget_override` if needed. |

## Storage estimate (five years, 1m, three symbols)

- Order of magnitude: **~0.25–0.6 GB parquet per micro** → **~1–2 GB total** for MNQ+MES+MGC.
- Plan **≥5 GB** on `/data` for headroom, derived timeframes, and future rolls.

## Contract / continuous limitations

- Default series: **continuous unadjusted** (`ROOT.c.0`, `stype_in=continuous`).
- Rollover gaps are **not stitched**; `rollover_events` stored in dataset meta; quality audit flags large jumps.
- This is appropriate for **pattern research**; **outright contract execution fidelity** requires outright/IBKR paths (experimental).

## Symbols & aggregation

| App symbol | Databento continuous | Stored |
|------------|----------------------|--------|
| MNQ | MNQ.c.0 | 1m parquet + derived TFs |
| MES | MES.c.0 | same |
| MGC | MGC.c.0 | same |

4H bias for Berg TNB uses aggregated 4h bars with **no lookahead** (bar open + 4h boundary rule in Phase 2 tests).

## APIs

- `GET /api/v1/market-data/databento/setup`
- `POST /api/v1/market-data/ingest/estimate-bundle`
- `POST /api/v1/market-data/ingest/bundle` (requires `confirm_paid: true`)
- `GET /api/v1/instruments?scope=primary` (MNQ, MES, MGC only in primary UI)

## Not done automatically

- No paid download without your explicit approve on the setup screen.
- No merge/deploy from agents.
- No live trading or copier changes.