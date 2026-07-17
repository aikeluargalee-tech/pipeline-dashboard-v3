# V4 Migration Blueprint
## Pipeline V3 → BTC Intelligence Pipeline V4

**Date:** 2026-07-17
**Source:** Complete V3 inventory (48,393 LOC, 50+ Python files, 34 HTML pages, 30 JSON files, 13 cron jobs)
**Status:** PLANNING — no code modified

---

## 1. Complete Component Classification

### Legend
- **KEEP** — Extract as-is into V4 with minimal changes
- **MODIFY** — Valuable concept, needs restructuring for V4 architecture
- **REBUILD** — Concept is valuable but code quality/architecture requires full rewrite
- **ARCHIVE** — Keep for historical reference, don't migrate to V4
- **REMOVE** — No longer needed

---

### 1.1 Data Producers (`scripts/producers/`)

| File | Lines | Decision | Reason |
|------|-------|----------|--------|
| `realtime_proxies.py` | ~100 | **REBUILD** | Core BTC price source. Needs timestamp tracking, quality score, stale detection |
| `macro_snapshot.py` | ~120 | **REBUILD** | DXY/VIX/US10Y/M2. Needs FRED fallback chain, freshness gates |
| `risk_assets.py` | ~150 | **REBUILD** | SPY/QQQ/MSTR. Fix 24h change calculation bug. Add multi-timeframe |
| `risk_monitor.py` | ~100 | **KEEP** | Black swan + crash precursor scoring. Well-scoped, works |
| `session_brief.py` | ~192 | **ARCHIVE** | Session-specific data. Low value for weekly/monthly focus |
| `bgeometrics_mvrv.py` | ~167 | **REBUILD** | Replace with BRK on-chain (already available, free, no API key) |
| `pipeline.py` | ~187 | **MODIFY** | News analysis via Gemini. Keep concept, remove Gemini dependency |
| `cycle_pipeline.py` | ~100 | **REBUILD** | MVRV-Z/SOPR/NUPL synthesis. Use BRK data directly |
| `profile.py` | ~326 | **REBUILD** | Volume Profile. Core concept, needs cleaner implementation |
| `chart_patterns_main.py` | ~215 | **ARCHIVE** | Candle patterns. Too short-term for V4 focus |
| `candle3_main.py` | ~152 | **ARCHIVE** | 3-candle patterns. Too short-term |
| `markets.py` | ~196 | **KEEP** | Polymarket data. Clean, well-scoped, unique data source |
| `fetch_vp_card.py` | ~424 | **REBUILD** | VP card producer. Core concept, GetClaw-formulas. Needs cleaner structure |
| `fetch_liquidity_status.py` | ~291 | **MODIFY** | Liquidity verdict. Good concept, simplify output |
| `fetch_amt_status.py` | ~184 | **REBUILD** | AMT status reader. Hard dependency on AMT feed path |
| `fetch_sigma_status.py` | ~60 | **ARCHIVE** | SIGMA status. External system, separate concern |
| `fetch_trp_status.py` | ~50 | **ARCHIVE** | TRP status. External system, separate concern |
| `detect_regime.py` | ~302 | **MODIFY** | Regime detection. Keep concept, simplify logic |
| `fetch_regime_synthesis.py` | ~467 | **REBUILD** | Regime synthesis. Overly complex, overlaps with regime_classifier.py |
| `fetch_cts.py` | ~285 | **ARCHIVE** | Corporate Treasury Stress. Niche, keep as research module |
| `fetch_beginner_metrics.py` | ~80 | **REMOVE** | Beginner-friendly metrics. Not V4 target audience |
| `fetch_gate0_full.py` | ~245 | **MODIFY** | Gate0 concept. Keep scoring, remove trading signals |
| `btc_sr_bands.py` | ~608 | **MODIFY** | S/R bands. Good concept, too large for single file |
| `confluence.py` | ~100 | **ARCHIVE** | Confluence scoring. Absorbed into other modules |
| `regime.py` | ~100 | **ARCHIVE** | Redundant with regime_classifier.py |
| `candles.py` | ~335 | **ARCHIVE** | Candle computation library. Too low-level for V4 |
| `pivots.py` | ~160 | **ARCHIVE** | Pivot detection. Short-term focus |
| `volume.py` | ~80 | **ARCHIVE** | Volume utilities. Short-term focus |
| `market_data.py` | ~228 | **REBUILD** | Market data library. Useful, but needs restructuring |
| `config.py` | ~80 | **REBUILD** | Configuration. Good pattern, needs V4-appropriate defaults |
| `card.py` | ~60 | **ARCHIVE** | Card formatting. Dashboard-specific |
| `state.py` | ~80 | **ARCHIVE** | Pattern state. Dashboard-specific |
| `logger.py` | ~40 | **KEEP** | Detection logging. Simple, reusable |
| `patterns/` (6 files) | ~400 | **ARCHIVE** | Chart pattern detectors. Too short-term |

