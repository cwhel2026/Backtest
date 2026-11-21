# AI Research Arena (PROP EDGE AI 5.1)

## API keys (Railway / server env only)

Never commit keys. Set on the **API + worker** services (worker runs arena cycles).

| Provider | Environment variable | Default model |
|----------|----------------------|---------------|
| OpenAI | `OPENAI_API_KEY` | `OPENAI_MODEL` (default `gpt-4o-mini`) |
| Anthropic | `ANTHROPIC_API_KEY` | `claude-3-5-haiku-latest` |
| Google Gemini | `GOOGLE_AI_API_KEY` | `gemini-2.0-flash` |
| Moonshot Kimi | `MOONSHOT_API_KEY` | `moonshot-v1-8k` |
| DeepSeek | `DEEPSEEK_API_KEY` | `deepseek-chat` |
| xAI Grok | `XAI_API_KEY` | `grok-2-latest` |
| Alibaba Qwen | `DASHSCOPE_API_KEY` | `qwen-plus` |
| Mistral | `MISTRAL_API_KEY` | `mistral-small-latest` |

Optional: `AI_ARENA_ENABLED=true` (default true) — master switch for scheduler.

## Start / stop researchers

1. Deploy migrations **013** and **014** (`alembic upgrade head`).
2. Add at least one API key above.
3. Open **Settings → AI Arena** or `GET /api/v1/ai-arena/providers`.
4. **Test connection**: `POST /api/v1/ai-arena/researchers/{slug}/test-connection`
5. **Activate** (explicit): `PATCH /api/v1/ai-arena/researchers/{slug}/settings` with `{"activated_by_user": true, "enabled": true}`.
6. **Stop**: `PATCH` with `{"enabled": false}` (keeps history).

Budgets default to **$2/day** and **$25/month** per researcher until you raise them in the same PATCH endpoint.

## Queues

- `realtime` — live lab ingest, paper tick
- `research` — backtests, prop search, ingestion
- `ai_arena` — LLM cycles (isolated from ingest)

Run workers: `-Q realtime`, `-Q research`, `-Q ai_arena` (see `railway-start-simple.sh` when merged with production repair).

## Data sent to LLMs

Only **derived statistics** and **experiment summaries** — not licensed raw OHLCV series.

## Validation

Backtest engine gates strategy survival. Cross-AI critiques are **advisory only**.