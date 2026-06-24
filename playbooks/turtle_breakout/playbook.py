#!/usr/bin/env python3
"""
Turtle Breakout Playbook v1.0 — per GetClaw spec (June 24, 2026).
Activated when TRENDING + active_strategy = "Turtle Breakout".

Classic Donchian channel trend-following. Two entry modes:
  HIGH:   Donchian breakout (close > 20h high / < 20h low) + volume confirmation
  MEDIUM: SIGMA conviction HIGH + funding not adverse

Stop: trailing ATR (2.0x for HIGH, 1.5x for MEDIUM).
Exit: reverse Donchian breakout or ATR trail hit.

Output: data/playbook_turtle_breakout.json
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
from position_manager import check_exposure_cap, acquire_position_lock


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


def fetch_klines(symbol="BTCUSDT", interval="1h", limit=60):
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
        print(f"[turtle_breakout] klines fetch failed: {e}")
        return None


def load_amt():
    return load_json("/tmp/amt_feed.json")


def load_sigma():
    return load_json(SITE / "data/sigma_status.json")


# ═══════════════════════════════════════
# DONCHIAN CHANNEL
# ═══════════════════════════════════════

def donchian_high(highs, period=20):
    """Donchian channel upper band."""
    if len(highs) < period:
        return None
    return max(highs[-period:])


def donchian_low(lows, period=20):
    """Donchian channel lower band."""
    if len(lows) < period:
        return None
    return min(lows[-period:])


def donchian_width(high_val, low_val, price):
    """Donchian channel width as % of price."""
    if price == 0:
        return None
    return (high_val - low_val) / price * 100


def is_breakout_long(closes, highs, period=20):
    """Close above 20-period Donchian high = breakout."""
    dh = donchian_high(highs, period)
    if dh is None:
        return False
    return closes[-1] > dh


def is_breakout_short(closes, lows, period=20):
    """Close below 20-period Donchian low = breakdown."""
    dl = donchian_low(lows, period)
    if dl is None:
        return False
    return closes[-1] < dl


def reverse_breakout(direction, closes, highs, lows, period=20):
    """Check if price has crossed back inside Donchian channel (reverse signal)."""
    if direction == "LONG":
        dl = donchian_low(lows, period)
        return dl is not None and closes[-1] <= lows[-1]
    else:
        dh = donchian_high(highs, period)
        return dh is not None and closes[-1] >= highs[-1]


# ═══════════════════════════════════════
# CVD
# ═══════════════════════════════════════

def compute_cvd(klines):
    """Approximate CVD from close deltas × volume."""
    vals = []
    cumulative = 0
    for i in range(1, len(klines["close"])):
        delta = klines["close"][i] - klines["close"][i-1]
        cumulative += delta * klines["volume"][i]
        vals.append(cumulative)
    return vals


def cvd_positive(cvd_vals):
    """CVD last value > 0 and trending up."""
    if not cvd_vals or len(cvd_vals) < 3:
        return False
    return cvd_vals[-1] > cvd_vals[-3]


def cvd_negative(cvd_vals):
    """CVD last value < 0 and trending down."""
    if not cvd_vals or len(cvd_vals) < 3:
        return False
    return cvd_vals[-1] < cvd_vals[-3]


def cvd_not_bearish(cvd_vals):
    """CVD not in clear downtrend."""
    if not cvd_vals or len(cvd_vals) < 3:
        return True
    return cvd_vals[-1] >= cvd_vals[-3]


def cvd_not_bullish(cvd_vals):
    """CVD not in clear uptrend."""
    if not cvd_vals or len(cvd_vals) < 3:
        return True
    return cvd_vals[-1] <= cvd_vals[-3]


def cvd_direction_failure(direction, cvd_vals, candles=3):
    """CVD direction has reversed for N candles."""
    if not cvd_vals or len(cvd_vals) < candles + 1:
        return False
    if direction == "LONG":
        return all(cvd_vals[-(i+1)] < cvd_vals[-(i+2)] for i in range(candles))
    else:
        return all(cvd_vals[-(i+1)] > cvd_vals[-(i+2)] for i in range(candles))


# ═══════════════════════════════════════
# ENTRY CHECKS
# ═══════════════════════════════════════

def check_entry(mode, direction, cfg, klines, amt_data, liq_data, sigma_data, cvd_vals):
    """Check entry conditions for given direction. Returns (passed, checks_dict)."""
    rules = cfg["entry"][direction][mode]
    checks = {}

    price = klines["close"][-1]

    # 1. Donchian breakout (HIGH only)
    if mode == "high":
        if direction == "long":
            checks["donchian_breakout"] = is_breakout_long(klines["close"], klines["high"])
            checks["price_near_high"] = True  # already at breakout
        else:
            checks["donchian_breakout"] = is_breakout_short(klines["close"], klines["low"])
            checks["price_near_low"] = True

    # 2. Taker ratio
    taker = amt_data.get("taker_volume", {}).get("ratio_24h") if amt_data else None
    if taker is not None:
        taker_pct = taker / (1 + taker) if taker > 0 else 0.5
    else:
        taker_pct = None

    if mode == "high":
        if direction == "long":
            checks["taker_ratio"] = taker_pct is not None and taker_pct >= rules["taker_ratio_min"]
        else:
            checks["taker_ratio"] = taker_pct is not None and taker_pct <= rules["taker_ratio_max"]

    # 3. CVD
    if mode == "high":
        if direction == "long":
            checks["cvd"] = cvd_positive(cvd_vals) if rules.get("cvd_positive") else True
        else:
            checks["cvd"] = cvd_negative(cvd_vals) if rules.get("cvd_negative") else True
    else:
        if direction == "long":
            checks["cvd_not_bearish"] = cvd_not_bearish(cvd_vals) if rules.get("cvd_not_bearish") else True
        else:
            checks["cvd_not_bullish"] = cvd_not_bullish(cvd_vals) if rules.get("cvd_not_bullish") else True

    # 4. OI delta
    oi_delta = amt_data.get("funding", {}).get("oi_change_1h", 0) if amt_data else 0
    if oi_delta > 2:
        oi_label = "EXPANDING"
    elif oi_delta < -2:
        oi_label = "DECLINING"
    else:
        oi_label = "FLAT"
    checks["oi_delta"] = oi_label in rules["oi_delta_allowed"]

    # 5. Funding
    funding = amt_data.get("funding", {}).get("rate") if amt_data else None
    if mode == "high":
        if direction == "long":
            checks["funding"] = funding is None or funding <= rules.get("funding_max", 0.0005)
        else:
            checks["funding"] = funding is None or funding >= rules.get("funding_min", -0.0005)
    else:
        if direction == "long":
            checks["funding_not_negative"] = funding is None or funding >= -0.0001
        else:
            checks["funding_not_positive"] = funding is None or funding <= 0.0001

    # 6. SIGMA conviction (MEDIUM only)
    if mode == "medium":
        sigma_conv = sigma_data.get("conviction", "LOW") if sigma_data else "LOW"
        checks["sigma_conviction"] = sigma_conv == rules.get("sigma_conviction_min", "HIGH")

    # 7. Liquidity
    liq_verdict = liq_data.get("liquidity_verdict", "UNKNOWN") if liq_data else "UNKNOWN"
    checks["liquidity"] = liq_verdict in rules["liquidity_allowed"]

    passed = all(checks.values())
    return passed, checks


# ═══════════════════════════════════════
# INVALIDATION
# ═══════════════════════════════════════

def check_invalidation(regime_data, amt_data, liq_data, cfg, direction, cvd_vals, klines):
    triggers = []
    inv = cfg["invalidation"]

    # 1. Regime flip
    if inv.get("regime_flip_away_from_trending") and regime_data.get("regime_changed"):
        triggers.append(f"regime_flip: {regime_data.get('previous_regime', '?')} → {regime_data.get('regime', '?')}")

    # 2. Strategy changed
    active_strat = regime_data.get("active_strategy", "")
    if "Turtle Breakout" not in active_strat:
        triggers.append(f"strategy_changed: '{active_strat}'")

    # 3. Reverse Donchian breakout
    if inv.get("donchian_channel_break_reverse"):
        if reverse_breakout(direction, klines["close"], klines["high"], klines["low"]):
            triggers.append("reverse_donchian: price crossed back inside channel")

    # 4. CVD direction failure
    if inv.get("cvd_direction_failure") and cvd_direction_failure(direction, cvd_vals):
        triggers.append("cvd_direction_failure: CVD reversed for 3 candles")

    # 5. OI decline
    oi_delta = amt_data.get("funding", {}).get("oi_change_1h", 0) if amt_data else 0
    if oi_delta < inv.get("oi_decline_pct", -5):
        triggers.append(f"oi_decline: {oi_delta}%")

    # 6. Volume dry-up
    avg_vol = sum(klines["volume"][-20:]) / 20 if len(klines["volume"]) >= 20 else klines["volume"][-1]
    if klines["volume"][-1] < avg_vol * inv.get("volume_dry_up_below_avg", 0.5):
        triggers.append("volume_dry_up: below 50% average")

    # 7. Liquidity
    liq_verdict = liq_data.get("liquidity_verdict", "UNKNOWN") if liq_data else "UNKNOWN"
    if liq_verdict in inv.get("liquidity_kill", []):
        triggers.append(f"liquidity_kill: {liq_verdict}")

    # 8. Funding exhaustion
    funding = amt_data.get("funding", {}).get("rate") if amt_data else None
    if funding is not None and abs(funding) > inv.get("funding_exhaustion", 0.008):
        triggers.append(f"funding_exhaustion: {funding*100:.4f}%")

    return triggers


# ═══════════════════════════════════════
# POSITION SIZING
# ═══════════════════════════════════════

def compute_position_size(confidence, klines, cfg):
    base = cfg["sizing"]["base_risk_pct"].get(confidence, 1.0)
    dw = donchian_width(
        donchian_high(klines["high"]) or klines["high"][-1],
        donchian_low(klines["low"]) or klines["low"][-1],
        klines["close"][-1]
    )
    if dw is not None:
        if dw < 1.5:
            scalar = cfg["sizing"]["donchian_width_scalar"]["narrow"]
        elif dw > 4.0:
            scalar = cfg["sizing"]["donchian_width_scalar"]["wide"]
        else:
            scalar = cfg["sizing"]["donchian_width_scalar"]["normal"]
    else:
        scalar = 1.0
    return round(base * scalar, 2)


# ═══════════════════════════════════════
# MAIN
# ═══════════════════════════════════════

def main():
    now = datetime.now(timezone.utc)
    cfg = load_config()
    if not cfg:
        print("[turtle_breakout] config.json missing — exiting")
        return 1

    regime = get_regime()
    if not regime:
        result = {"status": "offline", "reason": "No regime data", "timestamp": now.isoformat()}
        write_output(result)
        return 0

    detected = regime.get("regime", "UNCERTAIN")
    if detected != "TRENDING":
        result = {"status": "inactive", "reason": f"Regime is {detected}, not TRENDING", "timestamp": now.isoformat()}
        write_output(result)
        print(f"[turtle_breakout] Inactive — regime is {detected}")
        return 0

    active_strat = regime.get("active_strategy", "")
    if "Turtle Breakout" not in active_strat:
        result = {"status": "inactive", "reason": f"Active strategy is '{active_strat}', not Turtle Breakout", "timestamp": now.isoformat()}
        write_output(result)
        print(f"[turtle_breakout] Inactive — strategy is '{active_strat}'")
        return 0

    amt = load_amt()
    liq = get_liquidity()
    sigma = load_sigma()
    klines = fetch_klines()

    if not klines or len(klines["close"]) < 25:
        result = {"status": "offline", "reason": "Klines unavailable", "timestamp": now.isoformat()}
        write_output(result)
        return 0

    price = klines["close"][-1]
    confidence = regime.get("confidence", "MEDIUM")
    mode = confidence.lower()

    # Map HIGH/MEDIUM → high/medium
    if mode == "high":
        entry_mode = "high"
    else:
        entry_mode = "medium"

    cvd_vals = compute_cvd(klines)
    atr_norm = regime.get("atr_normalized", 2.0) if isinstance(regime.get("atr_normalized"), (int, float)) else 2.0

    # Entry checks
    long_passed, long_checks = check_entry(entry_mode, "long", cfg, klines, amt, liq, sigma, cvd_vals)
    short_passed, short_checks = check_entry(entry_mode, "short", cfg, klines, amt, liq, sigma, cvd_vals)

    if long_passed:
        signal = "LONG"
        direction = "LONG"
    elif short_passed:
        signal = "SHORT"
        direction = "SHORT"
    else:
        signal = "NO_SIGNAL"
        direction = None

    # Invalidation
    invalidation_triggers = []
    if signal != "NO_SIGNAL":
        invalidation_triggers = check_invalidation(regime, amt, liq, cfg, direction, cvd_vals, klines)
        if invalidation_triggers:
            signal = "NO_SIGNAL"
            direction = None

    # Stops
    stop_cfg = cfg["stops"][entry_mode]
    atr_price_val = price * (atr_norm / 100) if atr_norm is not None and atr_norm < 900 else price * 0.02
    stop_distance = stop_cfg["atr_mult"] * atr_price_val

    # Take profit
    tp_cfg = cfg["take_profit"]
    tp_atr = tp_cfg["atr_mult"] * atr_price_val
    if signal == "LONG":
        tp_primary = round(price + tp_atr, 2)
        tp_partial = round(price + tp_cfg["tier1_atr_mult"] * atr_price_val, 2)
    elif signal == "SHORT":
        tp_primary = round(price - tp_atr, 2)
        tp_partial = round(price - tp_cfg["tier1_atr_mult"] * atr_price_val, 2)
    else:
        tp_primary = None
        tp_partial = None

    # R:R
    rr = None
    if signal != "NO_SIGNAL" and tp_primary and stop_distance > 0:
        reward = tp_primary - price if direction == "LONG" else price - tp_primary
        rr = round(reward / stop_distance, 2)
        rr_min = cfg["take_profit"]["tight_rr_min"] if entry_mode == "high" else cfg["take_profit"]["loose_rr_min"]
        if rr < rr_min:
            signal = "NO_SIGNAL"
            direction = None
            invalidation_triggers.append(f"rr_check: {rr:.2f} < {rr_min}")

    # Size
    pos_size = compute_position_size(confidence, klines, cfg)

    # ── Portfolio exposure cap (GetClaw flag June 24) ──
    # Lock wraps read→check to prevent race condition with Volume Breakout
    cap_note = None
    if signal != "NO_SIGNAL":
        try:
            with acquire_position_lock():
                allowed, cap_reason = check_exposure_cap(pos_size, "turtle_breakout")
                if allowed < pos_size:
                    cap_note = cap_reason
                    pos_size = allowed
                    if pos_size == 0:
                        signal = "NO_SIGNAL"
                        direction = None
                        invalidation_triggers.append(cap_reason)
        except TimeoutError as e:
            print(f"[turtle_breakout] Lock timeout: {e} — aborting entry")
            signal = "NO_SIGNAL"
            direction = None
            invalidation_triggers.append(f"LOCK_TIMEOUT: {e}")

    # Donchian levels for display
    dh = donchian_high(klines["high"])
    dl = donchian_low(klines["low"])

    result = {
        "strategy": cfg["strategy"],
        "version": cfg["version"],
        "mode": entry_mode,
        "signal": signal,
        "timestamp": now.isoformat(),
        "btc_price": round(price, 2),
        "donchian_high_20h": round(dh, 2) if dh else None,
        "donchian_low_20h": round(dl, 2) if dl else None,
        "donchian_width_pct": round(dw_val, 2) if (dw_val := donchian_width(dh or price, dl or price, price)) is not None else None,
        "atr_pct": round(atr_norm, 2),
        "atr_price": round(atr_price_val, 2),
        "confidence": confidence,
        "position_size_pct": pos_size,
        "max_hold_hours": cfg["time_limits"]["max_hold_hours"],
        "stop_distance_usd": round(stop_distance, 2),
        "trailing_stop": stop_cfg.get("trail", True),
        "entry_price": round(price, 2) if signal != "NO_SIGNAL" else None,
        "stop_loss": round(price - stop_distance, 2) if signal == "LONG" else (round(price + stop_distance, 2) if signal == "SHORT" else None),
        "tp_primary": tp_primary,
        "tp_partial": tp_partial,
        "tp_partial_pct": tp_cfg["tier1_position_pct"],
        "rr_ratio": rr,
        "long_checks": long_checks,
        "short_checks": short_checks,
        "invalidation_triggers": invalidation_triggers,
        "exposure_cap_note": cap_note,
        "regime": detected,
        "active_strategy": active_strat,
    }
    write_output(result)

    print(f"[turtle_breakout] Mode: {entry_mode.upper()} | Signal: {signal} | Price: ${price:,.0f} | Donchian: {dh:,.0f}-{dl:,.0f}" if dh and dl else f"[turtle_breakout] Mode: {entry_mode.upper()} | Signal: {signal}")
    if signal != "NO_SIGNAL":
        print(f"[turtle_breakout] {signal}: entry ${price:,.0f} | stop ${result['stop_loss']:,.0f} | TP1 ${tp_partial:,.0f} | TP2 ${tp_primary:,.0f} | R:R {rr} | Size {pos_size}%")
    else:
        fails = [k for k, v in (long_checks | short_checks).items() if v is False]
        print(f"[turtle_breakout] No signal — failing: {fails[:5]}")
    print(f"[turtle_breakout] Written to data/playbook_turtle_breakout.json")
    return 0


def write_output(data):
    import json as _json
    DATA_DIR.mkdir(exist_ok=True)
    out = DATA_DIR / "playbook_turtle_breakout.json"
    tmp = out.with_name(f".{out.name}.tmp")
    with open(tmp, "w") as f:
        _json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, out)


if __name__ == "__main__":
    sys.exit(main())