### 1.2 Fetch Scripts (`scripts/`)

| File | Decision | Reason |
|------|----------|--------|
| `fetch_etf_flow.py` | **KEEP** | ETF flow via Google News RSS. Proven, works, clean |
| `fetch_market_data.py` | **MODIFY** | Market data fetch. Overlaps with CCXT in producers |
| `fetch_btc_distribution.py` | **ARCHIVE** | Wallet distribution. Replace with BRK on-chain |
| `fetch_skew.py` | **KEEP** | Options skew from Deribit. Clean, valuable |
| `fetch_cot.py` | **KEEP** | COT report. Unique macro data source |
| `fetch_options_full.py` | **MODIFY** | Full options chain. Heavy, keep concept, simplify |
| `fetch_gamma.py` | **ARCHIVE** | Gamma exposure. Niche, unreliable source |
| `fetch_gate0.py` | **ARCHIVE** | Gate0 fetcher. Absorbed by fetch_gate0_full.py |
| `fetch_sr_bands.py` | **MODIFY** | S/R bands. Useful, but overlaps with btc_sr_bands.py |
| `fetch_synthesis.py` | **ARCHIVE** | Synthesis. Absorbed into other modules |
| `capture_heatmap.py` | **ARCHIVE** | Heatmap screenshot. Coinglass-dependent, fragile |
| `capture_v7_images.py` | **ARCHIVE** | V7 heatmap images. Coinglass-dependent, fragile |
| `social_pulse.py` | **ARCHIVE** | X/Twitter. Requires auth, unreliable for V4 |
| `news_aggregator.py` | **MODIFY** | News aggregation. Keep concept, replace Jina API |
| `signal_tracker.py` | **ARCHIVE** | Trading signal tracker. Not V4 focus |
| `resolve_predictions.py` | **ARCHIVE** | Prediction resolution. Trading-focused |
| `corporate_treasury_stress.py` | **ARCHIVE** | CTS. Niche, keep as research module |
| `parse_heatmap.py` | **REMOVE** | Heatmap parser. Coinglass-dependent |
| `generate_verdict_page.py` | **ARCHIVE** | Verdict page generator. Dashboard artifact |

### 1.3 Packet Pipeline (`~/projects/btc-data-packet/`)

| File | Lines | Decision | Reason |
|------|-------|----------|--------|
| `build_packet.py` | 1,312 | **REBUILD** | Core packet builder. Heart of V4. Keep text format, redesign schema |
| `packet_to_json.py` | 840 | **REBUILD** | Web JSON producer. Keep concept, merge with build_packet |
| `regime_classifier.py` | 677 | **REBUILD** | Regime classification. GetClaw-vetted. Keep logic, clean implementation |
| `correlation_producer.py` | 182 | **KEEP** | BTC/SPY correlation. Clean, well-scoped |
| `liq_clusters_producer.py` | 214 | **MODIFY** | Liquidation clusters. Fix VP path, simplify |
| `brk_collector.py` | ~120 | **KEEP** | BRK on-chain collector. Clean, proven, free |
| `macro_short_trigger.py` | 568 | **ARCHIVE** | Macro short signal. Experimental, trading-focused |

### 1.4 AI Factors (`~/projects/ai-factors/`)

| File | Lines | Decision | Reason |
|------|-------|----------|--------|
| `run_all.py` | ~60 | **MODIFY** | Orchestrator. Keep pattern, simplify |
| `signals/s9_s10_macro_roc.py` | 246 | **KEEP** | VIX/US10Y ROC. Clean, proven, valuable |
| `signals/s11_volume_anomaly.py` | 213 | **KEEP** | Volume anomaly. Clean, useful |
| `signals/tripwire_monitor.py` | 247 | **KEEP** | Tripwire thresholds. Good concept |
| `signals/mining_context.py` | 223 | **MODIFY** | Mining/ERCOT. Remove FRED dependency, use BRK |

### 1.5 Playbooks (`playbooks/`)

| Item | Decision | Reason |
|------|----------|--------|
| `regime_gate.py` | **ARCHIVE** | Regime gating. Trading-focused |
| `position_manager.py` | **ARCHIVE** | Position sizing. Trading-focused |
| All 6 playbooks | **ARCHIVE** | Trading strategies. Not V4 objective |
| All 6 config.json | **ARCHIVE** | Playbook configs. Not V4 |

### 1.6 Core Python Files (root)

