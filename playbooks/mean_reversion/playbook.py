#!/usr/bin/env python3
"""
Mean Reversion + Vol Filter — Playbook v1.0
Per GetClaw spec (June 24, 2026). Activated when Regime Switch = RANGING.

Architecture:
  playbooks/regime_gate.py  → shared regime validation
  config.json               → all thresholds (no magic numbers in code)
  playbook.py               → this file — entry/exit/sizing logic

Output: data/playbook_mean_reversion.json
"""
import sys, os, json, math
from datetime import datetime, timezone
from pathlib import Path
import urllib.request

# ── Project paths ──
PLAYBOOK_DIR = Path(__file__).parent
SITE = Path("/home/maswilee/projects/pipeline-dashboard-v3")
DATA_DIR = SITE / "data"
sys.path.insert(0, str(SITE / "playbooks"))

from regime_gate import get_regime, get_liquidity, compute_mode


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
            "volume":[float(c[5]) for c in data],
        }
    except Exception as e:
        print(f"[mean_reversion] klines fetch failed: {e}")
        return None


def load_amt():
    return load_json("/tmp/amt_feed.json")


# ═══════════════════════════════════════
# INDICATORS
# ═══════════════════════════════════════

def calc_rsi(closes, period=14):
    """RSI(14) on 1H closes."""
    n = len(closes)
    if n < period + 1:
        return [None] * n
    deltas = [closes[i] - closes[i-1] for i in range(1, n)]
    gains = [max(d, 0) for d in deltas]
    losses = [max(-d, 0) for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    rsi = [None] * n
    if avg_loss == 0:
        rsi[period] = 100.0
    else:
        rsi[period] = 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))
    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i-1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i-1]) / period
        if avg_loss == 0:
            rsi[i] = 100.0
        else:
            rsi[i] = 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))
    return rsi


def rolling_mean(values, window=20):
    """20-period rolling mean (SMA)."""
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def cvd_making_lows(cvd_values, lookback=3):
    """Check if CVD is making new lows in recent candles."""
    if len(cvd_values) < lookback + 1:
        return False
    recent = cvd_values[-lookback:]
    return min(recent) <= min(cvd_values[-lookback-1:-1])


def cvd_making_highs(cvd_values, lookback=3):
    """Check if CVD is making new highs in recent candles."""
    if len(cvd_values) < lookback + 1:
        return False
    recent = cvd_values[-lookback:]
    return max(recent) >= max(cvd_values[-lookback-1:-1])


# ═══════════════════════════════════════
# ENTRY CHECKS
# ═══════════════════════════════════════

def check_long_entry(mode, cfg, price, rsi_val, amt_data, liq_data, cvd_vals):
    """Check all long entry conditions. Returns (passed, checks_dict)."""
    rules = cfg["entry"]["long"][mode.lower()]
    checks = {}

    # 1. RSI
    checks["rsi"] = rsi_val is not None and rsi_val < rules["rsi_max"]

    # 2. Taker buy ratio
    taker = amt_data.get("taker_volume", {}).get("ratio_24h") if amt_data else None
    # ratio_24h in AMT is buy/sell volume ratio — values like 1.2 = 55% taker
    # Convert to percentage: ratio / (1 + ratio)
    if taker is not None:
        taker_pct = taker / (1 + taker) if taker > 0 else 0.5
    else:
        taker_pct = None
    checks["taker_ratio"] = taker_pct is not None and taker_pct < rules["taker_ratio_max"]

    # 3. CVD: flat or turning up (not making new lows)
    if mode == "TIGHT":
        checks["cvd"] = not cvd_making_lows(cvd_vals) if cvd_vals else False
    else:
        recent_cvd = cvd_vals[-3:] if cvd_vals and len(cvd_vals) >= 4 else None
        checks["cvd"] = recent_cvd is not None and recent_cvd[-1] >= recent_cvd[0]  # flat or rising

    # 4. OI delta
    oi_delta = amt_data.get("funding", {}).get("oi_change_1h", 0) if amt_data else 0
    if oi_delta > 2:
        oi_label = "EXPANDING"
    elif oi_delta < -2:
        oi_label = "DECLINING"
    else:
        oi_label = "FLAT"
    checks["oi_delta"] = oi_label in rules["oi_delta_allowed"]

    # 5. Funding rate
    funding = amt_data.get("funding", {}).get("rate") if amt_data else None
    checks["funding"] = funding is not None and funding > rules["funding_min"]

    # 6. Liquidity
    liq_verdict = liq_data.get("liquidity_verdict", "UNKNOWN") if liq_data else "UNKNOWN"
    checks["liquidity"] = liq_verdict in rules["liquidity_allowed"]

    passed = all(checks.values())
    return passed, checks


