#!/usr/bin/env python3
"""
Liquidation Momentum Playbook v1.0 — per GetClaw spec (June 24, 2026).
Activated when Regime Switch = CASCADE.

Bias: predominantly SHORT (long liquidation cascades).
Long entries rare — short squeeze only, CAUTIOUS mode always.

Architecture:
  playbooks/regime_gate.py          → shared regime validation
  config.json                       → all thresholds
  playbook.py                       → this file
  idle_monitor.py                   → pre-CASCADE watch (RANGING)

Output: data/playbook_liquidation_momentum.json
"""
import sys, os, json, math
from datetime import datetime, timezone
from pathlib import Path
import urllib.request

PLAYBOOK_DIR = Path(__file__).parent
SITE = Path("/home/maswilee/projects/pipeline-dashboard-v3")
DATA_DIR = SITE / "data"
sys.path.insert(0, str(SITE / "playbooks"))

from regime_gate import get_regime, get_liquidity, compute_mode


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


def load_amt():
    return load_json("/tmp/amt_feed.json")


def load_gate0():
    return load_json(DATA_DIR / "gate0.json")


def fetch_klines(symbol="BTCUSDT", interval="1h", limit=30):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        return {
            "close": [float(c[4]) for c in data],
            "high":  [float(c[2]) for c in data],
            "low":   [float(c[3]) for c in data],
            "volume":[float(c[5]) for c in data],
        }
    except Exception as e:
        print(f"[liq_momentum] klines fetch failed: {e}")
        return None


# ═══════════════════════════════════════
# INDICATORS
# ═══════════════════════════════════════

def cvd_series(klines):
    """Approximate CVD from kline close deltas × volume."""
    vals = []
    cum = 0
    for i in range(1, len(klines["close"])):
        delta = klines["close"][i] - klines["close"][i-1]
        cum += delta * klines["volume"][i]
        vals.append(cum)
    return vals


def cvd_making_new_lows(cvd_vals, lookback=3):
    """Is CVD making new session lows?"""
    if len(cvd_vals) < lookback + 2:
        return False
    recent = cvd_vals[-lookback:]
    prior = cvd_vals[-lookback-2:-lookback]
    return min(recent) < min(prior)


def cvd_steepening(cvd_vals, lookback=3):
    """Is CVD decline accelerating?"""
    if len(cvd_vals) < lookback + 3:
        return False
    recent_slope = cvd_vals[-1] - cvd_vals[-lookback]
    prior_slope = cvd_vals[-lookback] - cvd_vals[-lookback*2] if len(cvd_vals) >= lookback*2 else 0
    return recent_slope < prior_slope and recent_slope < 0


def cvd_diverging_up(cvd_vals, lookback=4):
    """CVD rising while price falling (bullish divergence)."""
    if len(cvd_vals) < lookback + 2:
        return False
    recent = cvd_vals[-lookback:]
    return recent[-1] > recent[0]


def cvd_consolidating(cvd_vals, candles=2):
    """CVD flat/consolidating for N candles."""
    if len(cvd_vals) < candles + 1:
        return False
    window = cvd_vals[-candles-1:]
    diffs = [abs(window[i] - window[i-1]) for i in range(1, len(window))]
    avg_change = sum(diffs) / len(diffs)
    avg_val = sum(abs(v) for v in window) / len(window)
    return avg_val > 0 and avg_change / avg_val < 0.02  # less than 2% change


def candle_deltas(klines):
    """Per-candle delta: close - open."""
    return [klines["close"][i] - klines["open"][i] for i in range(len(klines["close"]))]


# ═══════════════════════════════════════
# ENTRY CHECKS
# ═══════════════════════════════════════

