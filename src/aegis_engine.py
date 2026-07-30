#!/usr/bin/env python3
"""
BTC AEGIS State Engine — generate aegis_state.json from pipeline data.json
Replaces the Docker backend (localhost:8000) with static JSON for GitHub Pages.
"""
import json, os, sys
from datetime import datetime, timezone
from typing import Any

DATA_JSON = os.path.join(os.path.dirname(__file__), '..', 'packet', 'data.json')
OUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
OUT_FILE = os.path.join(OUT_DIR, 'aegis_state.json')
STATIC_FILES = [
    os.path.join(OUT_DIR, 'trap_monitor.json'),
    os.path.join(OUT_DIR, 'crash_precursor.json'),
    os.path.join(OUT_DIR, 'cycle.json'),
]

with open(DATA_JSON) as f:
    data = json.load(f)

now_ts = datetime.now(timezone.utc).isoformat()
enriched = data.get('enriched', {})
context = data.get('context', {})
critical = data.get('critical', {})
reference = data.get('reference', {})
status = data.get('status', {})
black_swan = data.get('black_swan', {})
header = data.get('header', {})

price = enriched.get('price', 0)

# ─── Helper ───
def m(v):
    return f"${v:,.0f}" if v else "—"

def pct_str(v, scale=1):
    if v is None: return "—"
    return f"{v*scale:.4f}%"

def ago(ts_str):
    if not ts_str: return "—"
    try:
        ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        s = (datetime.now(timezone.utc) - ts).total_seconds()
        if s < 60: return f"{int(s)}s ago"
        if s < 3600: return f"{int(s/60)}m ago"
        return f"{int(s/3600)}h ago"
    except: return "—"

# ═══════════════════════════════════════
# SECTION 1+2: Overview + Bottom Line
# ═══════════════════════════════════════

# Data health
dq_warnings = status.get('staleness_warnings', [])
if not dq_warnings:
    data_health = "DATA_HEALTHY"
    health_reasons = ["All feeds passed"]
else:
    data_health = "DATA_DEGRADED"
    health_reasons = dq_warnings[:3]

# Nearest level from S/R bands
sr_1h = enriched.get('sr_1h', {})
rlvl = None
ref_price = price
if sr_1h:
    supp = sr_1h.get('support')
    res = sr_1h.get('resistance')
    if supp and res:
        d_s = ref_price - supp
        d_r = res - ref_price
        if abs(d_s) < abs(d_r):
            rlvl = {'price': supp, 'label': '1H Nearest Support', 'kind': 'support',
                    'distance_pct': round(d_s/ref_price*100, 2)}
        else:
            rlvl = {'price': res, 'label': '1H Nearest Resistance', 'kind': 'resistance',
                    'distance_pct': round(d_r/ref_price*100, 2)}

# Breakout validator from critical data
cvd = critical.get('cvd_per_tf', {}).get('1h', 0) or 0
taker = enriched.get('taker_buy_ratio', 0.5)
funding = enriched.get('funding_rate', 0)
oi_delta = critical.get('oi_delta_5m', 0)
atr = critical.get('atr_pct', 0)
volume_ratio = critical.get('volume_ratio', 1.0)

# Level interaction
distance_pct = rlvl['distance_pct'] if rlvl else 0
direction = "APPROACHING_SUPPORT" if (rlvl and rlvl['kind'] == 'support' and distance_pct < 3) else \
           "APPROACHING_RESISTANCE" if (rlvl and rlvl['kind'] == 'resistance' and distance_pct < 3) else \
           "IDLE"

# Evidence
acceptance = "UNCERTAIN"
if abs(distance_pct) < 0.5:
    acceptance = "CLOSE_TO_LEVEL"
elif taker > 0.55:
    acceptance = "BUY_PRESSURE"
elif taker < 0.45:
    acceptance = "SELL_PRESSURE"

participation = "NORMAL"
if volume_ratio > 2:
    participation = "ELEVATED"
elif volume_ratio < 0.5:
    participation = "LOW"

aggression = "BALANCED"
if taker > 0.6:
    aggression = "AGGRESSIVE_BUY"
elif taker < 0.4:
    aggression = "AGGRESSIVE_SELL"

leverage = "NORMAL"
if abs(funding) > 0.001:
    leverage = "ELEVATED_FUNDING"
if abs(oi_delta) > 5:
    leverage = "OI_SPIKE"

