#!/usr/bin/env python3
"""
Regime Switch Producer for Pipeline V3 — per GetClaw spec.
Classifies market into 1 of 6 regimes (5 + UNCERTAIN fallback).
Reads existing data feeds — zero new API calls.

Priority: DISTRIBUTION → RISK_OFF → CASCADE → TRENDING → RANGING → UNCERTAIN
Output: data/regime_switch.json
"""
import sys
import os
import json
from datetime import datetime, timezone

SITE = "/home/maswilee/projects/pipeline-dashboard-v3"
OUTPUT = os.path.join(SITE, "data/regime_switch.json")
PREVIOUS = os.path.join(SITE, "data/regime_switch.json")

AMT_FEED = "/tmp/amt_feed.json"
LIQUIDITY = os.path.join(SITE, "data/liquidity_status.json")
BLACK_SWAN = os.path.join(SITE, "data/black_swan.json")
CRASH_PRE = os.path.join(SITE, "data/crash_precursor.json")
GATE0 = os.path.join(SITE, "data/gate0.json")
SIGMA = os.path.join(SITE, "data/sigma_status.json")
AMT_STATUS = os.path.join(SITE, "data/amt_status.json")


def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def parse_age_minutes(age_str):
    """Parse '1h 18m ago' or '47 min ago' into minutes."""
    if not age_str:
        return None
    total = 0
    for part in age_str.replace("ago", "").strip().split():
        part = part.strip()
        if "h" in part:
            try:
                total += int(part.replace("h", "")) * 60
            except ValueError:
                pass
        elif "m" in part and "min" not in part:
            try:
                total += int(part.replace("m", ""))
            except ValueError:
                pass
        elif "min" in part:
            try:
                total += int(part.replace("min", ""))
            except ValueError:
                pass
        elif part.isdigit():
            total += int(part)
    return total if total > 0 else None