| File | Lines | Decision | Reason |
|------|-------|----------|--------|
| `collect.py` | 3,612 | **REBUILD** | Monolithic collector. THE biggest problem. Split into 10+ focused modules |
| `detect_only.py` | 290 | **ARCHIVE** | Fast detection mode. Trading-focused |
| `deploy.sh` | 217 | **REBUILD** | Deploy script. Keep pattern, simplify, remove secrets sourcing |
| `test_collect.py` | ~200 | **REBUILD** | Tests. Keep concept, rewrite for V4 |
| `test_detect_only.py` | ~100 | **ARCHIVE** | Tests for archived module |
| `test_resolution.py` | ~100 | **ARCHIVE** | Tests for archived module |
| `verify_metrics.py` | ~100 | **MODIFY** | Metric verification. Keep pattern |
| `set_gate.py` | ~50 | **ARCHIVE** | Manual gate setter. Trading-focused |

### 1.7 HTML Pages / Dashboard

| Item | Decision | Reason |
|------|----------|--------|
| `dashboard/index.html` | **REBUILD** | Main dashboard. Keep as V4 frontend but redesign |
| `packet/index.html` | **REBUILD** | Packet viewer. This IS the V4 product. Full redesign |
| `trap-monitor/index.html` | **MODIFY** | Trap monitor. Move to V4 core intelligence |
| `ai-factors/index.html` | **MODIFY** | AI factors page. Merge into packet or dashboard |
| `verdicts/` (20+ pages) | **ARCHIVE** | Daily verdict pages. Not V4 focus |
| `research/` (34 pages) | **ARCHIVE** | Research articles. Move to separate knowledge repo |
| `methodology/` | **ARCHIVE** | Static content. Not V4 core |
| `glossary/`, `faq/`, `about/`, `contact/`, `privacy/`, `terms/` | **ARCHIVE** | Static pages. Not V4 core |
| `compare/` (4 pages) | **ARCHIVE** | Comparison pages. Not V4 core |
| `track-record/` | **ARCHIVE** | Track record. Not V4 core |
| `events-and-disruptions/` | **ARCHIVE** | Event log. Move to data layer |
| `assets/styles.css` | **REBUILD** | CSS. Keep visual language, rebuild for V4 |
| `assets/nav.js` | **KEEP** | Navigation. Simple, reusable |
| `assets/vp-card.js` | **MODIFY** | VP card renderer. Merge with vp-chart |
| `assets/vp-chart.js` | **MODIFY** | VP chart renderer. Merge with vp-card |
| `index.html` (root) | **ARCHIVE** | Landing page. Redirect to new V4 structure |

### 1.8 JSON Data Files (`data/`)

| File | Decision | Reason |
|------|----------|--------|
| `cycle.json` | **KEEP** | Cycle data. Core metric |
| `macro.json` | **KEEP** | Macro data. Core metric |
| `derivatives.json` | **KEEP** | Derivatives data. Core metric |
| `structural.json` | **KEEP** | S/R and structure. Core metric |
| `sentiment.json` | **KEEP** | Sentiment data. Core metric |
| `positioning.json` | **KEEP** | Positioning data. Core metric |
| `black_swan.json` | **KEEP** | Black swan scoring. Valuable |
| `crash_precursor.json` | **KEEP** | Crash scoring. Valuable |
| `trap_monitor.json` | **KEEP** | Trap detection. V4 core |
| `regime_switch.json` | **MODIFY** | Regime switch. Keep, simplify |
| `liquidity_status.json` | **MODIFY** | Liquidity status. Keep, simplify |
| `gate0.json` | **MODIFY** | Gate0. Keep scoring, remove signals |
| `ai_factors.json` | **KEEP** | AI factors. Core V4 metric |
| `ai_factors_state.json` | **KEEP** | AI factors state. |
| `btc_price.json` | **KEEP** | Price data. |
| `meta.json` | **KEEP** | Meta/run info. |
| `run_status.json` | **KEEP** | Run status. |
| `predictions.json` | **ARCHIVE** | Prediction tracking. Trading-focused |
| `signal_tracker.json` | **ARCHIVE** | Signal tracking. Trading-focused |
| `signal_stats.json` | **ARCHIVE** | Signal statistics. Trading-focused |
| `confidence_tracker.json` | **ARCHIVE** | Confidence tracking. Trading-focused |
| `track-record-summary.json` | **ARCHIVE** | Track record. Trading-focused |
| `playbook_*.json` (6 files) | **ARCHIVE** | Playbook outputs. Trading |
| `patterns.json` | **ARCHIVE** | Chart patterns. Too short-term |
| `supplementary.json` | **ARCHIVE** | Supplementary data. |
| `news_feed.json` | **MODIFY** | News feed. Keep concept, simplify |
| `social_pulse.json` | **REMOVE** | Twitter data. Unreliable |
| `amt_status.json` | **MODIFY** | AMT status. Keep for now |
| `sigma_status.json` | **ARCHIVE** | SIGMA status. External system |
| `trp_status.json` | **ARCHIVE** | TRP status. External system |
| `corporate_treasury_stress.json` | **ARCHIVE** | CTS. Research module |
| `geopolitical_override.json` | **MODIFY** | Keep for event intelligence |
| `manual_gate.json` | **ARCHIVE** | Manual gate. Trading |
| `regime.json` | **ARCHIVE** | Redundant with regime_switch |
| `v7_captures.json` | **REMOVE** | Heatmap captures. Coinglass-dependent |

