#!/usr/bin/env python3
"""
Volume + Breakout Confirmation Playbook v1.0 — per GetClaw spec (June 24, 2026).
Activated when TRENDING + active_strategy = "Volume + Breakout Confirmation".

Purpose: Confirm the breakout is real (not a fakeout) using volume profile.
Only fires at HIGH confidence — stronger than Turtle Breakout.

Two modes:
  MOMENTUM: volume 1.5x+ average → enter immediately (fading fast)
  RETEST:   volume 1.2x+ average → wait for pullback to breakout level

Key differentiator vs Turtle Breakout: volume confirmation is mandatory,
taker threshold is higher (60% vs 55%), and position sizing is 1.5x larger.

Output: data/playbook_volume_breakout.json
"""
import sys, os, json
from datetime import datetime, timezone
from pathlib import Path
import urllib.request

PLAYBOOK_DIR = Path(__file__).parent
SITE = Path("/home/maswilee/projects/pipeline-dashboard-v3")
DATA_DIR = SITE / "data"
sys.path.insert(0, str(SITE / "playbooks"))

from regime_gate import get_regime, get_liquidity
from position_manager import check_exposure_cap, check_turtle_overlap, acquire_position_lock


# ═══════════════════════════════════════
# DATA LOADING
# ═══════════════════════════════════════

def load_json(path):
    if not os.path.exists(str(path)):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def load_config():
    return load_json(PLAYBOOK_DIR / "config.json")


def fetch_klines(symbol="BTCUSDT", interval="1h", limit=50):
    """Fetch OHLCV klines from Binance public API."""
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        return {
            "close": [float(c[4]) for c in data],
            "high":  [float(c[2]) for c in data],
            "low":   [float(c[3]) for c in data],
            "open":  [float(c[1]) for c in data],
            "volume": [float(c[5]) for c in data],
        }
    except Exception as e:
        print(f"[volume_breakout] klines fetch failed: {e}")
        return None


def load_amt():
    return load_json("/tmp/amt_feed.json")


# ═══════════════════════════════════════
# INDICATORS
# ═══════════════════════════════════════

def rolling_mean(values, window=20):
    """SMA over window periods."""
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def volume_ratio_current(vs_avg, current_vol, avg_vol):
    """Current volume / 20-period average volume."""
    if avg_vol is None or avg_vol == 0:
        return 1.0
    return current_vol / avg_vol


def cvd_accelerating(cvd_values, candles=3):
    """CVD slope steepening — last N candles slope > previous N candles slope."""
    if len(cvd_values) < candles * 2:
        return False
    recent = cvd_values[-candles:]
    prior = cvd_values[-candles*2:-candles]
    recent_slope = (recent[-1] - recent[0]) / candles if candles > 0 else 0
    prior_slope = (prior[-1] - prior[0]) / candles if candles > 0 else 0
    # For longs: slope is positive and accelerating
    # For shorts: slope is negative and accelerating (more negative)
    return abs(recent_slope) > abs(prior_slope) and abs(recent_slope) > 0


def cvd_holding(cvd_values, candles=2, tolerance_pct=0.05):
    """CVD not declining — holding near recent highs (for retest validation)."""
    if len(cvd_values) < candles:
        return False
    recent = cvd_values[-candles:]
    peak = max(cvd_values[-candles*2:]) if len(cvd_values) >= candles*2 else cvd_values[-1]
    if peak == 0:
        return False
    return min(recent) >= peak * (1 - tolerance_pct)


def volume_exhausting(volumes, cfg):
    """Check if volume is contracting below threshold."""
    ex = cfg["volume_exhaustion"]
    n = ex["declining_candles"]
    if len(volumes) < n + 1:
        return False
    avg_vol = rolling_mean(volumes, cfg["volume_window"])
    if avg_vol is None:
        return False
    recent = volumes[-n:]
    # All last N candles below threshold
    all_below = all(v < avg_vol * ex["below_avg_mult"] for v in recent)
    # Declining trend
    declining = recent[-1] < recent[0]
    return all_below and declining


