# Whale Audit — PFC-3L Signal Engine + AEGIS Engine

**Date:** 2026-08-01 (UTC)
**Scope:**
- `src/pfc3l/signal_engine.py` (908 lines, not 858 as briefed)
- `src/pfc3l/enrich.py` (157 lines)
- `src/aegis_engine.py` (325 lines)
- Consumers: `pfc3l/index.html` (fetches `pfc3l/signal.json`), `aegis/index.html` (fetches `data/aegis_state.json`)
- Data source: `packet/data.json` (regenerated ~every 15 min by external pipeline; git log `auto: update packet data`)

**Method:** read all modules; ran both engines in an isolated scratch copy (`.audit_scratch/`, since deleted-attempt left untracked copy in workspace); diffed two consecutive runs; fed edge-case data; compared production `pfc3l/signal.json` byte-semantics against local engine output; traced every data path against the live `packet/data.json` schema and the dashboard JS contracts.

**Headline verdict:** Both engines run without crashing on the current packet, and both are deterministic (signal logic identical across runs; the only variance is wall-clock timestamps). **However, most "live data" wiring is broken: AEGIS computes ~7 of its sections from keys that do not exist in `data.json` (zeros/nulls/empty in every section), and enrich's informational zones are structurally incapable of ever being populated.** No candidate states (`LONG_CANDIDATE`/`SHORT_CANDIDATE`) or watch states fire on current data; output is always `NO_TRADE`/`DATA_UNRELIABLE`-style defaults with empty invalidation lists from the engine itself.

---

## 1. Execution & Determinism

| Check | Result |
|---|---|
| `python3 src/pfc3l/signal_engine.py` (default `packet/data.json`) | Exit 0, clean. `NO_TRADE`, conf 0, dq 100/100 allowed |
| Run twice, diff minus `id`/`ts` | **Identical** — deterministic |
| `python3 src/aegis_engine.py` | Exit 0, writes 4 JSON files; run twice, diff minus `generated`/`generated_human`/`crash_precursor.timestamp`/`trap_environment._collected`/legacy `ts` | **Identical** — deterministic |
| Production `pfc3l/signal.json` vs local engine run | Matches exactly except age-string seconds/minutes — production uses this exact engine + enrich |
| Edge: `{}` empty data | signal_engine exit 0; aegis exit 0 |
| Edge: top-level sections `null` (`"enriched": null, "status": null, ...`) | **signal_engine crashes** — `AttributeError` at line 70 (`status.get`) |
| Edge: `enriched.sr_1h` dict + no `price` key | **aegis_engine crashes** — `ZeroDivisionError` at line 76 (`d_s/ref_price*100`) |

Non-determinism is limited to timestamps (`id`, `ts`, `generated`, `enriched_at`, `timestamp` fields). No randomness, no dict-order dependence (sorting is explicit, sums are order-independent).

**Design note:** `run()` stamps `id` and `ts` at call time (signal_engine.py:848-849). Two runs 1 s apart get different `id` even with identical inputs — fine for caching/ETag purposes, but means the output file changes every run even when nothing else changes.

---

## 2. Wrong Data Paths (HIGH severity — engines read keys that don't exist)

Verified against live `packet/data.json` (top-level keys: `header, critical, context, reference, enriched, ai_factors, regime, heatmap, status, sources`).

### 2.1 AEGIS price — `enriched['price']` doesn't exist
- `src/aegis_engine.py:33` — `price = enriched.get('price', 0)`; the live key is `enriched['btc_price']` (62797.0). `header['btc_price']` also exists; `header['price']` does not.
- **Consequence (live-proven):** `reference_price: 0`, `snapshot.price: 0` in both the fresh sandbox run AND the committed `data/aegis_state.json` (`"price": 0`). Every `$` display on the AEGIS overview shows `—`.
- **Latent crash:** aegis_engine.py:76 `round(d_s/ref_price*100, 2)` divides by `ref_price` (which is 0) whenever `enriched.sr_1h` is a populated dict. Today it is masked only because `enriched['sr_1h']` also doesn't exist (`{}` → `rlvl` stays None). The moment upstream data changes shape (or someone fixes the sr path without fixing the price path), the engine dies with `ZeroDivisionError` (reproduced).
- **Fix direction:** read `enriched['btc_price']`, guard `ref_price > 0` before computing distances.