### 1.9 Cron Jobs (13 total)

| Job | Decision | Reason |
|-----|----------|--------|
| BTC Data Packet (15m) | **KEEP** | Core V4 pipeline |
| Pipeline V3 Deploy (:45) | **REBUILD** | Replace with V4 deploy |
| Pipeline Fast Refresh (:15,:45) | **MODIFY** | Keep ADX gate, simplify |
| AI Factors Runner (:12,:42) | **KEEP** | Pre-packet AI factors |
| VP V3 Deploy (:48) | **MODIFY** | Merge into main deploy |
| TRP Pipeline (hourly) | **MODIFY** | Keep as event intelligence source |
| TRP Watchdog (4h) | **MODIFY** | Keep as event intelligence source |
| Redline BTC (hourly) | **ARCHIVE** | Separate system, don't migrate |
| Heatmap Capture (4h) | **REMOVE** | Coinglass-dependent, fragile |
| Production Health (:55) | **KEEP** | Essential monitoring |
| Governance Reminder (hourly) | **KEEP** | Governance |
| Vault Health (daily) | **KEEP** | Knowledge management |
| Skill Gap Scanner (weekly) | **KEEP** | Meta-maintenance |

---

## 2. Data Source Migration Map

### KEEP as V4 Core Sources

| Source | Current Producer | V4 Path | Critical Fields | Improvements |
|--------|-----------------|---------|-----------------|--------------|
| **Binance** | `realtime_proxies.py` + CCXT in `build_packet.py` | `data_sources/market/binance.py` | Price, bid/ask, spread, volume, klines | Add timestamp validation, freshness gate, quality score |
| **Yahoo Finance** | `risk_assets.py`, `macro_snapshot.py` | `data_sources/macro/yahoo.py` | VIX, SPY, QQQ, MSTR, DXY, US10Y, USDJPY | Add rate-limit awareness, cache layer |
| **FRED** | `macro_snapshot.py` | `data_sources/macro/fred.py` | M2, ERCOT | Add fallback chain, cache |
| **BRK on-chain** | `brk_collector.py` | `data_sources/onchain/brk.py` | MVRV, SOPR, NUPL, hashrate, 16 series | Already well-structured, proven free API |
| **ETF flows** | `fetch_etf_flow.py` | `data_sources/macro/etf_flow.py` | Daily/weekly ETF flow | RSS-based, works |
| **Options/Deribit** | `fetch_skew.py` | `data_sources/derivatives/options.py` | 25-delta skew | Clean, valuable |
| **COT/CFTC** | `fetch_cot.py` | `data_sources/macro/cot.py` | Institutional positioning | Weekly cadence, unique |
| **Polymarket** | `markets.py` | `data_sources/sentiment/polymarket.py` | Prediction markets | Clean, unique |
| **Fear & Greed** | `collect.py` inline | `data_sources/sentiment/fng.py` | F&G value + classification | Simple HTTP fetch |
| **AMT Feed** | `fetch_amt_status.py` | `data_sources/market/amt.py` | CVD, delta, OI, whale, ADX | Batch file read, works |

### ARCHIVE / DON'T MIGRATE

| Source | Reason |
|--------|--------|
| bgeometrics MVRV | Redundant — BRK provides same data free |
| X/Twitter | Requires auth tokens, unreliable, not institutional |
| Coinglass heatmaps | Selenium-dependent, fragile, browser automation |
| Jina News API | Replace with free RSS/Google News |
| Gemini AI analysis | Remove LLM dependency from data pipeline |
| Gamma exposure | Niche, unreliable source |
| Wallet distribution | BRK provides better on-chain data |

### NEW Sources for V4

| Source | Purpose | Priority |
|--------|---------|----------|
| **Truth Social RSS** | Event Intelligence — Trump posts | HIGH |
| **Federal Reserve calendar** | Event Intelligence — FOMC dates | HIGH |
| **SEC/CFTC announcements** | Event Intelligence — regulatory | MEDIUM |
| **Glassnode (optional)** | On-chain verification | LOW |
| **News wire RSS** | Event-driven market moves | MEDIUM |

---

## 3. Packet Field Migration Map

### CRITICAL Tier — KEEP ALL