# Verdict
trap_env_risk = context.get('trap_signals', {}).get('total_score', 0)
trap_prob = min(trap_env_risk / 8, 1.0)
verdict = "UNCONFIRMED_BREAK" if trap_prob > 0.5 else \
          "TRAP_LIKELY" if trap_prob > 0.375 else \
          "NO_ACTIVE_VERDICT"
risk_action = "DEFENSIVE" if trap_prob > 0.5 else \
              "CAUTION" if trap_prob > 0.25 else \
              "MONITOR"

snapshot = {
    "data_health": data_health,
    "health_reasons": health_reasons,
    "price": price,
    "observed_at": header.get('generated_timestamp', now_ts),
}

latest_verdict = {
    "verdict": verdict,
    "trap_probability": round(trap_prob, 3),
    "confidence": max(0, min(100, 100 - trap_prob*100 + 30)),
    "risk_action": risk_action,
    "evidence": [
        {"label": "Taker Buy Ratio", "value": f"{taker*100:.1f}%", "effect": -taker+0.5},
        {"label": "Funding Rate", "value": pct_str(funding), "effect": abs(funding)*1000},
        {"label": "OI 5m Delta", "value": f"{oi_delta}%", "effect": oi_delta/100},
    ] if trap_prob > 0.1 else [],
}

active_event = {
    "state": "CROSSED" if rlvl and abs(distance_pct) < 1 else "IDLE",
    "direction": "BREAKOUT_LONG" if taker > 0.55 else "BREAKOUT_SHORT" if taker < 0.45 else "NONE",
}

nearest_level = rlvl

# Breakout validator data
breakout = {
    "level_interaction": {
        "state": direction,
        "nearest_level": m(rlvl['price']) if rlvl else "—",
        "distance": f"{distance_pct}%" if rlvl else "—",
        "direction": "Above → resistance test" if (rlvl and rlvl['kind'] == 'resistance') else
                    "Below → support test" if rlvl else "—",
        "bars_observed": 15,
        "close_beyond_level": "No" if abs(distance_pct) > 1 else "Yes",
        "retest_result": "N/A (not yet crossed)",
    },
    "market_evidence": {
        "relative_volume": f"{volume_ratio:.1f}x",
        "taker_buy_sell": f"{taker*100:.1f}% buy",
        "funding_rate": pct_str(funding),
        "oi_delta_5m": f"{oi_delta:.1f}%",
        "atr_14": f"{atr:.2f}%",
    },
    "why_verdict": {
        "acceptance": acceptance,
        "participation": participation,
        "aggression": aggression,
        "leverage": leverage,
        "catalyst": "NONE_DETECTED",
        "environment": f"Trap risk {trap_env_risk}/8" if trap_env_risk > 0 else "Clear",
    }
}

# ═══════════════════════════════════════
# SECTION 3: Trap Environment
# ═══════════════════════════════════════
signals = context.get('trap_signals', {})
env = {
    "composite": signals.get('total_score', 0),
    "actual_max": 8,
    "status": "TRAP_ACTIVE" if signals.get('total_score', 0) >= 6 else
             "CAUTION" if signals.get('total_score', 0) >= 3 else
             "CLEAR",
    "_collected": header.get('generated_timestamp', now_ts),
    "signals": {
        "leverage": [
            {"id": "S1", "label": "Funding Rate Extremity", "active": abs(funding) > 0.0005,
             "value": pct_str(funding), "score": signals.get('s1', 0)},
            {"id": "S2", "label": "OI Spike >5%/1h", "active": abs(oi_delta) > 5,
             "value": f"{oi_delta:.1f}%", "score": signals.get('s2', 0)},
            {"id": "S3", "label": "OI–Price Divergence", "active": False,
             "value": "—", "score": signals.get('s3', 0)},
        ],
        "orderflow": [
            {"id": "S4", "label": "Coinbase Premium Deviation", "active": False,
             "value": "—", "score": signals.get('s4', 0)},
            {"id": "S5", "label": "CVD Divergence", "active": cvd != 0 and ((taker > 0.5) != (cvd > 0)),
             "value": f"CVD {cvd}", "score": signals.get('s5', 0)},
        ],
        "onchain": [
            {"id": "S6", "label": "Exchange Netflow Spike", "active": False,
             "value": "—", "score": signals.get('s6', 0)},
            {"id": "S7", "label": "UTXO Age Band Shift", "active": False,
             "value": "—", "score": signals.get('s7', 0)},
        ],
        "options": [
            {"id": "S8", "label": "Options 25Δ Skew", "active": False,
             "value": "—", "score": signals.get('s8', 0)},
        ],
    },
    "structural_backdrop": "Accumulation Zone" if enriched.get('mvrv_z', 0) < 1 else "Neutral",
}

