# Berg TNB Model v1 (`berg_tnb_model_v1`)

## Primary source

**PDF on file:** `docs/source/berg_tnb_setup.pdf` (visual infographic; OCR not available).

Audit date: aligned to PDF strips (session table, steps 2–8, diagrams).

## Rule mapping (PDF → code)

| PDF step | Rule | Tag | Implementation |
|----------|------|-----|----------------|
| 2 | Fractals by **Rachel_T** | **Unresolved** | Williams 2+2 pivot approximation until TV script exported |
| 2 | Bias on **4H** | **PDF-explicit** | `aggregate_bars(..., "4h")` + `bias_4h.py` |
| 2 | BOS = **body close**, not wick | **PDF-explicit** | `close > fractal` / `close < fractal` |
| 3–4 | Session GMT table | **PDF-explicit** | `sessions.py` (`pdf_indices`, `pdf_forex`) |
| 4 | London traders: low **00:00–08:00**; NY: low **08:00–13:00** | **PDF-explicit** | `setup_preset` `london_setup` / `new_york_setup` |
| 4 | Bearish marks **high** not low | **PDF-explicit** | `SessionLevelRecord.liquidity_level` |
| 5 | Revisit **exactly** or past level | **PDF-explicit** | `allow_exact_sweep_touch` (default true) |
| 6 | First **bullish/bearish candle** after sweep | **PDF-explicit** | `WAITING_FOR_REVERSAL_CANDLE` |
| 6 | Fakeout fib **0.079** | **PDF-explicit** | `fib_fakeout_ratio` |
| 6 | Bullish fib high→low; bearish opposite | **PDF-explicit** | `fib.py` orientation |
| 7 | **5m BOS after fakeout** | **PDF-explicit** | `_bos_after_fakeout` + `fakeout.bar_index < i` |
| 8 | Entry fib session extreme → post-BOS extreme | **PDF-explicit** | `current_session_*` + `post_bos_*` |
| 8 | Golden pocket **0.5–0.618** (PDF also lists 0.786 in UI) | **PDF / Experimental** | Default 0.618; config 0.5/0.550/0.595/0.786 |
| 8 | Limit orders | **PDF-explicit** | Shared `video_execution` (PR #47 compatible) |
| — | Stop/target universal rules | **Unresolved** | Research `exit_meta.profile` only |

## Session times (PDF-explicit)

**INDICES:** Asia 00:00, London 08:00, New York **14:30 GMT**  
**FOREX:** Asia 00:00, London 08:00, New York **13:00 GMT**

DST: PDF silent — stored as UTC wall clock (**interpretation**).

## Execution (PR #47 compatibility)

Berg backtests use `video_execution.run_video_orders` (vendored from PR #47 on this branch): order lifecycle, MAE/MFE, tick-value sizing, entry bar before exit, stop-before-target.

Does **not** merge PR #47 into `main` automatically — berg branch carries `video_execution.py` for compatibility.

## Remaining unverified / ambiguous

1. **Rachel_T** exact period / filtering vs 2+2 Williams fractal.
2. **“Current session”** low/high — PDF implies live session box; code tracks from completed measurement through trade (**interpretation**).
3. **Dynamic entry fib updates** until latest trade time — PDF yes; code emits one limit at first post-BOS bar (**partial**).
4. **Backend rules / multi-account** pages in PDF — out of scope for v1 engine.
5. **Prop-specific latest trade time** — not in PDF text (**experimental** via `order_expire_bars`).

## Defaults

Unchanged — see prior `spec-template` API; baseline `pdf_indices` + `new_york_setup` + `0.079` + `0.618`.