| Field | Source | V4 Decision |
|-------|--------|-------------|
| `btc_price` | CCXT Binance | **KEEP** — add `price_source`, `price_confidence` |
| `amt_adx` | AMT feed | **KEEP** |
| `amt_mtf` | AMT feed | **KEEP** — add `mtf_staleness_seconds` |
| `candle_delta` | AMT feed | **KEEP** |
| `candle_deltas_6` | AMT feed | **KEEP** |
| `cvd_per_tf` | AMT feed | **KEEP** |
| `oi_per_tf` | AMT feed | **KEEP** |
| `session_cvd` | AMT feed | **KEEP** |
| `oi_absolute_usd_billions` | AMT feed | **KEEP** |
| `taker_ratio_24h` | AMT/binance | **KEEP** |
| `vp_poc` | VP card | **KEEP** |
| `vp_vah` | VP card | **KEEP** |
| `vp_val` | VP card | **KEEP** |
| `vp_shape` | VP card | **KEEP** |
| `vp_state` | VP card | **KEEP** |
| `balance_state` | Pipeline | **KEEP** |
| `balance_width_pct` | Pipeline | **KEEP** |
| `adx_regime` | Pipeline | **KEEP** |

### CONTEXT Tier — KEEP with Additions

| Field | V4 Decision |
|-------|-------------|
| `fng_value` | **KEEP** |
| `vix` | **KEEP** — add `vix_term_structure` |
| `etf_flow_daily` | **KEEP** |
| `etf_flow_weekly` | **KEEP** |
| `coinbase_premium` | **KEEP** — ensure single source, consistent rounding |
| `equities` | **KEEP** — add `spy_qqq_divergence` |
| `dxy` | **KEEP** |
| `us10y` | **KEEP** — add `us2y` for yield curve |
| `oi_change_24h` | **KEEP** |
| `long_short_ratio` | **KEEP** |
| `funding_rate` | **KEEP** |
| `cvd_24h` | **KEEP** |
| `black_swan_score` | **KEEP** |
| `correlation_r` | **KEEP** |
| `liq_clusters` | **KEEP** |
| `perp_basis_pct` | **KEEP** |
| `order_book_top5` | **KEEP** |
| `realized_vol_1h_pct` | **KEEP** |
| `realized_vol_1d_pct` | **KEEP** |
| `mstr_close` | **KEEP** |
| `usdjpy` | **KEEP** |
| `daily_rsi_14` | **KEEP** |

### REFERENCE Tier — KEEP + Restructure

| Field | V4 Decision |
|-------|-------------|
| `sr_1h`, `sr_1d` | **KEEP** |
| `cycle.mvrv_z` | **KEEP** |
| `cycle.sopr` | **REPLACE** with BRK `lth_sopr_24h` |
| `cycle.netflow_7d` | **KEEP** |
| `cycle_composite` | **KEEP** |
| `sth_realized_price` | **KEEP** |
| `options_skew_25d` | **KEEP** |
| `brk.*` (all 16 series) | **KEEP** — expand over time |

### NEW V4 Fields

| Tier | Field | Purpose |
|------|-------|---------|
| CRITICAL | `data_quality_score` | Overall freshness/quality 0-1 |
| CRITICAL | `source_staleness` | Per-source staleness in seconds |
| CONTEXT | `yield_curve_2s10s` | 2Y-10Y spread for recession signal |
| CONTEXT | `anomaly_score` | Market Anomaly Radar output |
| CONTEXT | `anomaly_active_signals` | Which anomalies are firing |
| CONTEXT | `trap_score` | Trap Detection output |
| CONTEXT | `trap_active_signals` | Active trap types |
| CONTEXT | `event_threat_level` | Event Intelligence 0-5 |
| CONTEXT | `event_active` | Active event flags |
| CONTEXT | `lead_lag_map` | Which assets are leading/lagging BTC |
| CONTEXT | `institutional_flow_score` | COT + ETF + options synthesis |
| REFERENCE | `mtf_weekly` | Weekly trend structure |
| REFERENCE | `mtf_monthly` | Monthly trend structure |
| REFERENCE | `lth_sth_cost_basis_ratio` | LTH/STH cost basis comparison |

### REMOVE in V4

| Field | Reason |
|-------|--------|
| `sigma_status` references | External system |
| `trp_status` references | Move to event intelligence |
| Trading signals / verdicts | RAW METRICS ONLY — no verdicts |
| Playbook outputs | Not V4 focus |
| Verdict pages | Archive |

---

## 4. Code Architecture Problems

### Critical (block V4 quality)