### 2.2 AEGIS S/R levels — `enriched['sr_1h'/'sr_1d'/'sr_4h']` don't exist
- `src/aegis_engine.py:61,277-279` — expects dicts under `enriched`. Live data has `reference['sr_1h']`/`reference['sr_1d']` as **strings** `"S:  | R: "` (currently empty values!) and flat `enriched['sr_1h_support']`/`sr_1h_resistance` keys (currently `None`).
- **Consequence (live-proven):** `nearest_level: null`, `approved_levels: []` — the "approved levels" section and nearest-level display are always empty. `breakout.level_interaction` is all `—`.

### 2.3 AEGIS trap environment — `context['trap_signals']` never exists
- `src/aegis_engine.py:123,190` — `context.get('trap_signals', {})`; no producer in the repo writes this key (`collect.py` writes `sources['trap_monitor']` and `data/trap_monitor.json` with a different schema: `S1_PERP_FUNDING` … `S8_OPTIONS_PUT`, `score`, `active_traps`).
- **Consequence (live-proven):** `trap_environment.composite: 0`, `status: CLEAR`, all 8 signals inactive with `score: 0`, `latest_verdict` is **always** `NO_ACTIVE_VERDICT` with `trap_probability: 0` and `confidence: 100` (100−0+30 clamped). The trap-detection core of AEGIS is dead code on current data.
- Additionally `sources['trap_monitor']` itself currently carries placeholders (`"score": "?/?", "signals": {…: null}, "collected": ""`), so even the fallback source is degraded upstream.

### 2.4 AEGIS cycle — `enriched['mvrv_z'|'sopr'|'nupl'|'lth_sopr'|'supply_in_profit']` don't exist
- `src/aegis_engine.py:268-273`. Live data carries these under `data/cycle.json` (collect.py `collect_cycle()`: `mvrv_z, nupl, lth_sopr, puell_multiple`) — not in `enriched`.
- **Consequence (live-proven):** `cycle: {all null}` in `aegis_state.json`.

