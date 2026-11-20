# Interactive Brokers market data (read-only)

PROP EDGE AI uses IBKR **for market data only**. No orders are submitted.

## Prerequisites

- IB Gateway or Trader Workstation with API enabled
- Market data subscriptions for CME micro index and COMEX micro gold
- Network path from Railway/your server to the gateway (often VPN or fixed IP allowlist)

## Environment variables

| Variable | Purpose |
|----------|---------|
| `IBKR_HOST` | Gateway host (never expose in frontend) |
| `IBKR_PORT` | `4002` (paper gateway) or `4001` (live gateway) typical |
| `IBKR_CLIENT_ID` | Unique client id (worker uses +50 offset) |
| `LIVE_LAB_PROVIDER` | `ibkr_stream` for live adapter, `ibkr_fixture` for recorded ticks |
| `IBKR_FIXTURE_PATH` | Optional path to JSONL fixture for offline/CI |
| `LIVE_LAB_SYMBOLS` | Default `MNQ,MES,MGC` |

## Latency labelling

- **Real-time** — only when IB `marketDataType` indicates live (type 1) and connectivity is verified
- **Delayed** — type 3 or unverified stream (default when uncertain)
- **Replay / fixture** — `ibkr_fixture` or `replay` providers

The UI never labels delayed or replay data as real-time.

## Local smoke test (fixture)

```bash
cd backend
export LIVE_LAB_PROVIDER=ibkr_fixture
pytest tests/test_ibkr_fixture_adapter.py -q
```

## Live verification (your machine)

1. Start IB Gateway with **Read-Only API**.
2. Set `IBKR_HOST` / `IBKR_PORT` on the backend service.
3. Set `LIVE_LAB_PROVIDER=ibkr_stream`.
4. Call `GET /api/v1/platform/status` and confirm provider + latency class.
5. Confirm `live_completed_candles` receives new 5m bars.

Live Gateway connectivity **cannot** be verified from Cursor Cloud Agents without your gateway reachable on the network.