| # | Problem | Location | V4 Fix |
|---|---------|----------|--------|
| 1 | **Monolithic collector** | `collect.py` — 3,612 lines | Split into 10+ single-responsibility modules |
| 2 | **Duplicate CCXT fetch** | `build_packet.py` AND `packet_to_json.py` both fetch prices independently | Single `MarketDataProvider` class, shared cache |
| 3 | **Hardcoded paths** | Every file has `/home/maswilee/projects/...` paths | Configuration file + env vars |
| 4 | **Duplicate metric computation** | Coinbase Premium, ETF flow computed in multiple places with different rounding | Single source function per metric |
| 5 | **No data quality layer** | No timestamp validation, no stale detection, no source health | Add `DataQualityEngine` |
| 6 | **Mixed concerns** | `collect.py` does collection + computation + writing + alerting | Separate collection → processing → output |
| 7 | **No schema validation** | JSON outputs have no enforced schema | Pydantic/JSON Schema for all outputs |

### High (reduce maintenance burden)

| # | Problem | Location | V4 Fix |
|---|---------|----------|--------|
| 8 | **No test coverage** | Only `test_collect.py` and `test_detect_only.py` exist | Test every data source and packet builder |
| 9 | **VP path mismatch** | `liq_clusters_producer.py` uses wrong `/tmp/vp_card.json` path | Configuration-driven paths |
| 10 | **ATR sentinel leak** | `atr_normalized` default 2.0 could leak into calculations | Strong typing, None default |
| 11 | **String matching bugs** | `"ACTIVE" in state` matches `INACTIVE` | Enum types, not string matching |
| 12 | **Classification shadowing** | Broad-before-specific condition ordering | Enforce specific→broad in linter |
| 13 | **No graceful degradation** | `bgeometrics_mvrv.py` crashes without API key | Fallback chains for all sources |
| 14 | **Mixed Python versions** | 3.11 and 3.12 both used, __pycache__ for both | Pin to 3.11, clean caches |

### Medium (improve over time)

| # | Problem | Location | V4 Fix |
|---|---------|----------|--------|
| 15 | Duplicated `vp-card.js` + `vp-chart.js` | Two repos | Single source of truth |
| 16 | Audit artifacts in repo | 5 .txt files | Remove, use .gitignore |
| 17 | `.gemini_key` committed | Repo root | Removed, add to .gitignore |
| 18 | `corporate_treasury_stress.log` committed | `data/` | Add to .gitignore |
| 19 | No requirements.txt | V3 root | Standardize dependencies |
| 20 | Cron scripts scattered | `~/.hermes/scripts/` | Consolidate under V4 repo |

---

## 5. V4 Recommended Folder Structure

```
btc-intelligence-v4/
│
├── README.md                     # Project overview, setup, architecture
├── pyproject.toml                # Dependencies, build config
├── requirements.txt              # Pinned deps for cron
├── .gitignore                    # Comprehensive (includes .env, *.key, etc.)
├── config.yaml                   # All paths, thresholds, schedules
│
├── data_sources/                  # DATA ENGINE — Layer 1
│   ├── __init__.py
│   ├── market/
│   │   ├── binance.py            # CCXT: price, klines, orderbook, CVD, OI
│   │   ├── amt_feed.py           # AMT batch file reader
│   │   └── volume_profile.py     # VP data producer
│   ├── macro/
│   │   ├── yahoo.py              # VIX, SPY, QQQ, MSTR, DXY, US10Y, USDJPY
│   │   ├── fred.py               # M2, ERCOT
│   │   ├── etf_flow.py           # ETF flow via RSS
│   │   └── cot.py                # CFTC COT reports
│   ├── derivatives/
│   │   ├── options.py            # Deribit 25-delta skew + open interest
│   │   └── futures.py            # Funding rate, OI, L/S ratio
│   ├── onchain/
│   │   └── brk.py                # BRK: MVRV, SOPR, NUPL, hashrate (16 series)
│   ├── sentiment/
│   │   ├── fng.py                # Fear & Greed
│   │   └── polymarket.py         # Prediction markets
│   └── events/
│       ├── truth_social.py       # Trump posts via RSS
│       ├── fed_calendar.py       # FOMC dates
│       └── news_wire.py          # Headline aggregation
│
├── processing/                    # DATA QUALITY + INTELLIGENCE — Layers 2-3
│   ├── __init__.py
│   ├── quality/                   # LAYER 2 — Data Quality Engine
│   │   ├── validator.py          # Schema validation (Pydantic)
│   │   ├── freshness.py          # Timestamp checks, stale detection
│   │   ├── completeness.py       # Missing data detection
│   │   └── reliability.py        # Source reliability scoring
│   ├── intelligence/              # LAYER 3 — Market Intelligence
│   │   ├── anomaly.py            # Market Anomaly Radar
│   │   ├── traps.py              # Trap Detection (from existing trap_monitor)
│   │   ├── events.py             # Event Intelligence engine
│   │   ├── lead_lag.py           # Lead-Lag Tracker
│   │   ├── black_swan.py         # Black Swan scoring (from existing)
│   │   ├── crash_precursor.py    # Crash Precursor (from existing)
│   │   ├── mtf.py                # Multi-Timeframe Analysis
│   │   └── regime.py             # Regime classifier (from regime_classifier.py)
│   └── ai_factors/               # AI Factors (existing, migrated)
│       ├── s9_s10_macro_roc.py
│       ├── s11_volume_anomaly.py
│       ├── tripwire_monitor.py
│       └── mining_context.py
│
├── packet/                        # DATA PACKET — Layer 4 (THE PRODUCT)
│   ├── __init__.py
│   ├── schema.py                 # Packet JSON schema (Pydantic)
│   ├── builder.py                # Text packet builder (from build_packet.py)
│   ├── json_builder.py           # Web JSON builder (from packet_to_json.py)
│   ├── exporters/
│   │   ├── telegram.py           # Telegram delivery
│   │   ├── web_json.py           # GitHub Pages deploy
│   │   └── file.py               # Local file output
│   └── sources.py                # Source aggregator (from packet_to_json sources)
│
├── dashboard/                     # FRONTEND (optional, minimal)
│   ├── index.html                # V4 dashboard
│   ├── packet.html               # Packet viewer (primary product)
│   ├── traps.html                # Trap monitor
│   ├── css/
│   ├── js/
│   └── assets/
│
├── archive/                       # ARCHIVED V3 ARTIFACTS
│   ├── research/                 # 34 research pages
│   ├── verdicts/                 # Historical verdict pages
│   ├── playbooks/                # Trading playbooks (reference only)
│   ├── static_pages/             # FAQ, glossary, about, etc.
│   └── v3_reference/             # Full V3 code snapshot
│
├── tests/
│   ├── test_data_sources/
│   ├── test_processing/
│   ├── test_packet/
│   └── conftest.py
│
├── scripts/
│   ├── deploy.sh                 # Single deploy script
│   ├── health_check.sh           # Production health
│   └── cron/                     # Cron job definitions
│
└── docs/
    ├── ARCHITECTURE.md
    ├── DATA_SOURCES.md
    ├── PACKET_SCHEMA.md
    └── MIGRATION_NOTES.md
```

