# Live Strategy Lab (Phase 3)

## Status

Forward-testing platform with **replay-verified** logic. **No live CME/Databento/IBKR feed tested** on the agent VM (no credentials).

Default provider: `LIVE_LAB_PROVIDER=replay` (deterministic JSONL-style events).

## Architecture

```
Market adapter (replay | delayed_bars | stubs)
    → live_feed_status + incidents
    → candle_engine (1m→5m/15m/1h/4h, incomplete carry in DB)
    → forward_runner (bar-close only, DSL + experimental video/Berg)
    → paper_broker + forward_test_ledger_events
    → PostgreSQL forward_test_runs
```

## Railway

- **API** + **worker** share Postgres; candles/ledger in DB (not shared disk).
- Worker: `live_lab_forward_tick` every 30s when `LIVE_LAB_TICK_ENABLED=true`.
- RAM: **≥ 1 GB** worker for replay; **≥ 2 GB** if delayed bar refresh + multiple runs.
- Secrets: `LIVE_LAB_PROVIDER`, optional `DATABENTO_API_KEY`, `IBKR_HOST`, etc.

## Honest limitations

- Real-time adapters are **stubs** until you connect licensed feeds.
- Video/Berg forward path is **experimental** (bar-close reconciliation; not incremental state machine yet).
- Live charts on run detail: ledger-first; candle chart API optional follow-up.
- No broker order submission; `IBKR` paper is read-only probe when implemented.

## Merge stack

On branch `cursor/live-strategy-lab-3c6d` — base `cursor/databento-mnq-mes-mgc-3c6d` (or your merged trunk).

Deploy after DB migration `009`.