def detect_breakout_level(klines, direction, lookback=20):
    """Detect the breakout level from recent price structure.
    LONG: 20h high as breakout level
    SHORT: 20h low as breakout level
    """
    if direction == "LONG":
        return max(klines["high"][-lookback:])
    else:
        return min(klines["low"][-lookback:])


def price_near_breakout(price, breakout_level, threshold_pct):
    """Check if price is within threshold_pct of breakout level."""
    if breakout_level == 0:
        return False
    dist_pct = abs(price - breakout_level) / breakout_level * 100
    return dist_pct <= threshold_pct


# ═══════════════════════════════════════
# ENTRY CHECKS
# ═══════════════════════════════════════

def check_long_entry(mode, cfg, price, klines, amt_data, liq_data, cvd_vals):
    """Check all long entry conditions. Returns (passed, checks_dict, mode_used)."""
    rules = cfg["entry"]["long"][mode]
    checks = {}

    # Volume
    avg_vol = rolling_mean(klines["volume"], cfg["volume_window"])
    current_vol = klines["volume"][-1]
    vol_ratio = volume_ratio_current(vs_avg=current_vol, current_vol=current_vol, avg_vol=avg_vol)
    checks["volume_surge"] = vol_ratio >= rules["volume_mult"]

    # Taker buy ratio
    taker = amt_data.get("taker_volume", {}).get("ratio_24h") if amt_data else None
    if taker is not None:
        taker_pct = taker / (1 + taker) if taker > 0 else 0.5
    else:
        taker_pct = None
    checks["taker_ratio"] = taker_pct is not None and taker_pct >= rules["taker_ratio_min"]

    # CVD
    if mode == "momentum":
        checks["cvd_accel"] = cvd_accelerating(cvd_vals, rules["cvd_accel_candles"])
    else:
        checks["cvd_hold"] = cvd_holding(cvd_vals, rules["cvd_hold_candles"])

    # OI delta
    oi_delta = amt_data.get("funding", {}).get("oi_change_1h", 0) if amt_data else 0
    if oi_delta > 2:
        oi_label = "EXPANDING"
    elif oi_delta < -2:
        oi_label = "DECLINING"
    else:
        oi_label = "FLAT"
    checks["oi_delta"] = oi_label in rules["oi_delta_allowed"]

    # Funding
    funding = amt_data.get("funding", {}).get("rate") if amt_data else None
    checks["funding"] = funding is None or funding <= rules.get("funding_max", 0.0005)

    # Price near breakout level
    breakout = detect_breakout_level(klines, "LONG")
    checks["price_near_high"] = price_near_breakout(price, breakout, rules["price_near_high_pct"])

    # RETEST: additional depth check
    if mode == "retest":
        retest_max = rules.get("retest_depth_max_pct", 0.4)
        # Pullback shouldn't exceed retest_depth_max from breakout level
        pullback_pct = (breakout - price) / breakout * 100 if breakout > 0 else 999
        checks["retest_depth"] = pullback_pct <= retest_max

    # Liquidity
    liq_verdict = liq_data.get("liquidity_verdict", "UNKNOWN") if liq_data else "UNKNOWN"
    checks["liquidity"] = liq_verdict in rules["liquidity_allowed"]

    passed = all(checks.values())
    return passed, checks