### 2.5 AEGIS crash precursor inputs — wrong keys
- `src/aegis_engine.py:82-86` — `critical['cvd_per_tf']['1h']` (key is **`1H`** uppercase; value is the string `"N/A"`), `critical['atr_pct']` (doesn't exist; live: `enriched['atr_1h_pct']`), `critical['volume_ratio']` (doesn't exist), `critical['oi_delta_5m']` (doesn't exist; live: `critical['oi_per_tf_pct_change']`).
- `src/aegis_engine.py:233-238` — `enriched['rsi']` (doesn't exist; live: `context['daily_rsi_14']`), `enriched['us10y_roc']` (doesn't exist; live: `ai_factors['s10_us10y_roc']`).
- `src/aegis_engine.py:256-262` — `reference['hashrate_ehs'|'hashrate_ath'|'fee_rate'|'difficulty']` don't exist (live `reference` keys: `brk, brk_summary, cycle, cycle_composite, options_skew_25d, sr_1d, sr_1h, sr_1h_inverted, sth_realized_price`).
- **Consequence (live-proven):** `market_evidence` shows `relative_volume 1.0x`, `atr_14 0.00%`, `oi_delta_5m 0.0%`; `crash_precursor` composite 0/NORMAL with `network_health` all zeros. The crash precursor section can never reach ELEVATED/DANGER via OI/ATR/volume/hashrate inputs — only via taker/funding/RSI if those paths were fixed.

### 2.6 PFC-3L catalyst ETF flow — `enriched['etf_flow_daily']` doesn't exist
- `src/pfc3l/signal_engine.py:465` — `enriched.get("etf_flow_daily", 0)`. Live key is `context['etf_flow_daily']` (0.0 in this packet). **The ETF inflow/outflow catalyst branch is dead** — `etf_daily` is always 0 → never `< -200` or `> 200`.

### 2.7 Enrich OI delta — `critical['oi_delta_5m']` doesn't exist
- `src/pfc3l/enrich.py:27` — always `0` → every invalidation line renders `"(currently 0.0%)"` (live-proven in production `signal.json`).

### 2.8 Enrich informational zones — price key wrong → **zones can never populate**
- `src/pfc3l/enrich.py:106-109` — `price = enriched.get('price', 0) or header.get('price', 0)`; neither key exists (both are `btc_price`). `if not price: return []` → **`informational_zones` is always `[]`**.
- Live-proven: production `pfc3l/signal.json` (multiple commits back through `7956c26`, `3d18d55`) has `informational_zones: []`; the dashboard permanently renders "No price zones configured."
- VP POC/VAL/VAH **are** present in `critical` (62653/62648/62672) and S/R values would be parseable from `reference['sr_1h']` strings — the data exists, the code just reads the wrong keys. Reproduced zones working (VP POC, 1H S/R, 1D S/R) when fed `header['price']` in the sandbox.

---

## 3. Data-Format / Value-Contract Mismatches (MEDIUM)

| # | Where | Live data | Engine expects | Effect |
|---|---|---|---|---|
| 3.1 | signal_engine.py:358-362, 406-410 | `critical['delta_trend'] = "STRONG_SELLING"` | `"STRONG_SELL"` / `"STRONG_BUY"` / `"SELL"` / `"BUY"` | CVD trend never contributes ±10/±20 to flow score. Live run: flow NEUTRAL 25 (bull 10, bear 25) with zero CVD contribution despite a strong-selling tape |
| 3.2 | signal_engine.py:355-369 | `critical['cvd_per_tf'] = {"1D":"N/A","4H":"N/A","1H":"N/A"}` (timeframes, strings) | `{"spot": {tf: n}, "perpetual": {tf: n}}` dicts of numbers | Spot-vs-perp comparison always falls into the `else` branch → **unconditional `bull_score += 10`** on every evaluation ("neutral bonus" is bullish-only). The "spot leads perps" and "DERIVATIVES_ONLY" veto are both unreachable on live data |
| 3.3 | aegis_engine.py:82 | `cvd_per_tf` keys `1H/4H/1D` (uppercase) | `'1h'` (lowercase) | `cvd` always 0 → S5 (CVD divergence) can never activate |
| 3.4 | signal_engine.py:560-580 | `reference['sr_1h'/'sr_1d']` are strings `"S:  | R: "` (currently empty values) | dicts with `support`/`resistance` | 1H/1D levels never generated; only VP levels can fire. Even if the collector filled the string, the engine never parses it (enrich.py does parse it — inconsistent handling between the two scripts) |
| 3.5 | enrich.py:20-23, 107-108 | same strings | handles both string/dict | OK mechanically, but the strings are currently empty (`"S:  | R: "`) → fallback generic text ("nearest S/R support") instead of `$62,100` |
| 3.6 | signal_engine.py:457-458 (catalyst `source_quality`) | — | — | `source_quality = min(100, confidence + 40)` is constant ≥40, never derived from data — dead "source quality" accounting |

---

## 4. Logic Bugs (MEDIUM/LOW)

1. **AEGIS `close_beyond_level` inverted/meaningless** — aegis_engine.py:159: `"close_beyond_level": "No" if abs(distance_pct) > 1 else "Yes"`. When no level exists, `distance_pct` defaults to 0 → **"Yes"**, while the same row shows `nearest_level: "—"` and `state: "IDLE"`. Live-proven in sandbox output (`close_beyond_level: "Yes"` with `nearest_level: "—"`). Semantics are also reversed: "Yes" means *close to* the level, not *closed beyond* it; `retest_result` says "N/A (not yet crossed)" in the same breath.
2. **AEGIS `acceptance: CLOSE_TO_LEVEL` with no level** — aegis_engine.py:90-91: `abs(distance_pct) < 0.5` uses the 0-default when `rlvl is None` → "CLOSE_TO_LEVEL" on a page that shows no nearest level. Guard should require `rlvl`.
3. **AEGIS `breakout.distance` shows `0.0%` when no level** — aegis_engine.py:148 uses `distance_pct` (0-default) instead of the rlvl-guarded string; contradicts `nearest_level: "—"`.
4. **signal_engine None-guard gap** — signal_engine.py:70 (`status.get`), and the same pattern for `enriched`/`critical`/`reference`/`context`/`sources`/`header` (`data.get(key, {})` returns `None` when the key exists with null value). `{"status": null, ...}` → `AttributeError` crash (reproduced, traceback at signal_engine.py:70). `enrich.py` has the same pattern (`data.get('enriched', {})`).
5. **AEGIS `data_health` logic** — aegis_engine.py:55-59: *any* entry in `staleness_warnings` flips the whole snapshot to `DATA_DEGRADED`, including informational warnings the signal engine deliberately treats as non-penalizing (see signal_engine.py:126-134 comment). Current packet: `DATA_DEGRADED` solely due to "STALE cycle: missing" + "STALE vp: 79m behind AMT" while `snapshot.price` is 0 — the health banner and the price row contradict each other.
6. **AEGIS `leverage`/`S2` OI spike** — aegis_engine.py:117-119, 199-201: reads `oi_delta` (wrong path, always 0) → `leverage` can only ever be NORMAL / ELEVATED_FUNDING via funding.
7. **Enrich LONG/SHORT S/R labeling** — enrich.py:36, 48: falls back `sr_1h.support or sr_1d.support` but always prints "(1H support)" even when the value came from 1D. Cosmetic.
8. **`generate_levels` score semantics** — signal_engine.py:539-541, 554-556: 1H levels `score = 100 - dist*10`, VP levels `80 - dist*8` — the score formulas are duplicated/hardcoded and can produce scores below `score_min` (60) for distances >4% (VP) — such levels are emitted but can never be "active", inflating the levels list with dead entries. Cosmetic.
9. **`healthy_spot_venues` constant** — signal_engine.py:443: `2 if coinbase_premium is not None else 1` — `coinbase_premium` is always present (0 or value) → always 2. Dead field.
10. **`feed_status` skip on error** — signal_engine.py:96-98: `continue` before `feed_status[feed_key] = fs` → an errored feed (e.g. `sources.redline.error`) never appears in `dq.feeds`, so the dashboard's per-feed table silently omits that row (pfc3l/index.html iterates fixed list `amt, ai_factors, volume_profile, redline, trap_monitor`).
11. **`total_critical_feeds` inconsistent with `healthy_count`** — signal_engine.py:90-92 vs 117-121: `volume_profile` is marked `critical: False` yet counted in `total_critical_feeds` (3), while `healthy_count` only ever counts amt + ai_factors (max 2). Dashboard shows "2/3" where 3 is unattainable, and the "Only N critical feeds healthy (need 2+)" veto (line 122-123) can only trigger when both real critical feeds are down — effectively dead threshold.

---

## 5. Hardcoded Values vs Config (LOW — but inconsistent-by-design)

- `THRESHOLDS["signal"]` (signal_engine.py:45-47) defines `cooldown_minutes`, `max_chase_pct`, `watch_min_components` but `evaluate_signal` calls `T.get("positioning_min", 70)` / `T.get("flow_score_min", 70)` — **config keys that are never defined**; always default 70. Dead config.
- flow "strong" split `75` hardcoded (signal_engine.py:447-449, 454-456) vs `flow.score_min: 70`.
- catalyst "MIXED" at `confidence >= 40` hardcoded (signal_engine.py:482); VIX caution `22`, FNG fear `35` hardcoded (signal_engine.py:472, 478) vs `vix_spike: 25`, `fng_extreme_fear: 20` in config.
- positioning funding thresholds `±0.0001`, `0.0005`, basis `0.5/1.0`, L/S `0.8/0.95/1.2/1.5` all hardcoded (signal_engine.py:202-265).
- `generate_levels`: `dist < 5` and `dist < 1.5` hardcoded (signal_engine.py:549, 555) vs `levels.max_distance_pct: 1.5`.
- AEGIS: all thresholds hardcoded (funding `0.0005`, OI `5%`, taker `0.55/0.45/0.6/0.4`, RSI `75/25`, volume `2x/0.5x`, verdict `0.5/0.375/0.25`, trap `6/3`, `actual_max: 8`, distance `3/1/0.5`).
- No YAML config exists despite the module docstring ("configurable via YAML in Phase 2") — acceptable, but the `.get("positioning_min", …)` keys suggest someone intended it.

---

## 6. Enrich ↔ Dashboard Schema Check

**Zones (enrich.py:113-131 → pfc3l/index.html:767-778):** enrich emits `{price, label, dist_pct, side}`; JS reads `z.price, z.side ('above'|'below'), z.dist_pct, z.label` — **schema matches** ✓ (when zones are non-empty, which they never are today — see 2.8).

**Signal-engine-native zones (signal_engine.py:759-760, 774-775):** for candidates, `informational_zones` is a list of **bare prices** (`[l["price"] ...]`). If enrich doesn't run (or runs before a candidate is generated), the JS would render `z.side === 'above'` → false, `Math.abs(z.dist_pct)` → **NaN**, `undefined` label. Latent schema mismatch — the engine's own zone format ≠ dashboard contract; correctness depends on enrich always running after the engine. Fragile coupling.

**Invalidation (enrich.py:31-74 → JS 758-765):** plain string arrays on both sides ✓. NO_TRADE/DATA_UNRELIABLE get template strings from enrich (live-proven in production signal.json). Candidate states get S/R + funding + CVD + taker + OI strings — the OI value is permanently wrong (2.7).

**Enrich writes `signal['enriched_at']`** — pfc3l/index.html ignores it, harmless. It also **overwrites** whatever invalidation/zones the engine emitted — by design, but note the engine's richer candidate invalidation text (5 bullet strings) is entirely replaced by enrich's own; the two sources must stay in sync.

**Enrich hardcoded absolute path** — enrich.py:8-9: `REPO_ROOT = "/home/susiwilee/projects/pipeline-dashboard-v3"` — unlike signal_engine.py (`Path(__file__)`) and aegis_engine.py (`os.path.dirname(__file__)`), enrich is **unportable**: breaks on any other checkout (CI, another machine) by silently skipping ("signal.json not found" → exit 0). HIGH-ish operational risk, LOW code risk.

---

## 7. Ops / Pipeline Observations

- **`data/aegis_state.json` is stale in the repo** — last committed `2026-07-31T02:26:58Z` (git: `146d4a7`), while the auto-pipeline commits `data/trap_monitor.json`, `data/crash_precursor.json`, `data/cycle.json` every 15 min (latest `3d18d55`). **Production does not run `src/aegis_engine.py`**; the legacy files are produced by `src/aegis_gen.py` (schema of committed `crash_precursor.json` — `nh`, `VIX_ROC` list — matches aegis_gen, not aegis_engine). So the 7-section `aegis_state.json` consumed by `aegis/index.html` is currently generated **never** (or manually, and 12+ h old) — and when it was generated (sandbox/commit), every section was zero/null due to §2.
- **`src/aegis_gen.py` and `src/aegis_engine.py` overlap** — same job, different outputs, only one wired in. Consolidate.
- `pfc3l/signal.json` production output matches this exact engine+enrich pair (verified) — PFC-3L is live; AEGIS is effectively not.
- Packet staleness: `sources['trap_monitor']` is placeholder (`"score": "?/?"`, null signals, empty `collected`), `reference.sr_1h/1d` strings are empty (`"S:  | R: "`) — upstream collector gaps worth a separate audit.

---

## 8. Findings Summary (severity-ordered)

### HIGH
1. **aegis_engine.py:33** — `enriched['price']` wrong key → price 0 everywhere; **and latent ZeroDivisionError at :76** (reproduced) whenever `sr_1h` is populated.
2. **aegis_engine.py:123,190** — `context['trap_signals']` never exists → trap environment + verdict permanently zero; trap core is dead code.
3. **enrich.py:106-109** — zones price from `enriched['price']`/`header['price']` (neither exists) → `informational_zones` **always empty** in production; dashboard permanently shows "No price zones configured."
4. **aegis_engine.py:61,277-279; 268-273; 256-262; 82-86; 233-238** — S/R levels, cycle, network health, market evidence, crash precursor all read nonexistent keys → every section of the 7-section output is zero/null/empty. AEGIS is, on current data, a static zero blob.
5. **signal_engine.py:465** — ETF flow catalyst reads `enriched['etf_flow_daily']` (wrong key) → branch dead.

### MEDIUM
6. **enrich.py:27** — `critical['oi_delta_5m']` wrong key → all invalidation OI lines show 0.0%.
7. **signal_engine.py:358-410** — `delta_trend` value contract mismatch (`STRONG_SELLING` vs `STRONG_SELL`); CVD momentum never scores.
8. **signal_engine.py:355-369** — `cvd_per_tf` shape mismatch (timeframes/`"N/A"` strings vs spot/perp dicts) → unconditional +10 bullish bonus; DERIVATIVES_ONLY veto unreachable.
9. **aegis_engine.py:82** — `'1h'` vs `'1H'` key case mismatch → CVD divergence signal S5 unreachable.
10. **enrich.py:8-9** — hardcoded absolute `REPO_ROOT` (unportable; silently no-ops on other machines).
11. **aegis_engine.py:155-160, 90-91, 148** — no-level defaults (`distance_pct=0`) produce contradictory displays: `close_beyond_level: "Yes"` + `acceptance: CLOSE_TO_LEVEL` + `distance: 0.0%` alongside `nearest_level: "—"`.
12. **signal_engine.py:759-760/774-775 vs pfc3l/index.html:767-778** — engine-native zones are bare prices; dashboard expects `{price, label, dist_pct, side}`. Works only because enrich rewrites them; breaks (NaN) if enrich ever doesn't run.

### LOW
13. signal_engine.py:70 (+enrich) — `.get()` on possibly-null top-level sections → AttributeError crash on malformed packet.
14. Dead config keys `signal.positioning_min`/`flow_score_min`; ~15 hardcoded thresholds diverging from `THRESHOLDS` (see §5).
15. signal_engine.py:90-92/117-121 — `total_critical_feeds` counts non-critical `volume_profile`; "2/3" display and "need 2+" veto semantics off.
16. signal_engine.py:96-98 — errored feeds omitted from `dq.feeds` (dashboard row disappears).
17. aegis_engine.py:55-59 — any staleness warning → DATA_DEGRADED (contradicts signal engine's intentional non-penalizing stance).
18. aegis_state.json stale (12+ h) in production; `aegis_engine.py` not wired into the auto-pipeline (aegis_gen is).
19. Line-count discrepancy: signal_engine.py is 908 lines (brief said 858).

---

## 9. Recommended Fix Order

1. Fix `price`/`btc_price` in aegis_engine.py:33 (+ guard division) and enrich.py:106-109 → zones + prices come alive immediately.
2. Point AEGIS at real data: `sources['trap_monitor']` (or `data/trap_monitor.json`) for S1-S8, `data/cycle.json` for MVRV/SOPR/NUPL, `reference['sr_1h'/'sr_1d']` strings (parse like enrich does) for levels, `context`/`ai_factors` for RSI/US10Y/ETF, `enriched['atr_1h_pct']` + `critical['oi_per_tf_pct_change']` for evidence.
3. Align `delta_trend` values and `cvd_per_tf` shape (either engine or producer — producer is in git history only; engine-side normalization is safer).
4. Fix enrich OI key; make REPO_ROOT relative; have enrich warn loudly (nonzero exit) instead of silent skip.
5. Wire aegis_engine.py into the auto-pipeline (or delete it in favor of aegis_gen) so `aegis_state.json` is fresh; regenerate now.
6. Add null-guards for top-level sections in all three modules; unit-test empty/None packets.

*Scratch artifacts from this audit (untracked): `.audit_scratch/` in the workspace root — safe to delete.*