def check_short_entry(mode, cfg, price, rsi_val, amt_data, liq_data, cvd_vals):
    """Check all short entry conditions. Returns (passed, checks_dict)."""
    rules = cfg["entry"]["short"][mode.lower()]
    checks = {}

    # 1. RSI
    checks["rsi"] = rsi_val is not None and rsi_val > rules["rsi_min"]

    # 2. Taker buy ratio
    taker = amt_data.get("taker_volume", {}).get("ratio_24h") if amt_data else None
    if taker is not None:
        taker_pct = taker / (1 + taker) if taker > 0 else 0.5
    else:
        taker_pct = None
    checks["taker_ratio"] = taker_pct is not None and taker_pct > rules["taker_ratio_min"]

    # 3. CVD: flat or turning down (not making new highs)
    if mode == "TIGHT":
        checks["cvd"] = not cvd_making_highs(cvd_vals) if cvd_vals else False
    else:
        recent_cvd = cvd_vals[-3:] if cvd_vals and len(cvd_vals) >= 4 else None
        checks["cvd"] = recent_cvd is not None and recent_cvd[-1] <= recent_cvd[0]

    # 4. OI delta
    oi_delta = amt_data.get("funding", {}).get("oi_change_1h", 0) if amt_data else 0
    if oi_delta > 2:
        oi_label = "EXPANDING"
    elif oi_delta < -2:
        oi_label = "DECLINING"
    else:
        oi_label = "FLAT"
    checks["oi_delta"] = oi_label in rules["oi_delta_allowed"]

    # 5. Funding rate
    funding = amt_data.get("funding", {}).get("rate") if amt_data else None
    checks["funding"] = funding is not None and funding < rules["funding_max"]

    # 6. Liquidity
    liq_verdict = liq_data.get("liquidity_verdict", "UNKNOWN") if liq_data else "UNKNOWN"
    checks["liquidity"] = liq_verdict in rules["liquidity_allowed"]

    passed = all(checks.values())
    return passed, checks


# ═══════════════════════════════════════
# INVALIDATION
# ═══════════════════════════════════════

def check_invalidation(regime_data, amt_data, liq_data, cfg, direction, cvd_vals):
    """
    Check all invalidation criteria.
    Returns list of active invalidation triggers (empty = valid).
    """
    triggers = []

    # 1. Regime flip
    if regime_data.get("regime_changed"):
        triggers.append(f"regime_flip: {regime_data.get('previous_regime', '?')} → {regime_data.get('regime', '?')}")

    # 2. Trend ignition
    taker = amt_data.get("taker_volume", {}).get("ratio_24h") if amt_data else None
    if taker:
        taker_pct = taker / (1 + taker)
    else:
        taker_pct = None
    oi_delta = amt_data.get("funding", {}).get("oi_change_1h", 0) if amt_data else 0
    ti = cfg["invalidation"]["trend_ignition"]
    if taker_pct is not None and taker_pct > ti["taker_ratio"] and oi_delta > 0:
        triggers.append(f"trend_ignition: taker {taker_pct:.3f} + OI expanding")

    # 3. Liquidity deterioration
    liq_verdict = liq_data.get("liquidity_verdict", "UNKNOWN") if liq_data else "UNKNOWN"
    if liq_verdict in cfg["invalidation"]["liquidity_kill"]:
        triggers.append(f"liquidity_kill: {liq_verdict}")

    # 4. CVD confirms trend (not reversion)
    if direction == "LONG" and cvd_making_lows(cvd_vals):
        triggers.append("cvd_new_low: sellers not exhausted")
    elif direction == "SHORT" and cvd_making_highs(cvd_vals):
        triggers.append("cvd_new_high: buyers not exhausted")

    # 5. Funding extreme (defer to Strategy 4)
    funding = amt_data.get("funding", {}).get("rate") if amt_data else None
    if funding is not None and abs(funding) > cfg["invalidation"]["funding_extreme"]:
        triggers.append(f"funding_extreme: {funding*100:.4f}% — defer to Funding Rate MR")

    return triggers