def main():
    now = datetime.now(timezone.utc)
    signals = {}

    # ── Load all sources ──
    amt = read_json(AMT_FEED)
    liq = read_json(LIQUIDITY)
    bs = read_json(BLACK_SWAN)
    cp = read_json(CRASH_PRE)
    g0 = read_json(GATE0)
    sg = read_json(SIGMA)
    ams = read_json(AMT_STATUS)

    # ── Liquidity signals ──
    if liq:
        signals["liquidity_verdict"] = liq.get("liquidity_verdict", "UNKNOWN")
        signals["taker_buy_ratio"] = liq.get("taker_buy_ratio")
        signals["cvd_trend"] = liq.get("cvd_trend", "UNKNOWN")
        signals["oi_delta"] = liq.get("oi_delta", "UNKNOWN")
        signals["funding_signal"] = liq.get("funding_signal", "UNKNOWN")

    # ── Risk signals ──
    signals["black_swan_score"] = bs.get("score", 0) if bs else 0
    signals["crash_precursor_d2"] = cp.get("composite", 0) if cp else 0
    signals["vix_spx_signal"] = "PROCEED"
    if g0 and "modules" in g0:
        vix_mod = g0["modules"].get("vix_spx", {})
        signals["vix_spx_signal"] = vix_mod.get("state", "PROCEED")

    # ── AMT whale pivot ──
    if ams:
        wp = ams.get("last_whale_pivot") or {}
        signals["whale_pivot_age"] = parse_age_minutes(wp.get("age", ""))
        signals["whale_pivot_distance_pct"] = wp.get("distance_pct", 0)

    # ── Sigma conviction ──
    if sg:
        raw = str(sg.get("conviction", "")).strip().upper()
        if raw == "HIGH":
            signals["sigma_conviction"] = "HIGH"
        elif raw == "MEDIUM":
            signals["sigma_conviction"] = "MEDIUM"
        elif raw == "LOW":
            signals["sigma_conviction"] = "LOW"
        else:
            signals["sigma_conviction"] = "FLAT"

    # ── Price structure (from AMT feed) ──
    signals["_price_data_valid"] = False
    signals["price_vs_20h_high"] = None
    signals["price_vs_20h_low"] = None
    signals["atr_normalized"] = 999
    if amt:
        btc_spot = amt.get("btc_spot", 0)
        high_24h = amt.get("high_24h", btc_spot)
        low_24h = amt.get("low_24h", btc_spot)
        if btc_spot and high_24h and low_24h and btc_spot > 0 and high_24h > low_24h:
            signals["price_vs_20h_high"] = round((btc_spot - high_24h) / high_24h * 100, 2)
            signals["price_vs_20h_low"] = round((btc_spot - low_24h) / low_24h * 100, 2)
            # 24h range as % of price (proxy for volatility — not true ATR)
            atr_val = (high_24h - low_24h) / btc_spot * 100
            signals["atr_normalized"] = round(atr_val, 2)
            signals["_price_data_valid"] = True
        else:
            signals["price_vs_20h_high"] = 0
            signals["price_vs_20h_low"] = 0
            signals["atr_normalized"] = 999  # sentinel: data invalid, suppress RANGING

    # ═══════════════════════════════════════════
    # DETECTION LOGIC (priority order per GetClaw)
    # ═══════════════════════════════════════════

    def regime(name, confidence, strategy, suppressed, note):
        return {
            "regime": name,
            "confidence": confidence,
            "active_strategy": strategy,
            "suppressed_strategies": suppressed,
            "tactical_note": note,
        }

    result = None

    # ── DISTRIBUTION (highest priority) ──
    lv = signals.get("liquidity_verdict", "UNKNOWN")
    if lv in ("DRY", "EVAPORATING"):
        result = regime("DISTRIBUTION", "HIGH", "Flat / Defensive Only",
                        ["Turtle Breakout", "Mean Reversion", "Liquidation Momentum"],
                        "Liquidity is DRY/EVAPORATING — distribution underway. Stay flat.")
    elif (lv == "THINNING"
          and signals.get("oi_delta") == "DECLINING"
          and signals.get("cvd_trend") == "NEGATIVE"):
        result = regime("DISTRIBUTION", "MEDIUM", "Flat / Defensive Only",
                        ["Turtle Breakout", "Mean Reversion", "Liquidation Momentum"],
                        "Liquidity thinning with OI declining and CVD negative — distribution warning.")

    # ── RISK_OFF (Gate0 driven) ──
    if not result:
        if signals.get("black_swan_score", 0) >= 10:
            result = regime("RISK_OFF", "HIGH", "Reduce Exposure / Macro Fade",
                            ["Turtle Breakout", "Mean Reversion", "Liquidation Momentum"],
                            f"Black Swan score {signals['black_swan_score']}/17 — systemic risk elevated.")
        elif signals.get("crash_precursor_d2", 0) >= 3:
            result = regime("RISK_OFF", "MEDIUM", "Reduce Exposure / Macro Fade",
                            ["Turtle Breakout", "Mean Reversion", "Liquidation Momentum"],
                            "Crash precursor signals firing — institutional exit risk.")

    # ── CASCADE (liquidation event) ──
    if not result:
        if (signals.get("oi_delta") == "DECLINING"
                and signals.get("_price_data_valid")
                and signals.get("price_vs_20h_high", 999) < -1.5
                and signals.get("taker_buy_ratio", 0.5) < 0.35):
            result = regime("CASCADE", "HIGH", "Liquidation Momentum",
                            ["Turtle Breakout", "Mean Reversion"],
                            "OI declining + price far from 20h high + taker < 35% — liquidation cascade in progress.")

    # ── TRENDING (directional move) ──
    if not result:
        if (signals.get("cvd_trend") == "POSITIVE"
                and signals.get("taker_buy_ratio", 0) > 0.55
                and signals.get("oi_delta") == "EXPANDING"
                and signals.get("_price_data_valid")
                and abs(signals.get("price_vs_20h_high", 999)) < 0.5):
            result = regime("TRENDING", "HIGH", "Turtle Breakout",
                            ["Mean Reversion"],
                            "CVD positive + taker > 55% + OI expanding + price near 20h high — trend confirmed.")
        elif (signals.get("sigma_conviction") == "HIGH"
                and signals.get("funding_signal") != "NEGATIVE"):
            result = regime("TRENDING", "MEDIUM", "Turtle Breakout",
                            ["Mean Reversion"],
                            "SIGMA conviction HIGH with funding not negative — directional bias active.")

    # ── RANGING (vol in band) ──
    if not result:
        if signals.get("atr_normalized", 999) < 0.8:
            result = regime("RANGING", "MEDIUM", "Mean Reversion + Vol Filter",
                            ["Turtle Breakout", "Liquidation Momentum"],
                            "ATR normalized < 0.8% — volatility contracting, mean reversion conditions.")
        else:
            result = regime("RANGING", "LOW", "Mean Reversion (loose)",
                            ["Liquidation Momentum"],
                            "No strong directional or risk signals. ATR elevated — loose mean reversion only.")

    # ── UNCERTAIN fallback ──
    if not result:
        result = regime("UNCERTAIN", "LOW", "Flat / Wait for Clarity",
                        ["Turtle Breakout", "Mean Reversion", "Liquidation Momentum"],
                        "Signals conflict. No clear regime — wait for resolution.")

    # ── Regime age tracking ──
    prev_data = read_json(PREVIOUS)
    previous_regime = None
    regime_changed = False
    regime_age_minutes = 0

    if prev_data:
        previous_regime = prev_data.get("regime")
        prev_timestamp = prev_data.get("timestamp")
        if prev_timestamp and previous_regime == result["regime"]:
            try:
                # Handle multiple ISO formats
                if prev_timestamp.endswith('Z'):
                    ts_clean = prev_timestamp[:-1] + '+00:00'
                else:
                    ts_clean = prev_timestamp.replace(" UTC", "+00:00").replace(" ", "T")
                prev_ts = datetime.fromisoformat(ts_clean)
                regime_age_minutes = max(0, int((now - prev_ts).total_seconds() / 60))
            except Exception:
                regime_age_minutes = 0

    if previous_regime and previous_regime != result["regime"]:
        regime_changed = True

    # ── Build payload ──
    payload = {
        **result,
        "regime_age_minutes": regime_age_minutes,
        "previous_regime": previous_regime,
        "regime_changed": regime_changed,
        "btc_price": amt.get("btc_spot") if amt else None,
        "timestamp": now.isoformat(),
        "data_age_minutes": 0,
    }

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w") as f:
        json.dump(payload, f, indent=2)

    changed_flag = "⚡ SWITCHED" if regime_changed else ""
    print(f"[regime] {result['regime']} ({result['confidence']}) | Strategy: {result['active_strategy']} | Age: {regime_age_minutes}min | Prev: {previous_regime} {changed_flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
