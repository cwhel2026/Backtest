# Live Strategy Lab (Phase 3 / 3.1 / 3.2)

## Status

**Phase 3.2B:** incremental Berg FSM resume (`loop_start` + `BergTnbFsmState`), video sweep/anchor incremental engines, runner_state v3, market-event reorder tolerance, strategy readiness matrix on certification dashboard.

**Phase 3.2:** execution accuracy certification package (`services/live_lab/certification/`), market-event integrity gate on ingest, Berg forward runtime snapshots (`berg_forward.py`), Accuracy Certification UI (`/live-lab/certification`). Replay triple-pass + restart fingerprinting in `certify_replay_triple()`; parity comparator documents batch vs incremental differences.

**Phase 3.1:** chronological `IncrementalVideoForwardEngine` (pending orders, amendments, fills, stops, position carry in `runner_state`). Berg/video signals discovered **per closed bar** (`incremental_signals.py`) — not bar-close trade reconciliation.

**IBKR stream adapter:** implemented (`ibkr_stream`); **connectivity unverified** without `IBKR_HOST` + gateway on the worker network.

Default provider: `LIVE_LAB_PROVIDER=replay`. Persisted archive: `live_market_events` + `LIVE_LAB_PROVIDER=event_store` for worker restart recovery.

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
- Berg forward uses deterministic setup IDs and persisted snapshots but still runs `BergTnbEngine` on a growing prefix per step — not a fully isolated single-bar state transition yet. Liquidity sweep / anchor BOS still prefix-scan.
- Certification **CERTIFIED_FOR_PAPER_RESEARCH** means software replay/contract tests passed on fixtures — not profitability or live fill guarantees.
- Live charts on run detail: ledger-first; candle chart API optional follow-up.
- No broker order submission; `IBKR` paper is read-only probe when implemented.

## Merge stack

On branch `cursor/live-strategy-lab-3c6d` — base `cursor/databento-mnq-mes-mgc-3c6d` (or your merged trunk).

Deploy after DB migrations `009`, `010`, `011` (`accuracy_certification_runs`).