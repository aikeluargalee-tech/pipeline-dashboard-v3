#!/usr/bin/env python3
"""
Funding Rate Mean Reversion Playbook v1.0 — per GetClaw spec (June 24, 2026).
Activated when RANGING + |funding_rate| > 0.01%.

Direction: LONG when funding < -0.01% (shorts paying), SHORT when > +0.01% (longs crowded).
Mode: EXTREME (≥0.03%) / MODERATE (0.01-0.03%)
Hysteresis: activates at 0.01%, deactivates at 0.008%

Output: data/playbook_funding_rate_mr.json
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
            "open":  [float(c[1]) for c in data],
            "volume":[float(c[5]) for c in data],
        }
    except Exception as e:
        print(f"[funding_mr] klines fetch failed: {e}")
        return None


def calc_rsi(closes, period=14):
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
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def cvd_series(klines):
    vals = []
    cum = 0
    for i in range(1, len(klines["close"])):
        delta = klines["close"][i] - klines["close"][i-1]
        cum += delta * klines["volume"][i]
        vals.append(cum)
    return vals


def cvd_flat_or_upturn(cvd_vals, lookback=4):
    if len(cvd_vals) < lookback + 1:
        return False
    return cvd_vals[-1] >= cvd_vals[-lookback]


def cvd_flat_or_downturn(cvd_vals, lookback=4):
    if len(cvd_vals) < lookback + 1:
        return False
    return cvd_vals[-1] <= cvd_vals[-lookback]


def cvd_flat(cvd_vals, lookback=4):
    if len(cvd_vals) < lookback + 1:
        return False
    window = cvd_vals[-lookback:]
    avg_val = sum(abs(v) for v in window) / len(window) if window else 1
    return avg_val > 0 and abs(cvd_vals[-1] - cvd_vals[-lookback]) / avg_val < 0.03


# ═══════════════════════════════════════
# ENTRY CHECKS
# ═══════════════════════════════════════

def check_entry(mode, direction, cfg, price, rsi_val, amt, liq, cvd_vals):
    """Check all entry conditions for given mode and direction."""
    rules = cfg["entry"][direction.lower()][mode.lower()]
    checks = {}

    # RSI
    if direction == "LONG":
        checks["rsi"] = rsi_val is not None and rsi_val < rules["rsi_max"]
    else:
        checks["rsi"] = rsi_val is not None and rsi_val > rules["rsi_min"]

    # Taker buy ratio
    taker = None
    if amt:
        tv = amt.get("taker_volume", {})
        ratio_raw = tv.get("ratio_24h")
        if ratio_raw is not None:
            taker = ratio_raw / (1 + ratio_raw)
    if direction == "LONG":
        checks["taker"] = taker is not None and taker > rules["taker_ratio_min"]
    else:
        checks["taker"] = taker is not None and taker < rules["taker_ratio_max"]

    # OI delta
    oi = amt.get("funding", {}).get("oi_change_1h") if amt else 0
    if oi > 2:
        oi_label = "EXPANDING"
    elif oi < -2:
        oi_label = "DECLINING"
    else:
        oi_label = "FLAT"
    checks["oi_delta"] = oi_label in rules["oi_delta_allowed"]

    # CVD
    cvd_req = rules["cvd_required"]
    if cvd_req == "flat_or_upturn":
        checks["cvd"] = cvd_flat_or_upturn(cvd_vals) or cvd_flat(cvd_vals)
    elif cvd_req == "flat_or_downturn":
        checks["cvd"] = cvd_flat_or_downturn(cvd_vals) or cvd_flat(cvd_vals)
    else:
        checks["cvd"] = cvd_flat(cvd_vals)

    # Liquidity
    liq_verdict = liq.get("liquidity_verdict", "UNKNOWN") if liq else "UNKNOWN"
    checks["liquidity"] = liq_verdict in rules["liquidity_allowed"]

    passed = all(checks.values())
    return passed, checks


# ═══════════════════════════════════════
# INVALIDATION
# ═══════════════════════════════════════

def check_invalidation(regime_data, amt, liq, cfg, direction, funding_rate, cvd_vals):
    triggers = []

    # 1. Regime flip
    if regime_data.get("regime") != "RANGING":
        triggers.append(f"regime_flip: {regime_data.get('regime')}")

    # 2. Funding flips to opposite extreme
    if direction == "SHORT" and funding_rate < -cfg["invalidation"]["funding_flip_threshold"]:
        triggers.append(f"funding_flipped: {funding_rate*100:.4f}% — shorts now crowded")
    if direction == "LONG" and funding_rate > cfg["invalidation"]["funding_flip_threshold"]:
        triggers.append(f"funding_flipped: {funding_rate*100:.4f}% — longs now crowded")

    # 3. OI accelerates wrong direction
    oi = amt.get("funding", {}).get("oi_change_1h") if amt else 0
    inv = cfg["invalidation"]
    if direction == "LONG" and oi < inv["oi_wrong_direction"]["long_floor"]:
        triggers.append(f"oi_accelerating_wrong: {oi:.1f}% — forced liquidation risk")
    if direction == "SHORT" and oi > inv["oi_wrong_direction"]["short_ceiling"]:
        triggers.append(f"oi_accelerating_wrong: +{oi:.1f}% — forced short squeeze risk")

    # 4. Taker divergence
    taker = None
    if amt:
        tv = amt.get("taker_volume", {})
        ratio_raw = tv.get("ratio_24h")
        if ratio_raw is not None:
            taker = ratio_raw / (1 + ratio_raw)
    if direction == "LONG" and taker is not None and taker < inv["taker_divergence"]["long_min"]:
        triggers.append(f"taker_divergence: {taker:.3f} — sellers overwhelming")
    if direction == "SHORT" and taker is not None and taker > inv["taker_divergence"]["short_max"]:
        triggers.append(f"taker_divergence: {taker:.3f} — buyers overwhelming")

    # 5. Liquidity collapse
    liq_verdict = liq.get("liquidity_verdict", "UNKNOWN") if liq else "UNKNOWN"
    if liq_verdict in inv["liquidity_kill"]:
        triggers.append(f"liquidity_collapse: {liq_verdict}")

    # 6. Funding normalized (hand back to Mean Reversion)
    if abs(funding_rate) < inv["funding_normalized"]:
        triggers.append(f"funding_normalized: {funding_rate*100:.4f}% — hand back to Mean Reversion")

    return triggers


# ═══════════════════════════════════════
# SIZING
# ═══════════════════════════════════════

def compute_position_size(mode, confidence, cfg):
    base = cfg["sizing"]["base_risk_pct"][mode.lower()]
    scalar = cfg["sizing"]["conf_scalar"].get(confidence, 0.5)
    cap = base * cfg["sizing"]["hard_cap_mult"]
    return min(round(base * scalar, 2), round(cap, 2))


# ═══════════════════════════════════════
# MAIN
# ═══════════════════════════════════════

def main():
    now = datetime.now(timezone.utc)
    cfg = load_config()
    if not cfg:
        print("[funding_mr] config.json missing")
        return 1

    regime = get_regime()
    if not regime:
        write_output({"status": "offline", "reason": "No regime data", "timestamp": now.isoformat()})
        return 0

    detected = regime.get("regime", "UNCERTAIN")
    amt = load_amt()
    funding_rate = amt.get("funding", {}).get("rate") if amt else None

    # ── Activation gate ──
    if detected != "RANGING" or funding_rate is None or abs(funding_rate) <= cfg["activation"]["funding_abs_min"]:
        # Idle monitor
        pre_alert = (
            detected == "RANGING" and funding_rate is not None and
            abs(funding_rate) > cfg["idle_monitor"]["pre_alert_threshold"]
        )
        watch_state = "ELEVATED" if pre_alert else "NORMAL"
        msg = f"Funding {funding_rate*100:.4f}% — building toward threshold" if pre_alert else "Funding neutral or regime not RANGING"
        result = {
            "status": "idle",
            "reason": f"Funding {funding_rate*100:.4f}% — not above {cfg['activation']['funding_abs_min']*100:.1f}% threshold" if funding_rate else "No funding data",
            "watch": {"watch_state": watch_state, "message": msg, "funding_rate": funding_rate},
            "timestamp": now.isoformat(),
            "btc_price": regime.get("btc_price"),
        }
        write_output(result)
        print(f"[funding_mr] Idle — {watch_state}. Funding: {funding_rate*100:.4f}%" if funding_rate else "[funding_mr] Idle — no funding data")
        return 0

    # ── ACTIVE ──
    conf = regime.get("confidence", "LOW")
    funding_abs = abs(funding_rate)

    # Mode selection
    if funding_abs >= cfg["modes"]["extreme"]["funding_abs_min"]:
        mode = "EXTREME"
    else:
        mode = "MODERATE"

    # Direction
    direction = "LONG" if funding_rate < -cfg["activation"]["funding_abs_min"] else "SHORT"

    # Load data
    liq = get_liquidity()
    klines = fetch_klines()

    if not klines or len(klines["close"]) < 20:
        write_output({"status": "offline", "reason": "Klines unavailable", "timestamp": now.isoformat()})
        return 0

    price = klines["close"][-1]
    rsi_vals = calc_rsi(klines["close"])
    rsi_val = rsi_vals[-1] if rsi_vals and rsi_vals[-1] is not None else None
    mean_20h = rolling_mean(klines["close"], 20)
    cvd_vals = cvd_series(klines)

    # Entry check
    passed, checks = check_entry(mode, direction, cfg, price, rsi_val, amt, liq, cvd_vals)

    # Stops
    atr_norm = regime.get("atr_normalized", 1.85) if isinstance(regime.get("atr_normalized"), (int, float)) else 1.85
    atr_price = price * (atr_norm / 100)
    stop_mult = cfg["stops"][mode.lower()]["atr_mult"]
    stop_distance = stop_mult * atr_price

    # Structural stop
    hard_stop = None
    if direction == "SHORT":
        high_20h = amt.get("high_24h") if amt else None
        if high_20h:
            hard_stop = max(price + stop_distance, high_20h * cfg["stops"]["structural_mult"]["short"])
    else:
        low_20h = amt.get("low_24h") if amt else None
        if low_20h:
            hard_stop = min(price - stop_distance, low_20h * cfg["stops"]["structural_mult"]["long"])

    # R:R
    rr = None
    if passed and mean_20h:
        tp2 = mean_20h
        if direction == "SHORT":
            reward = price - tp2
            risk = (hard_stop or (price + stop_distance)) - price
        else:
            reward = tp2 - price
            risk = price - (hard_stop or (price - stop_distance))
        rr = round(reward / risk, 2) if risk > 0 else 0
        rr_min = cfg["take_profit"]["rr_min"][mode.lower()]
        if rr < rr_min:
            passed = False
            checks["rr_check"] = f"FAIL: R:R {rr} < {rr_min}"

    # Signal
    signal = direction if passed else "NO_SIGNAL"

    # Invalidation
    inval_triggers = []
    if signal != "NO_SIGNAL":
        inval_triggers = check_invalidation(regime, amt, liq, cfg, direction, funding_rate, cvd_vals)
        funding_normalized_triggers = [t for t in inval_triggers if "funding_normalized" in t or "funding_flipped" in t or "regime_flip" in t or "liquidity_collapse" in t]
        if funding_normalized_triggers:
            signal = "NO_SIGNAL"

    # TP
    tp1 = None
    tp2 = mean_20h
    if signal != "NO_SIGNAL":
        tp1 = round(price - cfg["take_profit"]["tier1_atr_mult"] * atr_price, 2) if direction == "SHORT" else round(price + cfg["take_profit"]["tier1_atr_mult"] * atr_price, 2)
        tp2 = round(mean_20h, 2)

    # Size
    pos_size = compute_position_size(mode, conf, cfg)

    # Time limit
    max_hold = cfg["time_limits"][f"{mode.lower()}_max_hold_hours"]

    # Build output
    stop_price = (
        round(hard_stop or (price + stop_distance), 2) if direction == "SHORT"
        else round(hard_stop or (price - stop_distance), 2)
    )

    result = {
        "strategy": cfg["strategy"],
        "version": cfg["version"],
        "status": "active",
        "mode": mode,
        "direction": direction,
        "signal": signal,
        "timestamp": now.isoformat(),
        "btc_price": round(price, 2),
        "funding_rate": round(funding_rate * 100, 4),
        "atr_pct": round(atr_norm, 2),
        "atr_price": round(atr_price, 2),
        "rsi_14": round(rsi_val, 1) if rsi_val else None,
        "mean_20h": round(mean_20h, 2) if mean_20h else None,
        "confidence": conf,
        "position_size_pct": pos_size,
        "max_hold_hours": max_hold,
        "stop_distance_usd": round(stop_distance, 2),
        "entry_price": round(price, 2) if signal != "NO_SIGNAL" else None,
        "stop_loss": stop_price if signal != "NO_SIGNAL" else None,
        "tp1": tp1,
        "tp2": tp2,
        "tp1_position_pct": cfg["take_profit"]["tier1_pct"],
        "tp2_position_pct": cfg["take_profit"]["tier2_pct"],
        "funding_normalized_exit": cfg["take_profit"]["funding_normalized_exit"] * 100,
        "rr_ratio": rr,
        "checks": checks,
        "invalidation_triggers": inval_triggers,
        "regime": detected,
        "settlement_checkpoint_hours": cfg["settlement_checkpoint"]["interval_hours"],
    }
    write_output(result)

    # Summary
    print(f"[funding_mr] {mode} | {direction} | Signal: {signal} | Funding: {funding_rate*100:.4f}% | Price: ${price:,.0f}")
    if signal != "NO_SIGNAL":
        print(f"[funding_mr] {signal}: entry ${price:,.0f} | stop ${stop_price:,.0f} | TP1 ${tp1:,.0f} | TP2 ${tp2:,.0f} | R:R {rr} | Size {pos_size}%")
    else:
        fails = [k for k, v in checks.items() if v is False or (isinstance(v, str) and 'FAIL' in v)]
        print(f"[funding_mr] No signal — failing: {fails[:4]}")
    print(f"[funding_mr] Written to data/playbook_funding_rate_mr.json")
    return 0


def write_output(data):
    DATA_DIR.mkdir(exist_ok=True)
    out = DATA_DIR / "playbook_funding_rate_mr.json"
    tmp = out.with_name(f".{out.name}.tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, out)


if __name__ == "__main__":
    sys.exit(main())
