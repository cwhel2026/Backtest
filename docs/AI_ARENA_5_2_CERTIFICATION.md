# PROP EDGE AI 5.2 — Production certification guide

## Migrations

Run on deploy (Railway API + workers):

```bash
alembic upgrade head
```

Required revisions: **013** (arena tables), **014** (lineage + global settings), **015** (evolution limits, paper attribution, cycle heartbeat).

## Workers (must be three)

`railway-start-simple.sh` starts:

- `-Q realtime` — live ingest, paper tick (must not run LLM cycles)
- `-Q research` — backtests, search, ingestion
- `-Q ai_arena` — autonomous researcher cycles

## Test tiers

| Tier | What runs | API cost |
|------|-----------|----------|
| **CI mocked** | `test_ai_arena_evolution_e2e.py`, `test_ai_arena.py` | None |
| **Local genuine** | `/ai-arena` → Test connection → Run research now with env keys | Your keys |
| **Railway production** | Same UI after migrate + triple worker | Your keys |

## E2E checklist (genuine provider)

1. `GET /api/v1/platform/deployment-audit` — migration revision ≥ 015
2. Enable `AI_ARENA_ENABLED=true`, configure one provider key
3. `/ai-arena` → Start researcher → Run research now
4. Confirm Postgres: `ai_research_cycles` completed, `ai_experiments` with `parent_experiment_id` when refinements ran
5. Enable global **Paper auto-promotion** if testing forward path
6. After validation tier `validated`, check `paper_slots.arena_attribution` JSON
7. Leaderboard shows historical vs paper columns separately

## Not production-ready until

- At least one full cycle with **real** Databento lineage dataset and **your** provider key completes without worker interrupt
- Forward paper shows attributed fills (when sample ≥ 5 trades for ranking)
- `deployment-audit` green on your Railway project

No live brokerage orders are placed by this system.