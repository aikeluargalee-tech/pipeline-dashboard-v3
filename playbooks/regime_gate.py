#!/usr/bin/env python3
"""
Shared regime gate module — validates active regime before playbook execution.
Import by all playbooks: playbooks/mean_reversion/, playbooks/liquidation_momentum/, etc.
"""
import os, json

SITE = "/home/maswilee/projects/pipeline-dashboard-v3"
DATA_DIR = os.path.join(SITE, "data")
REGIME_FILE = os.path.join(DATA_DIR, "regime_switch.json")
LIQUIDITY_FILE = os.path.join(DATA_DIR, "liquidity_status.json")


def load_json(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        print(f"[regime_gate] Error loading {path}: {e}")
        return {}


def get_regime():
    """Return current regime dict from regime_switch.json, or None."""
    return load_json(REGIME_FILE)


def get_liquidity():
    """Return current liquidity status, or None."""
    return load_json(LIQUIDITY_FILE)


def validate_regime(required_regime):
    """
    Check if current regime matches required_regime.
    Returns (is_valid, reason_dict).
    reason_dict contains: regime, confidence, age_minutes, mode, atr_normalized, liquidity_verdict.
    """
    regime = get_regime()
    if not regime:
        return False, {"error": "No regime_switch.json — regime detection offline"}

    detected = regime.get("regime", "UNCERTAIN")
    confidence = regime.get("confidence", "LOW")
    age = regime.get("regime_age_minutes", 0)

    # ── Kill switch 1: regime doesn't match ──
    if detected != required_regime:
        return False, {
            "reason": f"Regime is {detected}, not {required_regime}",
            "regime": detected,
            "confidence": confidence,
            "age_minutes": age,
        }

    # ── Kill switch 2: regime too fresh (< 15 min) ──
    if age < 15:
        return False, {
            "reason": f"Regime {detected} is only {age}min old — wait for stabilization",
            "regime": detected,
            "confidence": confidence,
            "age_minutes": age,
        }

    # ── Mode selection ──
    # Canonical ATR default = 2.0%. 999 was a sentinel that could leak into stops.
    raw_atr = regime.get("atr_normalized")
    atr_data_valid = isinstance(raw_atr, (int, float))
    atr_norm = float(raw_atr) if atr_data_valid else 2.0  # type: ignore[arg-type]
    if confidence in ("HIGH", "MEDIUM") and atr_norm < 0.8:
        mode = "TIGHT"
    else:
        mode = "LOOSE"

    # ── Liquidity check ──
    liq = get_liquidity()
    liquidity_verdict = liq.get("liquidity_verdict", "UNKNOWN") if liq else "UNKNOWN"

    return True, {
        "regime": detected,
        "confidence": confidence,
        "age_minutes": age,
        "mode": mode,
        "atr_normalized": atr_norm,
        "atr_data_valid": atr_data_valid,
        "liquidity_verdict": liquidity_verdict,
    }


def compute_mode(regime_data, atr_normalized):
    """Standalone mode computation when regime dict is already loaded."""
    conf = regime_data.get("confidence", "LOW")
    if conf in ("HIGH", "MEDIUM") and atr_normalized < 0.8:
        return "TIGHT"
    return "LOOSE"
