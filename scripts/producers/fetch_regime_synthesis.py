#!/usr/bin/env python3
"""
Regime Synthesis Producer — bridges Regime Switch detection with 5-layer signal synthesis.
Reads regime_switch.json (detected regime) + all live data feeds.
Scores 5 layers: Gate, Macro, Structure, Derivatives, Cycle.
Applies regime overlay (DISTRIBUTION/RISK_OFF → force BEARISH).
Outputs data/regime.json (format expected by dashboard Regime Synthesis card).

Decision rules per btc-signal-synthesis skill:
  BULLISH if Bull factors > Bear factors + 2
  BEARISH if Bear factors > Bull factors + 2
  MIXED otherwise
"""
import sys, os, json
from datetime import datetime, timezone

SITE = "/home/maswilee/projects/pipeline-dashboard-v3"
DATA_DIR = os.path.join(SITE, "data")

def load(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None

def emoji_for(verdict):
    v = str(verdict).upper()
    if "BULL" in v:
        return "🟢"
    elif "BEAR" in v or v in ("DRY", "EVAPORATING"):
        return "🔴"
    elif v in ("CAUTIOUS", "TIGHTENED", "THINNING", "RISK_OFF"):
        return "🟡"
    elif v == "NEUTRAL":
        return "🟡"
    return "🟡"


def score_gate(gate0):
    """Gate0 — entry permission layer."""
    if not gate0:
        return {"verdict": "OFFLINE", "emoji": "⚫", "detail": "No Gate0 data"}
    verdict = gate0.get("verdict", "UNKNOWN")
    sources = gate0.get("sources", [])
    detail = ", ".join(sources) if sources else "all clear"
    return {"verdict": verdict, "emoji": emoji_for(verdict), "detail": detail}


def score_macro(macro, amt_status):
    """Macro layer: DXY, VIX, risk assets, ETF flows."""
    if not macro:
        return {"verdict": "OFFLINE", "emoji": "⚫", "detail": "No macro data"}

    signals = []
    bull = bear = 0

    dxy = macro.get("dxy", 100)
    if dxy < 100:
        bull += 0.5
        signals.append(f"DXY {dxy} (tailwind)")
    elif dxy > 105:
        bear += 0.5
        signals.append(f"DXY {dxy} (headwind)")
    else:
        signals.append(f"DXY {dxy} (neutral)")

    vix = macro.get("vix", 20)
    if vix < 15:
        bull += 0.5
        signals.append(f"VIX {vix} (low)")
    elif vix > 30:
        bear += 1
        signals.append(f"VIX {vix} (elevated)")
    else:
        signals.append(f"VIX {vix} (normal)")

    ra = macro.get("risk_assets", {})
    spy_chg = ra.get("SPY", {}).get("change_pct", 0)
    qqq_chg = ra.get("QQQ", {}).get("change_pct", 0)
    if spy_chg > 0 and qqq_chg > 0:
        bull += 0.5
        signals.append("SPY/QQQ positive")
    elif spy_chg < -1 or qqq_chg < -1:
        bear += 0.5
        signals.append("SPY/QQQ negative")

    etf = macro.get("etf_flow", {})
    daily = etf.get("daily_net", 0)
    if daily > 50:
        bull += 0.5
        signals.append(f"ETF +${daily}M")
    elif daily < -50:
        bear += 0.5
        signals.append(f"ETF -${abs(daily)}M")

    detail = "; ".join(signals)

    if bull > bear + 0.5:
        verdict = "BULLISH"
    elif bear > bull + 0.5:
        verdict = "BEARISH"
    else:
        verdict = "NEUTRAL"

    return {"verdict": verdict, "emoji": emoji_for(verdict), "detail": detail}


def score_structure(structural, supplementary):
    """Structure layer: S/R positioning, price vs MA50, magnets."""
    parts = []
    bull = bear = 0

    # Price vs MA50
    price = 0
    ma50 = 0
    if supplementary:
        price = supplementary.get("price", 0)
        ma50 = supplementary.get("ma50", 0)
        if price > 0 and ma50 > 0:
            if price > ma50:
                bull += 1
                pct_above = round((price - ma50) / ma50 * 100, 1)
                parts.append(f"Price above MA50 (+{pct_above}%)")
            else:
                bear += 1
                pct_below = round((ma50 - price) / ma50 * 100, 1)
                parts.append(f"Price below MA50 (-{pct_below}%)")

    # S/R positioning
    if structural:
        sr = structural.get("sr_bands", {})
        for tf in ["1h", "4h"]:
            tfd = sr.get(tf, {})
            if not tfd or tfd.get("error"):
                continue
            tp = tfd.get("current_price", price)
            if not tp or tp <= 0:
                continue
            # Nearest active resistance
            for r in (tfd.get("resistances") or []):
                if r.get("status") == "ACTIVE":
                    dist = (r["center"] - tp) / tp * 100
                    if dist < 1:
                        bear += 0.5
                        parts.append(f"Near {tf.upper()} R ${r['center']:,.0f} ({dist:.1f}%)")
                    break
            # Nearest active support
            for s in (tfd.get("supports") or []):
                if s.get("status") == "ACTIVE":
                    dist = (tp - s["center"]) / tp * 100
                    if dist < 1:
                        bear += 0.5  # Very close to support = could break
                        parts.append(f"Near {tf.upper()} S ${s['center']:,.0f} ({dist:.1f}%)")
                    elif dist < 3:
                        bull += 0.5  # Comfortable above support
                        parts.append(f"{tf.upper()} S below ${s['center']:,.0f} ({dist:.1f}%)")
                    break

        # Magnets
        magnets = structural.get("magnets", {})
        if magnets:
            m_regime = magnets.get("regime", "")
            if m_regime:
                parts.append(f"Mag: {m_regime}")
            sandwich = magnets.get("sandwich", {})
            if sandwich and sandwich.get("width_usd"):
                parts.append(f"Sandwich ${sandwich['width_usd']:,.0f}")

    detail = "; ".join(parts) if parts else "No structural data"
    if bull > bear + 0.5:
        verdict = "BULLISH"
    elif bear > bull + 0.5:
        verdict = "BEARISH"
    elif parts:
        verdict = "HOLDING"
    else:
        verdict = "OFFLINE"
    return {"verdict": verdict, "emoji": emoji_for(verdict), "detail": detail}


def score_derivatives(deriv, liquidity):
    """Derivatives layer: funding, taker, OI, CVD, L/S, Coinbase premium."""
    parts = []
    bull = bear = 0

    # Use liquidity data when available (fresher), fall back to derivatives.json
    taker = None
    cvd = None
    oi_change = None
    funding = None
    cb_premium = None

    if liquidity:
        taker = liquidity.get("taker_buy_ratio")
        oi_delta = liquidity.get("oi_delta", "FLAT")
        funding = liquidity.get("funding_rate")
        cb_premium = liquidity.get("coinbase_premium")

    if deriv:
        if taker is None:
            taker = deriv.get("taker_buy_ratio")
        if funding is None:
            funding = deriv.get("funding_rate", 0)
        if cb_premium is None:
            cb_premium = deriv.get("coinbase_premium")
        cvd = deriv.get("cvd_24h", 0)
        oi_change = deriv.get("oi_change_24h")

    # Taker buy ratio
    if taker is not None:
        if taker > 0.55:
            bull += 1
            parts.append(f"Taker {taker:.3f} (buy dominant)")
        elif taker < 0.45:
            bear += 1
            parts.append(f"Taker {taker:.3f} (sell dominant)")
        else:
            parts.append(f"Taker {taker:.3f} (neutral)")

    # CVD
    if cvd is not None:
        if cvd > 500:
            bull += 0.5
            parts.append(f"CVD +{cvd:,.0f}")
        elif cvd < -500:
            bear += 0.5
            parts.append(f"CVD {cvd:,.0f}")

    # OI
    if oi_change is not None:
        if oi_change > 3:
            bull += 0.5
            parts.append(f"OI +{oi_change:.1f}%")
        elif oi_change < -3:
            bear += 0.5
            parts.append(f"OI {oi_change:.1f}%")

    # Funding
    if funding is not None:
        if funding < -0.005:
            bull += 0.5
            parts.append(f"FR {funding*100:+.3f}% (shorts pay)")
        elif funding > 0.01:
            bear += 0.5
            parts.append(f"FR {funding*100:+.3f}% (longs crowded)")
        else:
            parts.append(f"FR {funding*100:+.4f}% (neutral)")

    # Coinbase premium
    if cb_premium is not None:
        if cb_premium > 0.5:
            bull += 0.5
            parts.append(f"CB prem +{cb_premium:.1f} (US bid)")
        elif cb_premium < -0.5:
            bear += 0.5
            parts.append(f"CB prem {cb_premium:.1f} (US soft)")

    # L/S ratio
    if deriv:
        ls = deriv.get("long_short_ratio")
        if ls is not None:
            if ls > 2.5:
                bear += 0.5
                parts.append(f"L/S {ls:.2f} (crowded longs)")
            elif ls < 1.2:
                bull += 0.5
                parts.append(f"L/S {ls:.2f} (balanced)")

    detail = "; ".join(parts) if parts else "No derivatives data"
    if bull > bear + 0.5:
        verdict = "BULLISH"
    elif bear > bull + 0.5:
        verdict = "BEARISH"
    else:
        verdict = "NEUTRAL"
    return {"verdict": verdict, "emoji": emoji_for(verdict), "detail": detail}


def score_cycle(cycle):
    """Cycle layer: MVRV-Z, SOPR, netflow, composite."""
    if not cycle:
        return {"verdict": "OFFLINE", "emoji": "⚫", "detail": "No cycle data"}

    parts = []
    bull = bear = 0

    mvrv_z = cycle.get("mvrv_z")
    if mvrv_z is not None:
        if mvrv_z < 0:
            bull += 1
            parts.append(f"MVRV-Z {mvrv_z:.2f} (undervalued)")
        elif mvrv_z > 2:
            bear += 0.5
            parts.append(f"MVRV-Z {mvrv_z:.2f} (overvalued)")
        else:
            parts.append(f"MVRV-Z {mvrv_z:.2f}")

    sopr = cycle.get("sopr")
    if sopr is not None:
        if sopr < 1:
            bull += 0.5
            parts.append(f"SOPR {sopr:.4f} (losses)")
        else:
            parts.append(f"SOPR {sopr:.4f}")

    netflow = cycle.get("netflow_7d")
    if netflow is not None:
        if netflow < -5000:
            bull += 0.5
            parts.append(f"Netflow {netflow:+,.0f} BTC (outflow)")
        elif netflow > 5000:
            bear += 0.5
            parts.append(f"Netflow {netflow:+,.0f} BTC (inflow)")
        else:
            parts.append(f"Netflow {netflow:+,.0f} BTC")

    composite = cycle.get("composite_score")
    if composite is not None:
        if composite < 20:
            bull += 0.5
            parts.append(f"Cycle {composite} (deep value)")
        elif composite > 80:
            bear += 0.5
            parts.append(f"Cycle {composite} (overheated)")
        else:
            parts.append(f"Cycle {composite}/100")

    detail = "; ".join(parts) if parts else "No cycle signals"
    if bull > bear + 0.5:
        verdict = "UNDERVALUED"
    elif bear > bull + 0.5:
        verdict = "OVERHEATED"
    else:
        verdict = "NEUTRAL"
    return {"verdict": verdict, "emoji": emoji_for(verdict), "detail": detail}


def main():
    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%d %H:%M UTC")

    # Load all data sources
    gate0 = load(os.path.join(DATA_DIR, "gate0.json"))
    macro = load(os.path.join(DATA_DIR, "macro.json"))
    structural = load(os.path.join(DATA_DIR, "structural.json"))
    supplementary = load(os.path.join(DATA_DIR, "supplementary.json"))
    derivatives = load(os.path.join(DATA_DIR, "derivatives.json"))
    cycle = load(os.path.join(DATA_DIR, "cycle.json"))
    liquidity = load(os.path.join(DATA_DIR, "liquidity_status.json"))
    regime_switch = load(os.path.join(DATA_DIR, "regime_switch.json"))
    amt_status = load(os.path.join(DATA_DIR, "amt_status.json"))

    # Score each layer
    gate = score_gate(gate0)
    macro_layer = score_macro(macro, amt_status)
    structure = score_structure(structural, supplementary)
    derivs = score_derivatives(derivatives, liquidity)
    cycle_layer = score_cycle(cycle)

    # ── Factor tally (for synthesis) ──
    layers = [gate, macro_layer, structure, derivs, cycle_layer]
    bull_count = 0
    bear_count = 0
    for layer in layers:
        v = str(layer.get("verdict", "")).upper()
        if "BULL" in v or "UNDER" in v:
            bull_count += 1
        elif "BEAR" in v or "OVER" in v or "DRY" in v or "EVAP" in v:
            bear_count += 1

    # ── Determine raw synthesis verdict ──
    if bull_count > bear_count + 2:
        raw_verdict = "BULLISH"
    elif bear_count > bull_count + 2:
        raw_verdict = "BEARISH"
    else:
        raw_verdict = "NEUTRAL"

    # ── Regime Overlay ──
    detected_regime = None
    regime_overlay_applied = False
    if regime_switch:
        detected_regime = regime_switch.get("regime", "UNCERTAIN")
        # Force BEARISH for distribution/risk-off regimes
        if detected_regime in ("DISTRIBUTION", "RISK_OFF"):
            raw_verdict = "BEARISH"
            bear_count = max(bear_count, 3)
            regime_overlay_applied = True

    # ── Build final verdict with regime context ──
    if regime_overlay_applied:
        synthesis_verdict = f"REGIME OVERRIDE — {detected_regime}"
    elif detected_regime in ("CASCADE",):
        if raw_verdict == "BULLISH":
            synthesis_verdict = "CAUTIOUS BULLISH"
        else:
            synthesis_verdict = raw_verdict
    elif detected_regime in ("TRENDING",):
        synthesis_verdict = raw_verdict
    elif detected_regime in ("RANGING",):
        if raw_verdict == "BULLISH":
            synthesis_verdict = "CAUTIOUS NEUTRAL"
        elif raw_verdict == "BEARISH":
            synthesis_verdict = "CAUTIOUS NEUTRAL"
        else:
            synthesis_verdict = "NEUTRAL"
    else:
        synthesis_verdict = raw_verdict

    # ── Build detail string ──
    detail_parts = []
    if regime_overlay_applied:
        detail_parts.append(f"FORCED by {detected_regime} regime detection — all contrary signals suppressed")
    else:
        detail_parts.append(f"{bull_count} bullish / {bear_count} bearish signals")
        if detected_regime:
            detail_parts.append(f"Regime: {detected_regime}")

    # TA warning
    ta_warning = None
    if supplementary:
        price = supplementary.get("price", 0)
        ma50 = supplementary.get("ma50", 0)
        if price > 0 and ma50 > 0 and price < ma50:
            pct = round((ma50 - price) / ma50 * 100, 1)
            ta_warning = f"Price {pct}% below MA50 — medium-term structure bearish"
            detail_parts.append(ta_warning)

    # ── Build output ──
    output = {
        "gate": gate,
        "macro": macro_layer,
        "structure": structure,
        "derivatives": derivs,
        "cycle": cycle_layer,
        "synthesis": {
            "verdict": synthesis_verdict,
            "detail": " | ".join(detail_parts),
            "bull_count": bull_count,
            "bear_count": bear_count,
            "ta_warning": ta_warning,
            "detected_regime": detected_regime,
            "regime_overlay_applied": regime_overlay_applied,
        },
        "_collected": now_str,
    }

    out_path = os.path.join(DATA_DIR, "regime.json")
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    # Print summary
    print(f"[regime_synthesis] Verdict: {synthesis_verdict}")
    print(f"[regime_synthesis] Bull: {bull_count} | Bear: {bear_count} | Regime: {detected_regime}")
    print(f"[regime_synthesis] Layers: Gate={gate['verdict']} Macro={macro_layer['verdict']} Structure={structure['verdict']} Deriv={derivs['verdict']} Cycle={cycle_layer['verdict']}")
    if regime_overlay_applied:
        print(f"[regime_synthesis] ⚠ REGIME OVERLAY ACTIVE — {detected_regime} forces BEARISH")
    print(f"[regime_synthesis] Written to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