def check_short_entry(mode, cfg, regime_signals, amt, liq, klines):
    """Check all short entry conditions. Returns (passed, checks_dict)."""
    rules = cfg["entry"]["short"][mode.lower()]
    checks = {}
    cvd_vals = cvd_series(klines)
    deltas = candle_deltas(klines)

    # 1. Price vs 20h high
    pv = regime_signals.get("price_vs_20h_high")
    checks["price_vs_20h_high"] = pv is not None and pv <= rules["price_vs_20h_high_max"]

    # 2. Taker buy ratio
    taker = None
    if amt:
        tv = amt.get("taker_volume", {})
        ratio_raw = tv.get("ratio_24h")
        if ratio_raw is not None:
            taker = ratio_raw / (1 + ratio_raw) if ratio_raw > 0 else 0.5
    checks["taker_ratio"] = taker is not None and taker < rules["taker_ratio_max"]

    # 3. OI change — negative (longs exiting)
    oi = None
    if amt:
        oi = amt.get("funding", {}).get("oi_change_1h")
    checks["oi_declining"] = oi is not None and oi < 0
    if mode == "CAUTIOUS" and rules.get("oi_accelerating"):
        # Check if OI decline is accelerating (compared to prior hour)
        oi_24h = amt.get("funding", {}).get("oi_change_24h") if amt else None
        checks["oi_accelerating"] = oi is not None and oi_24h is not None and oi < oi_24h / 24

    # 4. CVD making new session lows
    checks["cvd_new_lows"] = cvd_making_new_lows(cvd_vals)
    if mode == "CAUTIOUS":
        checks["cvd_steepening"] = cvd_steepening(cvd_vals)

    # 5. Candle delta negative N candles
    neg_count = sum(1 for d in deltas[-rules["candle_delta_negative_candles"]:] if d < 0)
    checks["candle_delta"] = neg_count == rules["candle_delta_negative_candles"]

    # 6. Liquidity
    liq_verdict = liq.get("liquidity_verdict", "UNKNOWN") if liq else "UNKNOWN"
    checks["liquidity"] = liq_verdict not in rules["liquidity_disallowed"]

    # All required
    required = ["price_vs_20h_high", "taker_ratio", "oi_declining", "cvd_new_lows", "candle_delta", "liquidity"]
    if mode == "CAUTIOUS":
        required.append("cvd_steepening")
    passed = all(checks.get(k, False) for k in required)
    return passed, checks


def check_long_entry(amt, klines, gate0, cfg):
    """Long entry — short squeeze only. CAUTIOUS always."""
    rules = cfg["entry"]["long"]
    checks = {}
    cvd_vals = cvd_series(klines)

    # 1. CVD diverging UP (bullish divergence — price down, CVD up)
    checks["cvd_diverging"] = cvd_diverging_up(cvd_vals)

    # 2. Taker recovering from < 35% to above 40%
    taker = None
    if amt:
        tv = amt.get("taker_volume", {})
        ratio_raw = tv.get("ratio_24h")
        if ratio_raw is not None:
            taker = ratio_raw / (1 + ratio_raw)
    checks["taker_recovering"] = taker is not None and taker > rules["taker_recovering_from_below_35_to_above"]

    # 3. OI declining
    oi = amt.get("funding", {}).get("oi_change_1h") if amt else None
    checks["oi_declining"] = oi is not None and oi < 0

    # 4. Funding extreme negative (< -0.03%)
    funding = amt.get("funding", {}).get("rate") if amt else None
    checks["funding_extreme"] = funding is not None and funding < rules["funding_below"]

    # 5. Black Swan = 0
    bs = gate0.get("modules", {}).get("black_swan", {}).get("state", "PROCEED") if gate0 else "PROCEED"
    checks["black_swan_clear"] = bs == "PROCEED"

    passed = all(checks.values())
    return passed, checks


# ═══════════════════════════════════════
# INVALIDATION
# ═══════════════════════════════════════

