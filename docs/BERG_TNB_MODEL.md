# Berg TNB Model v1 (`berg_tnb_model_v1`)

## PDF availability

**The attached PDF is not in this repository.** Implementation follows the written specification supplied in the product brief. Upload the PDF to `docs/source/berg_tnb_setup.pdf` (or similar) to enable line-by-line source verification.

## Rule classification legend

| Tag | Meaning |
|-----|---------|
| **PDF-explicit** | Stated in the user-provided brief (proxy for PDF until file is added) |
| **Interpretation** | Operational rule chosen where PDF silent |
| **Experimental** | Deliberately optional variant |
| **Unresolved** | Needs PDF / author confirmation |

## Pipeline (state machine)

| State | Tag | Rule |
|-------|-----|------|
| 4H bias from fractal BOS | PDF-explicit / Interpretation | Close above/below confirmed fractal; fractal = **configurable approximation** (Rachel_T **Unresolved**) |
| Session measurement 00:00–08:00 / 08:00–13:00 GMT | PDF-explicit | Profiles `pdf_indices`, `pdf_forex` |
| Previous session liquidity level | PDF-explicit | Bullish: session low; bearish: session high |
| Sweep | PDF-explicit | Exact touch allowed (`allow_exact_sweep_touch=true`) |
| First reversal candle | Interpretation | Close > open bullish; doji via `doji_mode` |
| 0.079 fakeout fib | PDF-explicit | Separate anchors from entry fib |
| 5m BOS after fakeout | PDF-explicit | Close break; must follow fakeout |
| Entry fib 0.500–0.618 | PDF-explicit / Experimental | Default **0.618**; others via config only |
| Stop/target | Interpretation | **Exit profiles** — not claimed as universal Berg rules |

## Sessions

| Profile | Use |
|---------|-----|
| `pdf_indices` | Asia 00:00, London 08:00, NY 14:30 GMT |
| `pdf_forex` | NY 13:00 GMT |
| `cme_futures_research` | Labelled CME RTH experiment — **not** PDF equivalent |

DST: **Interpretation** — PDF markers stored as UTC wall times without DST adjustment.

## Defaults

```json
{
  "entry.type": "berg_tnb_model_v1",
  "entry.session_profile": "pdf_indices",
  "entry.setup_preset": "new_york_setup",
  "entry.fib_fakeout_ratio": "0.079",
  "entry.entry_fib_ratio": "0.618",
  "exit_meta.profile": "structural_rr",
  "exit_meta.reward_risk": "2"
}
```

## Execution

Reuses `video_strategies.simulate` / shared OHLC assumptions. Limit touch = eligibility only.

`execution_scenario` values (research labels):

- `ohlc_conservative` (default)
- `same_bar_exits` — **Experimental** (not default)

## Research matrix

See `berg_tnb/research.py` — baseline cell isolated; counted experimental variants for multiple-testing awareness.

## How to run first backtest

1. Ingest validated **5m** MNQ/MES/MGC dataset (Engine 3.0).
2. Seed library or create strategy with `entry.type: berg_tnb_model_v1`.
3. Run backtest from UI or API (`POST /api/v1/backtests`).
4. Inspect `meta.berg_timeline` on trades and warnings.

## Compare three strategies

1. Run backtests for video sweep, video anchor, and Berg on the **same dataset** and assumptions.
2. `GET /api/v1/berg-tnb/compare?run_ids=<id1>,<id2>,<id3>`
3. Or open **Strategy Compare** dashboard page.

## API

- `GET /api/v1/berg-tnb/spec-template`
- `POST /api/v1/berg-tnb/preview-timeline`
- `GET /api/v1/berg-tnb/compare?run_ids=...`

## Limitations

- No PDF file in repo — **Unresolved** rules remain.
- Rachel_T fractals unverified.
- Single-order-per-setup entry fib updates simplified (full dynamic amend rules: **Interpretation** partial).
- Dashboard chart replay is JSON timeline from backtest meta (no video).