def check_short_entry(mode, cfg, price, klines, amt_data, liq_data, cvd_vals):
    """Check all short entry conditions."""
    rules = cfg["entry"]["short"][mode]
    checks = {}

    # Volume
    avg_vol = rolling_mean(klines["volume"], cfg["volume_window"])
    current_vol = klines["volume"][-1]
    vol_ratio = volume_ratio_current(vs_avg=current_vol, current_vol=current_vol, avg_vol=avg_vol)
    checks["volume_surge"] = vol_ratio >= rules["volume_mult"]

    # Taker buy ratio (low for shorts = sellers dominating)
    taker = amt_data.get("taker_volume", {}).get("ratio_24h") if amt_data else None
    if taker is not None:
        taker_pct = taker / (1 + taker) if taker > 0 else 0.5
    else:
        taker_pct = None
    checks["taker_ratio"] = taker_pct is not None and taker_pct <= rules["taker_ratio_max"]

    # CVD (negative acceleration for shorts)
    if mode == "momentum":
        checks["cvd_accel"] = cvd_accelerating(cvd_vals, rules["cvd_accel_candles"])
    else:
        checks["cvd_hold"] = cvd_holding(cvd_vals, rules["cvd_hold_candles"])

    # OI delta
    oi_delta = amt_data.get("funding", {}).get("oi_change_1h", 0) if amt_data else 0
    if oi_delta > 2:
        oi_label = "EXPANDING"
    elif oi_delta < -2:
        oi_label = "DECLINING"
    else:
        oi_label = "FLAT"
    checks["oi_delta"] = oi_label in rules["oi_delta_allowed"]

    # Funding
    funding = amt_data.get("funding", {}).get("rate") if amt_data else None
    checks["funding"] = funding is None or funding >= rules.get("funding_min", -0.0005)

    # Price near breakdown level
    breakdown = detect_breakout_level(klines, "SHORT")
    checks["price_near_low"] = price_near_breakout(price, breakdown, rules["price_near_low_pct"])

    # RETEST: additional depth check
    if mode == "retest":
        retest_max = rules.get("retest_depth_max_pct", 0.4)
        pullback_pct = (price - breakdown) / breakdown * 100 if breakdown > 0 else 999
        checks["retest_depth"] = pullback_pct <= retest_max

    # Liquidity
    liq_verdict = liq_data.get("liquidity_verdict", "UNKNOWN") if liq_data else "UNKNOWN"
    checks["liquidity"] = liq_verdict in rules["liquidity_allowed"]

    passed = all(checks.values())
    return passed, checks


# ═══════════════════════════════════════
# INVALIDATION
# ═══════════════════════════════════════

def check_invalidation(regime_data, amt_data, liq_data, cfg, direction, cvd_vals, klines, price):
    """
    Check all invalidation criteria.
    Returns list of active invalidation triggers (empty = valid).
    """
    triggers = []
    inv = cfg["invalidation"]

    # 1. Regime flip away from TRENDING
    if inv.get("regime_flip") and regime_data.get("regime_changed"):
        triggers.append(f"regime_flip: {regime_data.get('previous_regime', '?')} → {regime_data.get('regime', '?')}")

    # 2. Active strategy changed (no longer Volume + Breakout Confirmation)
    active_strat = regime_data.get("active_strategy", "")
    if "Volume + Breakout Confirmation" not in active_strat:
        triggers.append(f"strategy_changed: now '{active_strat}'")

    # 3. Volume exhaustion
    if volume_exhausting(klines["volume"], cfg):
        triggers.append("volume_exhaustion: declining volume below 70% average")

    # 4. CVD direction failure
    if inv.get("cvd_flip_negative") and cvd_vals and len(cvd_vals) >= 3:
        if direction == "LONG":
            if cvd_vals[-1] < cvd_vals[-3]:
                triggers.append("cvd_weakening: CVD declining last 3 candles")
        else:  # SHORT
            if cvd_vals[-1] > cvd_vals[-3]:
                triggers.append("cvd_weakening: CVD rising last 3 candles")

    # 5. OI decline (participation dropping)
    oi_delta = amt_data.get("funding", {}).get("oi_change_1h", 0) if amt_data else 0
    oi_decline_pct = abs(inv.get("oi_decline_pct", 5))
    if oi_delta < -oi_decline_pct:
        triggers.append(f"oi_decline: {oi_delta}% — participation dropping")

    # 6. Close back inside range (breakout failed)
    if inv.get("close_back_inside_range") and direction == "LONG":
        breakout = detect_breakout_level(klines, "LONG")
        if price < breakout * 0.998:  # 0.2% buffer
            triggers.append(f"close_back_inside: {price:.0f} < breakout {breakout:.0f}")
    elif inv.get("close_back_inside_range") and direction == "SHORT":
        breakdown = detect_breakout_level(klines, "SHORT")
        if price > breakdown * 1.002:
            triggers.append(f"close_back_inside: {price:.0f} > breakdown {breakdown:.0f}")

    # 7. Funding exhaustion (crowded trade)
    funding = amt_data.get("funding", {}).get("rate") if amt_data else None
    if funding is not None and abs(funding) > inv.get("funding_exhaustion", 0.008):
        triggers.append(f"funding_exhaustion: {funding*100:.4f}% — crowded trade signal")

    # 8. Liquidity deterioration
    liq_verdict = liq_data.get("liquidity_verdict", "UNKNOWN") if liq_data else "UNKNOWN"
    if liq_verdict in ("DRY", "EVAPORATING"):
        triggers.append(f"liquidity_kill: {liq_verdict}")

    return triggers