def check_invalidation(regime_data, amt, liq, gate0, cfg, direction, cvd_vals, klines):
    """Check all 6 invalidation criteria. Returns list of active triggers."""
    triggers = []

    # 1. Regime flip
    if regime_data.get("regime") != "CASCADE":
        triggers.append(f"regime_flip: now {regime_data.get('regime')}")

    # 2. OI stabilization
    oi = amt.get("funding", {}).get("oi_change_1h") if amt else None
    if oi is not None and oi >= cfg["invalidation"]["oi_stabilization_threshold"]:
        triggers.append(f"oi_stabilized: OI change {oi:.1f}%")

    # 3. Taker recovery + positive candle delta
    taker = None
    if amt:
        tv = amt.get("taker_volume", {})
        ratio_raw = tv.get("ratio_24h")
        if ratio_raw is not None:
            taker = ratio_raw / (1 + ratio_raw)
    deltas = candle_deltas(klines) if klines else []
    last_delta = deltas[-1] if deltas else 0
    if taker is not None and taker > cfg["invalidation"]["taker_recovery_ratio"] and last_delta > 0:
        triggers.append(f"taker_recovery: ratio {taker:.3f} + positive candle")

    # 4. Black Swan spike
    if gate0:
        bs_module = gate0.get("modules", {}).get("black_swan", {})
        bs_detail = bs_module.get("detail", "")
        if "score:" in bs_detail:
            try:
                score = int(bs_detail.split("score:")[1].split("/")[0].strip())
                if score >= cfg["invalidation"]["black_swan_threshold"]:
                    triggers.append(f"black_swan: score {score}/{cfg['invalidation']['black_swan_threshold']}")
            except:
                pass

    # 5. Liquidity collapse
    liq_verdict = liq.get("liquidity_verdict", "UNKNOWN") if liq else "UNKNOWN"
    if liq_verdict in cfg["invalidation"]["liquidity_kill"]:
        triggers.append(f"liquidity_collapse: {liq_verdict}")

    # 6. CVD divergence — momentum exhausted (Tier 3 runner only)
    if direction == "SHORT" and cvd_consolidating(cvd_vals, cfg["invalidation"]["cvd_consolidation_candles"]):
        triggers.append("cvd_consolidating: momentum exhausted (runner only)")

    return triggers


# ═══════════════════════════════════════
# POSITION SIZING
# ═══════════════════════════════════════

def compute_position_size(confidence, mode, cfg):
    base = cfg["sizing"]["base_risk_pct"].get(confidence, 0.75)
    scalar = cfg["sizing"]["size_scalar"].get(mode, 0.6)
    return round(base * scalar, 2)


# ═══════════════════════════════════════
# IDLE MONITOR (pre-CASCADE watch)
# ═══════════════════════════════════════

def idle_monitor(regime_data, amt, cfg):
    """Pre-CASCADE watch when regime is RANGING. Returns dict or None."""
    if regime_data.get("regime") != "RANGING":
        return None

    im = cfg["idle_monitor"]["pre_cascade"]
    oi = amt.get("funding", {}).get("oi_change_1h") if amt else None
    taker = None
    if amt:
        tv = amt.get("taker_volume", {})
        ratio_raw = tv.get("ratio_24h")
        if ratio_raw is not None:
            taker = ratio_raw / (1 + ratio_raw)
    pv = regime_data.get("price_vs_20h_high")

    pre = (
        oi is not None and oi < im["oi_change_1h_threshold"] and
        taker is not None and taker < im["taker_ratio_max"] and
        pv is not None and pv < im["price_vs_20h_high_max"]
    )

    if pre:
        return {
            "watch_state": "ELEVATED",
            "oi_change_1h": oi,
            "taker_ratio": round(taker, 3),
            "price_vs_20h_high": pv,
            "message": "Pre-CASCADE conditions — OI declining, taker weakening, price drifting from 20h high. No entry. Monitoring only."
        }
    return {"watch_state": "NORMAL", "message": "No pre-CASCADE signals"}


# ═══════════════════════════════════════
# MAIN
# ═══════════════════════════════════════

