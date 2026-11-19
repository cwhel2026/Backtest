# Databento batch import — reliability (pre-deploy)

## Status

Engineering hardening for five-year MNQ/MES/MGC batch import. **Live batch list/download unverified without `DATABENTO_API_KEY`.** E2E acceptance **not** claimed until your purchase is imported on Railway.

## Memory

- DBN decode: `DBNStore.to_df(count=25000)` iterator — no full-file DataFrame.
- 1m parquet: flush every **4000** bars per symbol.
- Derive 5m/15m/1h/4h: **day-by-day** parquet read + `StreamingAggregator` (carry incomplete buckets across days/files).
- Validation: **sampled** audit when row_count > 100k; full timestamp gap scan uses `ts` column only per day file.

Stress test `test_memory_bounded_derive_writes`: 14 trading days × 360 1m bars, day-wise parquet + streaming 5m aggregate; RSS growth **< 512 MB** (synthetic — not a claim about full 5y).

**Railway worker RAM:** recommend **≥ 2 GB** for import worker; **≥ 4 GB** safer for derive+validate overlap.

## Storage peak (five years, three micros)

Rough plan:

- Raw batch on disk: **~550 MB** (your quote)
- Staging copy under `/data/databento_batch/{job_id}/` until `IMPORT_COMPLETE`
- Parquet 1m × 3: **~1–2 GB**
- Derived TFs: **~0.5–1 GB** additional
- **Total peak ~3–4 GB** — mount **≥ 8 GB** on `/data`

API and worker **must share the same volume** or enable `OHLCV_S3_*` mirror so workers hydrate from S3 (`storage_backend.hydrate_dataset_from_remote`).

## Symbology

- `SymbologyResolver` uses `DBNStore.symbology`, symbol columns, and `instrument_id` maps.
- **No silent default** to MNQ/MES/MGC unless file metadata has exactly one research root.
- >5% unmapped rows → hard fail with samples.

## SDK batch API (code paths)

- `batch.list_jobs` / `batch.list_files` / `batch.download` only.
- **`submit_job` is never called** from this codebase.

## Merge stack

1. #51 genuine historical data  
2. #52 mobile UX  
3. #53 Databento MNQ/MES/MGC (+ this reliability commit)

## Railway deploy (you)

1. Same `DATABENTO_API_KEY` on API + worker.
2. Shared `/data` volume on both services **or** S3 mirror env vars.
3. Open `/market-data/import` → **Import Databento Purchase** → done job → import.
4. Monitor **AI Research** job messages (real backend progress).
5. Confirm datasets `ready` + `genuine_for_research` before first backtest.