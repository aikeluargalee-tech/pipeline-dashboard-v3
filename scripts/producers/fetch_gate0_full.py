#!/usr/bin/env python3
"""
Fetch Gate 0 Full
Executes the Gate 0 threat monitoring modules from ~/trading-workflow/gate0/ registry
and integrates stablecoins, session, and ai3_wave status.
Produces data/gate0.json.
"""
import sys
import os
import json
import math
from datetime import datetime, timezone

# Add site and trading-workflow paths
SITE = "/home/maswilee/projects/pipeline-dashboard-v3"
sys.path.insert(0, SITE)
sys.path.insert(0, os.path.expanduser("~/trading-workflow"))

OUTPUT_PATH = os.path.join(SITE, "data/gate0.json")
AI3_STATE = os.path.expanduser("~/.gemini/antigravity/scratch/sigma_trading_engine/ai3_watch_state.json")

def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default

def safe_float(val, name, default=None):
    if val is None:
        return default
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except Exception:
        return default

def main():
    modules = {}
    offline = False

    # 1. Check registry presence
    tw_path = os.path.expanduser("~/trading-workflow")
    if not os.path.exists(tw_path):
        offline = True

    if not offline:
        try:
            from gate0.gate0_orchestrator import run_all
            res = run_all()
            triggers = res.get("triggers", [])
            for trig in triggers:
                name = trig.get("module_name")
                level = trig.get("level", 1)
                trigger_text = trig.get("trigger_text", "")
                data = trig.get("data") or {}

                # Map level to state: PROCEED/TIGHTENED/PAUSE/ABORT
                state = "PROCEED"
                if name == "blackswan":
                    score = safe_float(data.get("score"), "black_swan_score", 0)
                    if score >= 12:
                        state = "ABORT"
                    elif score >= 8:
                        state = "PAUSE"
                    elif score >= 5:
                        state = "TIGHTENED"
                elif name == "vix_spx":
                    vix = safe_float(data.get("vix"), "vix")
                    if vix is not None:
                        if vix > 40:
                            state = "ABORT"
                        elif vix > 30:
                            state = "PAUSE"
                        elif vix > 22:
                            state = "TIGHTENED"
                else:
                    if level == 3:
                        state = "ABORT"
                    elif level == 2:
                        state = "PAUSE"
                    elif level == 1:
                        # Simple level mapping fallback
                        state = "PROCEED"

                # Normalize module names to match the 9/10 module grid:
                norm_map = {
                    "blackswan": "black_swan",
                    "vix_spx": "vix_spx",
                    "trump_trp": "trp_check",
                    "mstr_edgar": "mstr",
                    "elon_musk": "elon",
                    "ai_bubble": "ai_bubble",
                    "quantum_threat": "quantum"
                }
                norm_name = norm_map.get(name, name)

                modules[norm_name] = {
                    "state": state,
                    "detail": trigger_text
                }

            # If any module in registry failed to output:
            for r_name in ["black_swan", "vix_spx", "trp_check", "mstr", "elon", "ai_bubble", "quantum"]:
                if r_name not in modules:
                    modules[r_name] = {
                        "state": "Offline",
                        "detail": "Offline"
                    }

        except Exception as e:
            print(f"[gate0_full] Error importing/running gate0 orchestrator: {e}")
            offline = True

    if offline:
        for r_name in ["black_swan", "vix_spx", "trp_check", "mstr", "elon", "ai_bubble", "quantum"]:
            modules[r_name] = {
                "state": "Offline",
                "detail": "Offline"
            }

    # 2. Add stablecoins module
    stablecoins_raw = read_json("/tmp/btc_stablecoin_state.json")
    sc_state = "PROCEED"
    sc_details = "All stablecoin pegs stable"
    if stablecoins_raw:
        worst_dev = 0
        for coin in stablecoins_raw.get("coins", []):
            dev = abs(safe_float(coin.get("deviation_pct"), "stablecoin deviation", 0))
            if dev > worst_dev:
                worst_dev = dev
            if dev > 2.0:
                sc_state = "ABORT"
                sc_details = f"Stablecoin depeg detected: {coin.get('symbol')} deviation {dev:.2f}%"
                break
            elif dev > 0.5:
                sc_state = "PAUSE"
                sc_details = f"Stablecoin depeg warning: {coin.get('symbol')} deviation {dev:.2f}%"
        if sc_state == "PROCEED" and worst_dev > 0:
            sc_details = f"Max deviation {worst_dev:.2f}%"
    else:
        sc_details = "No stablecoin peg data available"
    modules["stablecoins"] = {
        "state": sc_state,
        "detail": sc_details
    }

    # 3. Add session module
    session_raw = read_json("/tmp/btc_session_state.json")
    session_state = "PROCEED"
    session_details = "Market open"
    if session_raw:
        current_sess = session_raw.get("current_session", "Unknown")
        is_wk = session_raw.get("is_weekend", False)
        if is_wk:
            session_state = "TIGHTENED"
            session_details = f"Weekend liquidity ({current_sess})"
        else:
            session_details = f"Active session: {current_sess}"
    else:
        session_details = "Offline"
    modules["session"] = {
        "state": session_state,
        "detail": session_details
    }

    # 4. Add ai3_wave module
    ai3_raw = read_json(AI3_STATE)
    ai3_active = False
    if ai3_raw:
        ai3_active = ai3_raw.get("spacex_s1_active", False)
    modules["ai3_wave"] = {
        "state": "TIGHTENED" if ai3_active else "PROCEED",
        "detail": "AI-3 Wave SpaceX active" if ai3_active else "AI-3 Wave inactive"
    }

    # 5. Add geopolitical module (replaces L-1 manual gate — automated via TRP)
    trp_status = read_json(os.path.join(SITE, "data/trp_status.json"))
    geo_state = "PROCEED"
    geo_detail = "No geopolitical signals detected"
    if trp_status:
        last_tier = trp_status.get("last_tier")
        last_class = trp_status.get("last_classification", "")
        signals_today = trp_status.get("signals_today", 0)
        if last_tier == "S":
            geo_state = "ABORT"
            geo_detail = f"Tier S geopolitical signal: {last_class} — {signals_today} signals today"
        elif last_tier == "A":
            geo_state = "PAUSE"
            geo_detail = f"Tier A geopolitical signal: {last_class} — {signals_today} signals today"
        elif last_tier:
            geo_state = "TIGHTENED"
            geo_detail = f"Tier {last_tier} geopolitical signal: {last_class} — {signals_today} signals today"
        elif signals_today > 0:
            geo_detail = f"Monitoring — {signals_today} signals today, no tier classification"
    modules["geopolitical"] = {
        "state": geo_state,
        "detail": geo_detail
    }

    # 6. Compute overall verdict
    state_priority = {"ABORT": 4, "PAUSE": 3, "TIGHTENED": 2, "PROCEED": 1, "Offline": 0}
    verdict = "PROCEED"
    sources = []
    for name, mod in modules.items():
        mod_state = mod.get("state", "PROCEED")
        if state_priority.get(mod_state, 0) > state_priority.get(verdict, 0):
            verdict = mod_state
            sources = [name]
        elif state_priority.get(mod_state, 0) == state_priority.get(verdict, 0):
            sources.append(name)

    # Active rules based on verdict
    rules = {}
    if verdict == "TIGHTENED":
        rules = {"action": "Reduce position size. Tight stops. Wait for conditions to clear."}
    elif verdict == "PAUSE":
        rules = {"action": "No new positions. Reduce open size. Monitor only."}
    elif verdict == "ABORT":
        rules = {"action": "No new positions. Evaluate existing for emergency close."}

    # Construct final payload
    payload = {
        "verdict": verdict,
        "sources": sources,
        "rules": rules,
        "modules": modules,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "_collected": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    }

    # Ensure output dir exists
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"[gate0_full] Verdict {verdict}, modules: {list(modules.keys())}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
