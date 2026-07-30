#!/usr/bin/env python3
"""Generate AEGIS static JSON files from pipeline data.json."""
import json, os, sys
from datetime import datetime, timezone

DATA_JSON = os.path.join(os.path.dirname(__file__), '..', 'packet', 'data.json')
OUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')

with open(DATA_JSON) as f:
    data = json.load(f)

now_ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
enriched = data.get('enriched', {})
context = data.get('context', {})
critical = data.get('critical', {})
reference = data.get('reference', {})
black_swan = data.get('black_swan', {})

os.makedirs(OUT_DIR, exist_ok=True)

# ── trap_monitor.json ──
signals = context.get('trap_signals', {})
trap_monitor = {
    'ts': now_ts,
    'environment_risk_index': signals.get('total_score', 0),
    'category': signals.get('category', 'NONE'),
    'signals': {
        'S1_PERP_FUNDING': {'score': signals.get('s1', 0), 'description': 'Extreme funding rate'},
        'S2_OI_SPIKE': {'score': signals.get('s2', 0), 'description': 'OI spike (>5% in 1h)'},
        'S3_OI_DIVERGENCE': {'score': signals.get('s3', 0), 'description': 'Price up, OI down'},
        'S4_PREMIUM_DEV': {'score': signals.get('s4', 0), 'description': 'Coinbase premium anomaly'},
        'S5_CVD_DIVERGENCE': {'score': signals.get('s5', 0), 'description': 'CVD vs price divergence'},
        'S6_EXCHANGE_INFLOW': {'score': signals.get('s6', 0), 'description': 'Large exchange inflow'},
        'S7_MINER_SELL': {'score': signals.get('s7', 0), 'description': 'Miner sell pressure'},
        'S8_OPTIONS_PUT': {'score': signals.get('s8', 0), 'description': 'Put/call ratio extreme'},
    },
    'structural_backdrop': signals.get('structural', 'NONE'),
}
with open(os.path.join(OUT_DIR, 'trap_monitor.json'), 'w') as f:
    json.dump(trap_monitor, f, indent=2)

# ── crash_precursor.json ──
crash = {
    'ts': now_ts,
    'composite': black_swan.get('score', 0) / 17.0 if isinstance(black_swan, dict) else 0,
    'status': black_swan.get('status', 'NORMAL') if isinstance(black_swan, dict) else 'NORMAL',
    'signals': [
        {'name': 'VIX_ROC', 'active': enriched.get('vix', 0) > 25, 'value': enriched.get('vix', 0), 'threshold': 25},
        {'name': 'US10Y_ROC', 'active': bool(enriched.get('us10y_spike', False)), 'value': enriched.get('us10y_roc', 0), 'threshold': 0.15},
        {'name': 'DXY_SPIKE', 'active': bool(enriched.get('dxy_spike', False)), 'value': enriched.get('dxy', 0)},
        {'name': 'CRYPTO_CORR', 'active': False, 'value': 0},
        {'name': 'HLOC_BREAKDOWN', 'active': False, 'value': critical.get('atr_pct', 0), 'threshold': 5},
    ],
    'nh': {
        'hashrate': reference.get('hashrate_ehs', 0),
        'hashrate_ath': reference.get('hashrate_ath', 0),
        'drawdown_pct': round((1 - reference.get('hashrate_ehs', 0) / max(reference.get('hashrate_ath', 1), 1)) * 100, 1) if reference.get('hashrate_ehs') and reference.get('hashrate_ath') else 0,
    },
}
with open(os.path.join(OUT_DIR, 'crash_precursor.json'), 'w') as f:
    json.dump(crash, f, indent=2)

# ── cycle.json ──
cycle = {
    'ts': now_ts,
    'mvrv_z': enriched.get('mvrv_z', 0),
    'nupl': enriched.get('nupl', 0),
    'lth_sopr': enriched.get('lth_sopr', 0),
    'puell_multiple': enriched.get('puell', 0),
}
with open(os.path.join(OUT_DIR, 'cycle.json'), 'w') as f:
    json.dump(cycle, f, indent=2)

print(f"aegis_gen: trap_monitor={os.path.getsize(os.path.join(OUT_DIR, 'trap_monitor.json'))}b crash_precursor={os.path.getsize(os.path.join(OUT_DIR, 'crash_precursor.json'))}b cycle={os.path.getsize(os.path.join(OUT_DIR, 'cycle.json'))}b")