# ═══════════════════════════════════════
# POSITION SIZING
# ═══════════════════════════════════════

def compute_position_size(confidence, mode, cfg):
    """Position risk as % of account."""
    base = cfg["sizing"]["base_risk_pct"].get(confidence, 0.5)
    scalar = cfg["sizing"]["atr_scalar"].get(mode, 0.6)
    return round(base * scalar, 2)


# ═══════════════════════════════════════
# MAIN
# ═══════════════════════════════════════

def main():
    now = datetime.now(timezone.utc)
    cfg = load_config()
    if not cfg:
        print("[mean_reversion] config.json missing — exiting")
        return 1

    # ── Regime gate ──
    regime = get_regime()
    if not regime:
        result = {"status": "offline", "reason": "No regime data", "timestamp": now.isoformat()}
        write_output(result)
        return 0

    detected = regime.get("regime", "UNCERTAIN")
    if detected != "RANGING":
        result = {"status": "inactive", "reason": f"Regime is {detected}, not RANGING", "timestamp": now.isoformat()}
        write_output(result)
        print(f"[mean_reversion] Inactive — regime is {detected}")
        return 0

    # Fresh regime check
    age = regime.get("regime_age_minutes", 0)
    if age < 15:
        result = {"status": "inactive", "reason": f"Regime only {age}min old — wait for stabilization", "timestamp": now.isoformat()}
        write_output(result)
        print(f"[mean_reversion] Skipped — regime only {age}min old")
        return 0

    # Mode
    atr_norm = regime.get("atr_normalized", 999) if isinstance(regime.get("atr_normalized"), (int, float)) else 999
    confidence = regime.get("confidence", "LOW")
    mode = compute_mode(regime, atr_norm)

    # ── Load data ──
    amt = load_amt()
    liq = get_liquidity()
    klines = fetch_klines()

    if not klines or len(klines["close"]) < 20:
        print("[mean_reversion] Insufficient kline data")
        result = {"status": "offline", "reason": "Klines unavailable", "timestamp": now.isoformat()}
        write_output(result)
        return 0

    price = klines["close"][-1]
    mean_20h = rolling_mean(klines["close"], 20)
    rsi_vals = calc_rsi(klines["close"], 14)
    rsi_val = rsi_vals[-1] if rsi_vals[-1] is not None else None

    # CVD from AMT session (approximate from taker volume delta)
    # Use session_cvd if available, else compute from kline closes
    cvd_vals = None
    if amt:
        cvd_val = amt.get("taker_volume", {}).get("session_cvd")
        # We only have one CVD number from AMT, not a series
        # For CVD trend check, use volume-weighted price direction from klines
    # Fallback: approximate CVD from close deltas
    cvd_vals = []
    cumulative = 0
    for i in range(1, len(klines["close"])):
        delta = klines["close"][i] - klines["close"][i-1]
        cumulative += delta * klines["volume"][i]
        cvd_vals.append(cumulative)

    # ── Entry checks ──
    long_passed, long_checks = check_long_entry(mode, cfg, price, rsi_val, amt, liq, cvd_vals)
    short_passed, short_checks = check_short_entry(mode, cfg, price, rsi_val, amt, liq, cvd_vals)

    # ── Stop & TP ──
    stop_cfg = cfg["stops"][mode.lower()]
    atr_price_val = price * (atr_norm / 100) if atr_norm < 900 else price * 0.02  # fallback 2%
    stop_distance = stop_cfg["atr_mult"] * atr_price_val

    # Hard floor: stop cannot exceed 20h range
    price_vs_high = regime.get("price_vs_20h_high")
    price_vs_low = regime.get("price_vs_20h_low")
    stop_pct = stop_distance / price * 100

    long_blocked_by_range = False
    short_blocked_by_range = False
    if mode == "LOOSE" and price_vs_low is not None:
        if stop_pct > abs(price_vs_low):
            long_blocked_by_range = True
    if mode == "LOOSE" and price_vs_high is not None:
        if stop_pct > abs(price_vs_high):
            short_blocked_by_range = True

    # ── R:R check ──
    long_rr = None
    short_rr = None
    rr_min = cfg["take_profit"][f"{mode.lower()}_rr_min"]
    tp1_pct = cfg["take_profit"]["tier1_pct_of_mean_distance"]

    if long_passed and not long_blocked_by_range and mean_20h:
        reward = mean_20h - price
        risk = stop_distance
        long_rr = round(reward / risk, 2) if risk > 0 else 0
        if long_rr < rr_min:
            long_passed = False
            long_checks["rr_check"] = f"FAIL: R:R {long_rr:.2f} < {rr_min}"

    if short_passed and not short_blocked_by_range and mean_20h:
        reward = price - mean_20h
        risk = stop_distance
        short_rr = round(reward / risk, 2) if risk > 0 else 0
        if short_rr < rr_min:
            short_passed = False
            short_checks["rr_check"] = f"FAIL: R:R {short_rr:.2f} < {rr_min}"

    if long_blocked_by_range:
        long_checks["range_guard"] = f"BLOCKED: stop {stop_pct:.1f}% exceeds 20h low range {abs(price_vs_low):.1f}%"
        long_passed = False
    if short_blocked_by_range:
        short_checks["range_guard"] = f"BLOCKED: stop {stop_pct:.1f}% exceeds 20h high range {abs(price_vs_high):.1f}%"
        short_passed = False

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
        invalidation_triggers = check_invalidation(regime, amt, liq, cfg, direction, cvd_vals)
        if invalidation_triggers:
            signal = "NO_SIGNAL"
            direction = None

    # ── TP levels ──
    tp_primary = None
    tp_partial = None
    if signal != "NO_SIGNAL" and mean_20h:
        tp_primary = round(mean_20h, 2)
        if direction == "LONG":
            tp_partial = round(price + tp1_pct * (mean_20h - price), 2)
        else:
            tp_partial = round(price - tp1_pct * (price - mean_20h), 2)

    # ── Size ──
    pos_size = compute_position_size(confidence, mode, cfg)

    # ── Time limits ──
    max_hold = cfg["time_limits"][f"{mode.lower()}_max_hold_hours"]

    # ── Build output ──
    result = {
        "strategy": cfg["strategy"],
        "version": cfg["version"],
        "mode": mode,
        "signal": signal,
        "timestamp": now.isoformat(),
        "btc_price": round(price, 2),
        "mean_20h": round(mean_20h, 2) if mean_20h else None,
        "atr_pct": round(atr_norm, 2),
        "atr_price": round(atr_price_val, 2),
        "rsi_14": round(rsi_val, 1) if rsi_val else None,
        "confidence": confidence,
        "position_size_pct": pos_size,
        "max_hold_hours": max_hold,
        "stop_distance_usd": round(stop_distance, 2),
        "entry_price": round(price, 2) if signal != "NO_SIGNAL" else None,
        "stop_loss": round(price - stop_distance, 2) if signal == "LONG" else (round(price + stop_distance, 2) if signal == "SHORT" else None),
        "tp_primary": tp_primary,
        "tp_partial": tp_partial,
        "tp_partial_pct": cfg["take_profit"]["tier1_position_pct"],
        "rr_ratio": long_rr if signal == "LONG" else (short_rr if signal == "SHORT" else None),
        "long_checks": long_checks,
        "short_checks": short_checks,
        "invalidation_triggers": invalidation_triggers,
        "regime": detected,
    }
    write_output(result)

    # ── Summary ──
    print(f"[mean_reversion] Mode: {mode} | Signal: {signal} | RSI: {rsi_val} | Price: ${price:,.0f} | Mean: ${mean_20h:,.0f}" if mean_20h else f"[mean_reversion] Mode: {mode} | Signal: {signal}")
    if signal != "NO_SIGNAL":
        print(f"[mean_reversion] {signal}: entry ${price:,.0f} | stop ${result['stop_loss']:,.0f} | TP1 ${tp_partial:,.0f} | TP2 ${tp_primary:,.0f} | R:R {result['rr_ratio']} | Size {pos_size}%")
    else:
        fails = [k for k, v in (long_checks | short_checks).items() if v is False or (isinstance(v, str) and ('FAIL' in v or 'BLOCKED' in v))]
        print(f"[mean_reversion] No signal — failing checks: {fails[:4]}")
    print(f"[mean_reversion] Written to data/playbook_mean_reversion.json")
    return 0


def write_output(data):
    import json as _json
    DATA_DIR.mkdir(exist_ok=True)
    out = DATA_DIR / "playbook_mean_reversion.json"
    tmp = out.with_name(f".{out.name}.tmp")
    with open(tmp, "w") as f:
        _json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, out)


if __name__ == "__main__":
    sys.exit(main())