# ═══════════════════════════════════════
# SECTION 4: Crash Precursor
# ═══════════════════════════════════════
vix_val = enriched.get('vix', 0)
us10y_roc = enriched.get('us10y_roc', 0)
bs_score = black_swan.get('score', 0) if isinstance(black_swan, dict) else 0

cp_signals = {
    "taker": 1 if taker < 0.35 or taker > 0.65 else 0,
    "bid_wall": 0,
    "funding": 1 if abs(funding) > 0.001 else 0,
    "oi_implosion": 1 if abs(oi_delta) > 8 else 0,
    "divergence": 1 if enriched.get('rsi', 50) > 75 or enriched.get('rsi', 50) < 25 else 0,
}
cp_composite = sum(cp_signals.values())
cp_status = "DANGER" if cp_composite >= 4 else "ELEVATED" if cp_composite >= 2 else "NORMAL"

crash_data = {
    "composite": cp_composite,
    "status": cp_status,
    "signals": cp_signals,
    "timestamp": now_ts,
    "_collected": header.get('generated_timestamp', now_ts),
    "network_health": {
        "hash_rate_ehs": reference.get('hashrate_ehs', 0),
        "hash_rate_drawdown_pct": round(
            (1 - reference.get('hashrate_ehs', 0) / max(reference.get('hashrate_ath', 1), 1)) * 100, 1
        ) if reference.get('hashrate_ehs') and reference.get('hashrate_ath') else 0,
        "fee_rate_sat_vb": reference.get('fee_rate', 0),
        "difficulty": reference.get('difficulty', 0),
    },
}

# ═══════════════════════════════════════
# Cycle data
# ═══════════════════════════════════════
cycle = {
    "mvrv_z": enriched.get('mvrv_z'),
    "sopr": enriched.get('sopr'),
    "nupl": enriched.get('nupl'),
    "lth_sopr_24h": enriched.get('lth_sopr'),
    "supply_in_profit_share": enriched.get('supply_in_profit'),
}

# ═══════════════════════════════════════
# Approved Levels (from S/R bands)
# ═══════════════════════════════════════
approved = []
for tf, tf_data in [('1H', enriched.get('sr_1h', {})), ('1D', enriched.get('sr_1d', {})),
                     ('4H', enriched.get('sr_4h', {}))]:
    for kind in ['support', 'resistance']:
        v = tf_data.get(kind)
        if v and v > 0:
            approved.append({
                "price": v,
                "label": f"{tf} {kind.title()}",
                "kind": kind,
                "source": "S/R Bands",
            })

# ═══════════════════════════════════════
# Assemble full state
# ═══════════════════════════════════════
aegis_state = {
    "generated": now_ts,
    "generated_human": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    "reference_price": price,
    "snapshot": snapshot,
    "latest_verdict": latest_verdict,
    "active_event": active_event,
    "nearest_level": nearest_level,
    "breakout": breakout,
    "trap_environment": env,
    "crash_precursor": crash_data,
    "cycle": cycle,
    "approved_levels": approved[:9],
}

os.makedirs(OUT_DIR, exist_ok=True)
with open(OUT_FILE, 'w') as f:
    json.dump(aegis_state, f, indent=2, default=str)

# Also generate the legacy individual files
trap_monitor = {
    "ts": now_ts, "environment_risk_index": env["composite"],
    "category": env["structural_backdrop"], "signals": {
     f"{v['id']}_DESC": {"score": v.get("score", 0), "description": v["label"]}
     for group in env["signals"].values() for v in group
 },
    "structural_backdrop": env["structural_backdrop"],
}
with open(STATIC_FILES[0], 'w') as f: json.dump(trap_monitor, f, indent=2)

with open(STATIC_FILES[1], 'w') as f: json.dump(crash_data, f, indent=2)

with open(STATIC_FILES[2], 'w') as f: json.dump(cycle, f, indent=2)

sizes = [os.path.getsize(f) for f in [OUT_FILE] + STATIC_FILES]
print(f"aegis_engine: state={sizes[0]}b trap={sizes[1]}b crash={sizes[2]}b cycle={sizes[3]}b")