def main():
    now = datetime.now(timezone.utc)
    cfg = load_config()
    if not cfg:
        print("[liq_momentum] config.json missing — exiting")
        return 1

    regime = get_regime()
    if not regime:
        write_output({"status": "offline", "reason": "No regime data", "timestamp": now.isoformat()})
        return 0

    detected = regime.get("regime", "UNCERTAIN")

    # ── Idle monitor for RANGING ──
    if detected == "RANGING":
        amt = load_amt()
        watch = idle_monitor(regime, amt, cfg)
        result = {
            "status": "idle",
            "reason": "Regime is RANGING — CASCADE not active",
            "watch": watch,
            "timestamp": now.isoformat(),
            "btc_price": regime.get("btc_price"),
        }
        write_output(result)
        state = watch.get("watch_state", "NORMAL") if watch else "NORMAL"
        print(f"[liq_momentum] Idle — RANGING. Pre-CASCADE watch: {state}")
        if state == "ELEVATED":
            print(f"[liq_momentum] ⚠ OI={watch.get('oi_change_1h')}% | Taker={watch.get('taker_ratio')} | Price vs 20h high={watch.get('price_vs_20h_high')}%")
        return 0

    if detected != "CASCADE":
        result = {"status": "inactive", "reason": f"Regime is {detected}, not CASCADE", "timestamp": now.isoformat()}
        write_output(result)
        print(f"[liq_momentum] Inactive — regime is {detected}")
        return 0

    # ── ACTIVE: CASCADE confirmed ──
    confidence = regime.get("confidence", "MEDIUM")
    mode = "AGGRESSIVE" if confidence == "HIGH" else "CAUTIOUS"

    # Stale data check
    data_age = regime.get("data_age_minutes", 0)
    if data_age >= cfg["time_limits"]["stale_data_cutoff_minutes"]:
        result = {"status": "inactive", "reason": f"Regime data stale ({data_age}min)", "timestamp": now.isoformat()}
        write_output(result)
        print(f"[liq_momentum] Stale data ({data_age}min) — cannot trade")
        return 0

    amt = load_amt()
    liq = get_liquidity()
    gate0 = load_gate0()
    klines = fetch_klines()

    if not klines or len(klines["close"]) < 10:
        print("[liq_momentum] Insufficient kline data")
        write_output({"status": "offline", "reason": "Klines unavailable", "timestamp": now.isoformat()})
        return 0

    price = klines["close"][-1]
    cvd_vals = cvd_series(klines)
    regime_signals = {
        "price_vs_20h_high": regime.get("price_vs_20h_high"),
    }

    # ── Entry checks ──
    short_passed, short_checks = check_short_entry(mode, cfg, regime_signals, amt, liq, klines)
    long_passed, long_checks = check_long_entry(amt, klines, gate0, cfg)

    # ── Stop & TP ──
    atr_norm = regime.get("atr_normalized", 1.85) if isinstance(regime.get("atr_normalized"), (int, float)) else 1.85
    atr_price = price * (atr_norm / 100)
    stop_mult = cfg["stops"][mode.lower()]["atr_mult"]
    stop_distance = stop_mult * atr_price

    # Structural hard stop for shorts
    high_20h = None
    if amt:
        high_20h = amt.get("high_24h")  # proxy for 20h high
    hard_stop = None
    if high_20h and short_passed:
        hard_stop = max(price + stop_distance, high_20h * cfg["stops"]["structural_hard_stop_mult"])

    # R:R check
    rr = None
    tp_cfg = cfg["take_profit"]
    if short_passed:
        tp2 = price - (tp_cfg["tier2_atr_mult"] * atr_price)
        reward = price - tp2
        risk = (hard_stop or (price + stop_distance)) - price
        rr = round(reward / risk, 2) if risk > 0 else 0
        if rr < tp_cfg["rr_min"]:
            short_passed = False
            short_checks["rr_check"] = f"FAIL: R:R {rr} < {tp_cfg['rr_min']}"

    if long_passed:
        tp2 = price + (tp_cfg["tier2_atr_mult"] * atr_price)
        reward = tp2 - price
        risk = stop_distance
        rr = round(reward / risk, 2) if risk > 0 else 0
        if rr < tp_cfg["rr_min"]:
            long_passed = False
            long_checks["rr_check"] = f"FAIL: R:R {rr} < {tp_cfg['rr_min']}"

    # ── Determine signal ──
    if short_passed:
        signal = "SHORT"
        direction = "SHORT"
    elif long_passed:
        signal = "LONG"
        direction = "LONG"
    else:
        signal = "NO_SIGNAL"
        direction = None

    # ── Invalidation ──
    invalidation_triggers = []
    if signal != "NO_SIGNAL":
        invalidation_triggers = check_invalidation(regime, amt, liq, gate0, cfg, direction, cvd_vals, klines)
        if invalidation_triggers:
            # Filter: only full kills block entry. CVD consolidation only kills runner.
            full_kills = [t for t in invalidation_triggers if "runner only" not in t]
            if full_kills:
                signal = "NO_SIGNAL"
                direction = None

    # ── TP levels ──
    tp1 = tp2 = None
    if signal == "SHORT":
        tp1 = round(price - tp_cfg["tier1_atr_mult"] * atr_price, 2)
        tp2 = round(price - tp_cfg["tier2_atr_mult"] * atr_price, 2)
    elif signal == "LONG":
        tp1 = round(price + tp_cfg["tier1_atr_mult"] * atr_price, 2)
        tp2 = round(price + tp_cfg["tier2_atr_mult"] * atr_price, 2)

    # ── Size ──
    pos_size = compute_position_size(confidence, mode, cfg)

    # ── Time limit ──
    max_hold = cfg["time_limits"][f"{mode.lower()}_max_hold_hours"]

    # ── Early exit check ──
    early_exit = False
    if signal == "SHORT":
        taker = None
        if amt:
            tv = amt.get("taker_volume", {})
            ratio_raw = tv.get("ratio_24h")
            if ratio_raw is not None:
                taker = ratio_raw / (1 + ratio_raw)
        if taker is not None and taker > tp_cfg["early_exit_taker_ratio"]:
            early_exit = True

    # ── Build output ──
    result = {
        "strategy": cfg["strategy"],
        "version": cfg["version"],
        "status": "active",
        "mode": mode,
        "signal": signal,
        "direction": direction,
        "timestamp": now.isoformat(),
        "btc_price": round(price, 2),
        "atr_pct": round(atr_norm, 2),
        "atr_price": round(atr_price, 2),
        "confidence": confidence,
        "position_size_pct": pos_size,
        "max_hold_hours": max_hold,
        "stop_distance_usd": round(stop_distance, 2),
        "structural_hard_stop": round(hard_stop, 2) if hard_stop else None,
        "entry_price": round(price, 2) if signal != "NO_SIGNAL" else None,
        "stop_loss": (
            round(hard_stop or (price + stop_distance), 2) if signal == "SHORT"
            else round(price - stop_distance, 2) if signal == "LONG"
            else None
        ),
        "tp1": tp1,
        "tp2": tp2,
        "tp1_position_pct": tp_cfg["tier1_pct"],
        "tp2_position_pct": tp_cfg["tier2_pct"],
        "tp3_position_pct": tp_cfg["tier3_pct"],
        "tp3_trailing_atr_mult": tp_cfg["tier3_trailing_atr_mult"],
        "rr_ratio": rr,
        "early_exit_triggered": early_exit,
        "short_checks": short_checks,
        "long_checks": long_checks,
        "invalidation_triggers": invalidation_triggers,
        "regime": detected,
    }
    write_output(result)

    # ── Summary ──
    print(f"[liq_momentum] CASCADE {confidence} | Mode: {mode} | Signal: {signal} | Price: ${price:,.0f}")
    if signal != "NO_SIGNAL":
        stop_label = f"${result['stop_loss']:,.0f}" + (" (hard)" if hard_stop else "")
        print(f"[liq_momentum] {signal}: entry ${price:,.0f} | stop {stop_label} | TP1 ${tp1:,.0f} | TP2 ${tp2:,.0f} | R:R {rr} | Size {pos_size}%")
        if early_exit:
            print(f"[liq_momentum] ⚠ Early exit triggered — taker recovered above {tp_cfg['early_exit_taker_ratio']}")
    else:
        fails = [k for k, v in short_checks.items() if v is False or (isinstance(v, str) and 'FAIL' in v)]
        print(f"[liq_momentum] No signal — failing: {fails[:4]}")
    if invalidation_triggers:
        print(f"[liq_momentum] Invalidation: {invalidation_triggers}")
    print(f"[liq_momentum] Written to data/playbook_liquidation_momentum.json")
    return 0


def write_output(data):
    DATA_DIR.mkdir(exist_ok=True)
    out = DATA_DIR / "playbook_liquidation_momentum.json"
    tmp = out.with_name(f".{out.name}.tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, out)


if __name__ == "__main__":
    sys.exit(main())
