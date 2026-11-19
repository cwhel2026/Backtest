# Video strategy specification (code audit)

**Scope:** `video_liquidity_sweep` and `video_anchor_bos` in `backend/app/backtest/video_strategies.py`, executed via `video_execution.py` and `video_backtest.py`.

**Important:** Original teaching videos are **not** in this repository. Rules marked *unconfirmed* are engineering interpretations aligned with the ported reference module, not claims about video content.

---

## Shared mechanics (both strategies)

| Rule | Status | Notes |
|------|--------|--------|
| Pivot definition (left/right bars, unique extreme) | **Implemented** | Confirmed at index `j + pivot_right` (no future pivot leak). |
| Fib entry on impulse range | **Implemented** | `fib_retracement` default **0.618**; `0.595` etc. via `entry.fib_ratio` only. |
| Limit price tick rounding | **Implemented** | Long limit rounded down; short limit rounded up. |
| Structural stop beyond impulse extreme + buffer ticks | **Implemented** | `stop_buffer_ticks`. |
| Target = entry ± R× risk | **Implemented** | `reward_risk` (default 2). |
| Min impulse width | **Implemented** | Reject if range `< 4 ticks`. |
| Order expiry in bars | **Implemented** | `expiry_bars` / `order_expire_bars`. |
| Limit fill earliest bar | **Implemented** | Signal bar **+1** onward (no same-bar entry). |
| OHLC limit fill | **Implemented** | Touch = eligibility only (*unconfirmed* vs live DOM). |
| Position sizing | **Implemented** | `tick_value` / `contracts_for_risk`; slippage + commission buffer. |
| MAE / MFE | **Implemented** | Path from fill through exit bar. |
| One position at a time | **Implemented** | Later signals cancelled while trade open. |
| Rollover / gap suppression | **Implemented** | No signals on detected roll/gap indices. |
| Sessions | **Implemented** | `exchange_calendars` CMES; MES/MNQ RTH 08:30–15:15 CT; MGC RTH 08:20–13:30 CT. |

### OHLC execution assumptions (labeled in trade `meta`)

1. Limit touch does **not** guarantee a live fill.
2. No stop/target on the entry fill bar.
3. Same-bar stop+target: **stop before target**.
4. Gap through stop: exit at **open** when worse than stop.

---

## `video_liquidity_sweep`

| Rule | Status | Notes |
|------|--------|--------|
| Prior **completed** session high/low | **Implemented** | Built from `session_keys` (calendar RTH buckets). |
| Sweep above prior high | **Implemented** | High ≥ prior high + `sweep_ticks`; **close < prior high**. |
| Sweep below prior low | **Implemented** | Low ≤ prior low − `sweep_ticks`; **close > prior low**. |
| Optional BOS after sweep | **Configurable** | `require_bos_after_sweep` (default true). |
| BOS definition | **Implemented** | Close breaks last opposite pivot before sweep, pivot confirmed before sweep bar. |
| Impulse leg for fib | **Implemented** | Short: sweep high → min low since sweep; long: symmetric. |
| BOS window timeout | **Implemented** | `bos_window` bars after sweep. |
| `require_bos_after_sweep=false` | **Implemented** | Order on sweep bar without BOS (*config variant — unconfirmed* in videos). |

---

## `video_anchor_bos`

| Rule | Status | Notes |
|------|--------|--------|
| Confirmed pivot tracking | **Implemented** | Updates on pivot **confirmation** index only. |
| Anchor high → long | **Implemented** | Close crosses above pivot high vs prior bar close. |
| Anchor low → short | **Implemented** | Close crosses below pivot low. |
| Opposite pivot for impulse | **Implemented** | Uses last opposite pivot before signal. |
| One order per anchor pivot | **Implemented** | `used` set on `(kind, anchor_j)`. |
| Opposite pivot must predate signal | **Implemented** | `opp_j < i`. |

---

## Configuration fields (`entry` block)

| Field | Default | Purpose |
|-------|---------|---------|
| `fib_ratio` | 0.618 | Baseline Fib; alternatives explicit only |
| `reward_risk` | 2 | Target distance |
| `stop_buffer_ticks` | 2 | Stop beyond structure |
| `sweep_ticks` | 1 | Sweep penetration |
| `pivot_left` / `pivot_right` | 3 | Pivot windows |
| `order_expire_bars` | 12 | Limit life |
| `bos_window` | 20 | Sweep → BOS timeout |
| `require_bos_after_sweep` | true | Sweep-only variant when false |

---

## Known limitations

- No tick/L2 data; intrabar ordering beyond documented assumptions.
- Continuous contract series may gap at rolls (suppressed, not stitched).
- Video copy / discretionary nuances (time filters, news, discretion) not modeled unless added to spec.