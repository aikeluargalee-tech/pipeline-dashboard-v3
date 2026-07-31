#!/usr/bin/env python3
"""
PFC-3L Signal Enricher — post-processes signal.json with data-driven
invalidation conditions and informational zones computed from live data.
Runs after signal_engine.py in the pipeline.
"""
import json, os, sys
from datetime import datetime, timezone
from typing import Any

REPO_ROOT = "/home/susiwilee/projects/pipeline-dashboard-v3"
SIGNAL_JSON = REPO_ROOT + "/pfc3l/signal.json"
DATA_JSON = REPO_ROOT + "/packet/data.json"


def build_invalidation(state: str, data: dict) -> list[str]:
    """Compute invalidation conditions from live data."""
    conds: list[str] = []
    enriched = data.get('enriched', {})
    critical = data.get('critical', {})
    reference = data.get('reference', {})
    sr_1h = _parse_sr(reference.get('sr_1h')) if isinstance(reference.get('sr_1h'), str) else (reference.get('sr_1h') or {})
    sr_1d = _parse_sr(reference.get('sr_1d')) if isinstance(reference.get('sr_1d'), str) else (reference.get('sr_1d') or {})
    fund = enriched.get('funding_rate', 0)
    oi_d = critical.get('oi_delta_5m', 0)
    taker = enriched.get('taker_buy_ratio', 0.5)

    if 'LONG' in state:
        supp = sr_1h.get('support') or sr_1d.get('support')
        if supp:
            conds.append(f"Price closes below ${supp:,.0f} (1H support)")
        else:
            conds.append("Price closes below nearest S/R support")
        conds.append(f"Funding flips >+0.01% (currently {fund*100:.3f}%)")
        conds.append("Spot CVD turns negative for 2+ consecutive intervals")
        conds.append(f"Taker buy ratio drops below 45% (currently {taker*100:.1f}%)")

    elif 'SHORT' in state:
        res = sr_1h.get('resistance') or sr_1d.get('resistance')
        if res:
            conds.append(f"Price closes above ${res:,.0f} (1H resistance)")
        else:
            conds.append("Price closes above nearest S/R resistance")
        conds.append(f"Funding flips <-0.01% (currently {fund*100:.3f}%)")
        conds.append("Spot CVD turns positive for 2+ consecutive intervals")
        conds.append(f"Taker buy ratio rises above 55% (currently {taker*100:.1f}%)")

    elif state == 'NO_TRADE':
        conds = [
            "3+ gates (P, F, C, L) simultaneously align",
            "Data quality score ≥ 60",
            "Clear directional catalyst with no vetoes active",
        ]

    elif state == 'DATA_UNRELIABLE':
        conds = [
            "All critical feeds return within 5 minutes",
            "No timestamp sequence gaps detected",
            "Minimum 2 critical feeds confirmed healthy",
        ]

    # Universal invalidation conditions (apply to all signal states)
    universal = [
        f"OI 5m delta spike beyond ±5% (currently {oi_d:.1f}%)",
        "Catalyst expires or is corrected at source",
    ]
    conds.extend(universal)
    return conds


def _parse_sr(sr_val):
    """Parse S/R string format 'S: 64000 | R: 66000' into dict."""
    result = {}
    if not sr_val or not isinstance(sr_val, str):
        return result
    parts = sr_val.split("|")
    for p in parts:
        p = p.strip()
        if p.startswith("S:"):
            try:
                result['support'] = float(p.split(":")[1].strip())
            except (ValueError, IndexError):
                pass
        elif p.startswith("R:"):
            try:
                result['resistance'] = float(p.split(":")[1].strip())
            except (ValueError, IndexError):
                pass
    return result

def build_zones(data: dict) -> list[dict]:
    """Compute informational zones: nearest S/R bands + VP POC."""
    enriched = data.get('enriched', {})
    reference = data.get('reference', {})
    critical = data.get('critical', {})
    price = enriched.get('price', 0) or (data.get('header', {}).get('price', 0))
    if not price or price <= 0:
        return []
    sr_1h = _parse_sr(reference.get('sr_1h')) if isinstance(reference.get('sr_1h'), str) else (reference.get('sr_1h') or {})
    sr_1d = _parse_sr(reference.get('sr_1d')) if isinstance(reference.get('sr_1d'), str) else (reference.get('sr_1d') or {})
    vp_poc = critical.get('vp_poc')

    zones: list[dict] = []
    for key, label in [('support', 'S'), ('resistance', 'R')]:
        for tf, tn in [(sr_1h, '1H'), (sr_1d, '1D')]:
            v = tf.get(key)
            if v and v > 0:
                dist = round((v - price) / price * 100, 2)
                zones.append({
                    'price': int(v),
                    'label': f'{tn} {label}',
                    'dist_pct': dist,
                    'side': 'above' if dist > 0 else 'below',
                })
    if vp_poc and vp_poc > 0:
        dist = round((vp_poc - price) / price * 100, 2)
        zones.append({
            'price': int(vp_poc),
            'label': 'VP POC',
            'dist_pct': dist,
            'side': 'above' if dist > 0 else 'below',
        })

    zones.sort(key=lambda z: abs(z['dist_pct']))
    return zones[:5]


def main():
    if not os.path.exists(SIGNAL_JSON):
        print("signal.json not found, skipping enrich", file=sys.stderr)
        sys.exit(0)
    if not os.path.exists(DATA_JSON):
        print("data.json not found, skipping enrich", file=sys.stderr)
        sys.exit(0)

    with open(SIGNAL_JSON) as f:
        signal = json.load(f)
    with open(DATA_JSON) as f:
        data = json.load(f)

    state = signal.get('signal', {}).get('state', 'NO_TRADE')

    inval = build_invalidation(state, data)
    zones = build_zones(data)

    signal['signal']['invalidation_conditions'] = inval
    signal['signal']['informational_zones'] = zones
    signal['enriched_at'] = datetime.now(timezone.utc).isoformat()

    with open(SIGNAL_JSON, 'w') as f:
        json.dump(signal, f, indent=2)

    print(f"enrich_pfc3l: state={state} inval={len(inval)} zones={len(zones)}")


if __name__ == '__main__':
    main()