# ═══════════════════════════════════════
# POSITION SIZING
# ═══════════════════════════════════════

def compute_position_size(confidence, mode, cfg):
    """Position risk as % of account. 1.5x Turtle baseline."""
    base = cfg["sizing"]["base_risk_pct"].get(confidence, 1.0)
    scalar = cfg["sizing"]["mode_scalar"].get(mode.upper(), 0.8)
    return round(base * scalar, 2)


# ═══════════════════════════════════════
# MAIN
# ═══════════════════════════════════════

def main():
    now = datetime.now(timezone.utc)
    cfg = load_config()
    if not cfg:
        print("[volume_breakout] config.json missing — exiting")
        return 1

    # ── Regime gate ──
    regime = get_regime()
    if not regime:
        result = {"status": "offline", "reason": "No regime data", "timestamp": now.isoformat()}
        write_output(result)
        return 0

    detected = regime.get("regime", "UNCERTAIN")
    if detected != "TRENDING":
        result = {
            "status": "inactive",
            "reason": f"Regime is {detected}, not TRENDING",
            "timestamp": now.isoformat()
        }
        write_output(result)
        print(f"[volume_breakout] Inactive — regime is {detected}")
        return 0

    # Only active when specifically Volume + Breakout Confirmation
    active_strat = regime.get("active_strategy", "")
    if "Volume + Breakout Confirmation" not in active_strat:
        result = {
            "status": "inactive",
            "reason": f"Active strategy is '{active_strat}', not Volume + Breakout Confirmation",
            "timestamp": now.isoformat()
        }
        write_output(result)
        print(f"[volume_breakout] Inactive — strategy is '{active_strat}'")
        return 0

    # ── Load data ──
    amt = load_amt()
    liq = get_liquidity()
    klines = fetch_klines()

    if not klines or len(klines["close"]) < 25:
        print("[volume_breakout] Insufficient kline data")
        result = {"status": "offline", "reason": "Klines unavailable", "timestamp": now.isoformat()}
        write_output(result)
        return 0

    price = klines["close"][-1]
    confidence = regime.get("confidence", "HIGH")

    # ── Compute CVD ──
    cvd_vals = []
    cumulative = 0
    for i in range(1, len(klines["close"])):
        delta = klines["close"][i] - klines["close"][i-1]
        cumulative += delta * klines["volume"][i]
        cvd_vals.append(cumulative)

    # ── Detect mode: MOMENTUM vs RETEST ──
    avg_vol = rolling_mean(klines["volume"], cfg["volume_window"])
    current_vol = klines["volume"][-1]
    vol_ratio = volume_ratio_current(current_vol, avg_vol, avg_vol)
    breakout = detect_breakout_level(klines, "LONG")
    breakdown = detect_breakout_level(klines, "SHORT")

    atr_norm = regime.get("atr_normalized", 2.0) if isinstance(regime.get("atr_normalized"), (int, float)) else 2.0

    if vol_ratio >= cfg["entry"]["long"]["momentum"]["volume_mult"]:
        mode = "momentum"
    else:
        mode = "retest"

    # ── Entry checks ──
    long_passed, long_checks = check_long_entry(mode, cfg, price, klines, amt, liq, cvd_vals)
    short_passed, short_checks = check_short_entry(mode, cfg, price, klines, amt, liq, cvd_vals)

    # ── Determine signal ──
    if long_passed:
        signal = "LONG"
        direction = "LONG"
    elif short_passed:
        signal = "SHORT"
        direction = "SHORT"
    else:
        signal = "NO_SIGNAL"
        direction = None

    # ── Invalidation check ──
    invalidation_triggers = []
    if signal != "NO_SIGNAL":
        invalidation_triggers = check_invalidation(regime, amt, liq, cfg, direction, cvd_vals, klines, price)
        if invalidation_triggers:
            signal = "NO_SIGNAL"
            direction = None

    # ── RETEST overlap guard (GetClaw flag June 24) ──
    # If RETEST mode and Turtle already entered at same breakout level → HARD NO_SIGNAL
    # Per GetClaw: "The cap is a safety net, not a signal filter."
    overlap_triggers = []
    if mode == "retest" and signal != "NO_SIGNAL":
        bk_level = detect_breakout_level(klines, direction)
        overlap, overlap_detail = check_turtle_overlap(bk_level, direction)
        if overlap:
            overlap_triggers.append(overlap_detail)
            signal = "NO_SIGNAL"
            direction = None
            invalidation_triggers.append(f"RETEST_OVERLAP: {overlap_detail['reason']}")

    # ── Stop calculation ──
    stop_cfg = cfg["stops"][mode]
    atr_price_val = price * (atr_norm / 100) if atr_norm is not None and atr_norm < 900 else price * 0.02
    stop_distance = stop_cfg["atr_mult"] * atr_price_val

    # Breakout level invalidation overrides ATR stop if tighter
    breakout_invalidation = stop_cfg.get("breakout_level_invalidation")
    if breakout_invalidation == "close_below" and direction == "LONG":
        level_stop = price - breakout * 0.998  # 0.2% below breakout
        if level_stop > 0:
            stop_distance = min(stop_distance, price - (breakout * 0.998))
    elif breakout_invalidation == "close_below" and direction == "SHORT":
        level_stop = breakdown * 1.002 - price
        if level_stop > 0:
            stop_distance = min(stop_distance, level_stop)

    # ── Take profit ──
    tp_cfg = cfg["take_profit"]
    tp_atr = tp_cfg[f"{mode}_tp_atr_mult"] * atr_price_val
    if signal == "LONG":
        tp_primary = round(price + tp_atr, 2)
        tp_partial = round(price + tp_atr * tp_cfg["tier1_position_pct"], 2)
    elif signal == "SHORT":
        tp_primary = round(price - tp_atr, 2)
        tp_partial = round(price - tp_atr * tp_cfg["tier1_position_pct"], 2)
    else:
        tp_primary = None
        tp_partial = None

    # ── R:R check ──
    rr = None
    if signal != "NO_SIGNAL" and tp_primary and stop_distance > 0:
        if direction == "LONG":
            reward = tp_primary - price
        else:
            reward = price - tp_primary
        rr = round(reward / stop_distance, 2)
        rr_min = cfg["take_profit"]["tight_rr_min"] if mode == "momentum" else cfg["take_profit"]["loose_rr_min"]
        if rr < rr_min:
            signal = "NO_SIGNAL"
            direction = None
            invalidation_triggers.append(f"rr_check: {rr:.2f} < {rr_min} minimum")

    # ── Size ──
    pos_size = compute_position_size(confidence, mode, cfg)

    # ── Portfolio exposure cap (GetClaw flag June 24) ──
    # Lock wraps read→check to prevent race condition with Turtle Breakout
    cap_note = None
    if signal != "NO_SIGNAL":
        try:
            with acquire_position_lock():
                allowed, cap_reason = check_exposure_cap(pos_size, "volume_breakout")
                if allowed < pos_size:
                    cap_note = cap_reason
                    pos_size = allowed
                    if pos_size == 0:
                        signal = "NO_SIGNAL"
                        direction = None
                        invalidation_triggers.append(cap_reason)
        except TimeoutError as e:
            print(f"[volume_breakout] Lock timeout: {e} — aborting entry")
            signal = "NO_SIGNAL"
            direction = None
            invalidation_triggers.append(f"LOCK_TIMEOUT: {e}")

    # ── Time limits ──
    max_hold = cfg["time_limits"][f"{mode}_max_hold_hours"]

    # ── Build output ──
    result = {
        "strategy": cfg["strategy"],
        "version": cfg["version"],
        "mode": mode,
        "signal": signal,
        "timestamp": now.isoformat(),
        "btc_price": round(price, 2),
        "atr_pct": round(atr_norm, 2),
        "atr_price": round(atr_price_val, 2),
        "confidence": confidence,
        "volume_ratio": round(vol_ratio, 2),
        "avg_volume": round(avg_vol, 2) if avg_vol is not None else None,
        "current_volume": round(current_vol, 2),
        "breakout_level": round(breakout if direction == "LONG" else breakdown, 2),
        "position_size_pct": pos_size,
        "vs_turtle_mult": cfg["sizing"]["vs_turtle_multiplier"],
        "max_hold_hours": max_hold,
        "stop_distance_usd": round(stop_distance, 2),
        "entry_price": round(price, 2) if signal != "NO_SIGNAL" else None,
        "stop_loss": round(price - stop_distance, 2) if signal == "LONG" else (round(price + stop_distance, 2) if signal == "SHORT" else None),
        "tp_primary": tp_primary,
        "tp_partial": tp_partial,
        "tp_partial_pct": tp_cfg["tier1_position_pct"],
        "rr_ratio": rr,
        "long_checks": long_checks,
        "short_checks": short_checks,
        "invalidation_triggers": invalidation_triggers,
        "overlap_triggers": overlap_triggers,
        "exposure_cap_note": cap_note,
        "regime": detected,
        "active_strategy": active_strat,
    }
    write_output(result)

    print(f"[volume_breakout] Mode: {mode.upper()} | Signal: {signal} | Price: ${price:,.0f} | Vol: {vol_ratio:.2f}x avg")
    if signal != "NO_SIGNAL":
        print(f"[volume_breakout] {signal}: entry ${price:,.0f} | stop ${result['stop_loss']:,.0f} | TP1 ${tp_partial:,.0f} | TP2 ${tp_primary:,.0f} | R:R {rr} | Size {pos_size}% ({cfg['sizing']['vs_turtle_multiplier']}x Turtle)")
    else:
        fails = [k for k, v in (long_checks | short_checks).items() if v is False]
        print(f"[volume_breakout] No signal — failing checks: {fails[:5]} | Invalidation: {len(invalidation_triggers)} triggers")
    print(f"[volume_breakout] Written to data/playbook_volume_breakout.json")
    return 0


def write_output(data):
    import json as _json
    DATA_DIR.mkdir(exist_ok=True)
    out = DATA_DIR / "playbook_volume_breakout.json"
    tmp = out.with_name(f".{out.name}.tmp")
    with open(tmp, "w") as f:
        _json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, out)


if __name__ == "__main__":
    sys.exit(main())