---

## 6. Dependency Requirements

### KEEP (Python)

| Package | Purpose | Justification |
|---------|---------|---------------|
| `ccxt` | Exchange data | Irreplaceable for Binance/Kraken/Coinbase |
| `requests` | HTTP calls | Yahoo Finance, FRED, APIs |
| `numpy` | Numerical ops | Correlation, volatility, ATR |

### ADD (Python)

| Package | Purpose | Justification |
|---------|---------|---------------|
| `pydantic` | Schema validation | Type-safe JSON outputs, auto-validation |
| `pytest` + `pytest-cov` | Testing | Essential for V4 quality |
| `pyyaml` | Config | Configuration-driven paths/thresholds |
| `structlog` | Structured logging | Audit trail for data quality |

### REMOVE (Python)

| Package | Reason |
|---------|--------|
| `selenium` | Coinglass-dependent, fragile browser automation |
| `playwright` | Same — browser automation for heatmaps |
| `Pillow` | Only used for heatmap screenshots |

### System

| Tool | Purpose |
|------|---------|
| `git` | Version control |
| `bash` | Cron wrappers |
| `python3.11` | Single pinned version |
| `uv` | Package management |

---

## 7. First 20 GitHub Issues for V4

| Issue | Title | Type | Priority | Depends On |
|-------|-------|------|----------|------------|
| **V4-001** | Create new private repo `btc-intelligence-v4` with folder structure | Setup | P0 | — |
| **V4-002** | Add comprehensive `.gitignore` (`.env`, `*.key`, `*.pem`, `__pycache__`, logs) | Security | P0 | V4-001 |
| **V4-003** | Define universal packet JSON schema (Pydantic) | Architecture | P0 | V4-001 |
| **V4-004** | Build `config.yaml` — all paths, thresholds, schedules externalized | Architecture | P0 | V4-001 |
| **V4-005** | Migrate Binance/CCXT data source with freshness gates | Data Engine | P0 | V4-004 |
| **V4-006** | Migrate Yahoo Finance macro sources (VIX, SPY, DXY, US10Y, MSTR) | Data Engine | P0 | V4-004 |
| **V4-007** | Migrate BRK on-chain collector (16 series) | Data Engine | P1 | V4-004 |
| **V4-008** | Migrate ETF flow, options, COT, Polymarket data sources | Data Engine | P1 | V4-004 |
| **V4-009** | Build Data Quality Engine (timestamp, freshness, completeness, reliability) | Quality | P0 | V4-003 |
| **V4-010** | Rebuild packet text builder (`builder.py`) from `build_packet.py` | Packet | P0 | V4-003, V4-005, V4-006 |
| **V4-011** | Rebuild packet JSON builder (`json_builder.py`) from `packet_to_json.py` | Packet | P0 | V4-003 |
| **V4-012** | Migrate regime classifier from `regime_classifier.py` | Intelligence | P1 | V4-005, V4-006 |
| **V4-013** | Build Market Anomaly Radar framework | Intelligence | P1 | V4-009 |
| **V4-014** | Migrate + redesign Trap Detection from `trap_monitor` | Intelligence | P1 | V4-009 |
| **V4-015** | Build Event Intelligence engine (Truth Social, Fed, news wire) | Intelligence | P2 | V4-004 |
| **V4-016** | Build Lead-Lag Tracker (cross-asset correlation) | Intelligence | P2 | V4-006 |
| **V4-017** | Migrate AI Factors (S9/S10/S11/tripwire/mining) | Intelligence | P1 | V4-004 |
| **V4-018** | Build Multi-Timeframe Analysis engine | Intelligence | P2 | V4-005 |
| **V4-019** | Create V4 packet viewer webpage | Dashboard | P1 | V4-011 |
| **V4-020** | Set up cron jobs for V4 pipeline (packet every 15min, health hourly) | Ops | P1 | V4-010, V4-011 |

### Issue Dependency Graph

```
V4-001 (repo setup)
├── V4-002 (gitignore)
├── V4-003 (schema)
├── V4-004 (config)
│   ├── V4-005 (Binance) ─────────────────────────┐
│   ├── V4-006 (Yahoo) ────────────────────────────┤
│   ├── V4-007 (BRK on-chain)                      │
│   ├── V4-008 (ETF/options/COT/Polymarket)        │
│   └── V4-015 (Event Intelligence)                │
│       └── V4-009 (Data Quality) ←────────────────┤
│           ├── V4-010 (Packet builder) ←──────────┤
│           │   └── V4-020 (Cron jobs)             │
│           ├── V4-011 (JSON builder)              │
│           │   └── V4-019 (Packet viewer)         │
│           ├── V4-012 (Regime classifier)         │
│           ├── V4-013 (Anomaly Radar)             │
│           ├── V4-014 (Trap Detection)            │
│           ├── V4-016 (Lead-Lag)                  │
│           ├── V4-017 (AI Factors)                │
│           └── V4-018 (MTF Engine)                │
```

**Recommended implementation order:**
1. Batch 1 (P0): V4-001 → V4-002, V4-003, V4-004 (foundation)
2. Batch 2 (P0): V4-005, V4-006, V4-009 (data + quality)
3. Batch 3 (P0): V4-010, V4-011 (packet — the product)
4. Batch 4 (P1): V4-007, V4-008, V4-012, V4-013, V4-014, V4-017 (intelligence modules)
5. Batch 5 (P1-P2): V4-015, V4-016, V4-018, V4-019, V4-020 (icing + ops)

---

## 8. Summary Stats

| Category | Keep | Modify | Rebuild | Archive | Remove |
|----------|------|--------|---------|---------|--------|
| Data Producers (27) | 2 | 6 | 9 | 16 | 1 |
| Fetch Scripts (18) | 3 | 4 | 0 | 9 | 2 |
| Packet Pipeline (7) | 2 | 1 | 3 | 1 | 0 |
| AI Factors (5) | 3 | 2 | 0 | 0 | 0 |
| Playbooks (8) | 0 | 0 | 0 | 8 | 0 |
| Core Python (7) | 0 | 1 | 3 | 3 | 0 |
| HTML Pages (60+) | 1 | 4 | 3 | 50+ | 0 |
| JSON Data (37) | 13 | 6 | 0 | 14 | 2 |
| Cron Jobs (13) | 6 | 5 | 1 | 1 | 1 |
| **TOTAL** | **30** | **29** | **19** | **102** | **6** |

**V4 core will extract ~78 files from the original ~186+ files.** The rest stay archived for reference.

---

## 9. What Does NOT Change

These V3 architectural decisions were correct and carry forward:

1. **RAW METRICS ONLY mandate** — packet contains zero verdicts, signals, or suggestions
2. **`data.json` as single source of truth** — one URL for all downstream consumers
3. **Multi-exchange CCXT price feed** — Binance/Kraken/Coinbase with fallback chain
4. **Atomic file writes** — tmp + fsync + os.replace pattern
5. **flock-based deploy locking** — prevents concurrent deploy races
6. **Cron-driven architecture** — no long-running daemons, everything stateless
7. **15-minute packet cadence** — proven right for balancing freshness vs cost
8. **BRK as primary on-chain source** — free, MIT-licensed, 54K+ series
9. **Yahoo Finance REST direct** — no yfinance library dependency
10. **GetClaw as designated verdict engine** — packet is data only

---

*End of V4 Migration Blueprint. No code has been modified. Ready for ChatGPT review.*
