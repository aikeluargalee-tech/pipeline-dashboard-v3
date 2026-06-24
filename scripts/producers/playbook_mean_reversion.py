#!/usr/bin/env python3
"""
Mean Reversion Playbook — per GetClaw spec (June 24, 2026)
Activated by Regime Switch when RANGING detected.
Fades overbought/oversold at Bollinger Band extremes.

Mode selection:
  TIGHT_MODE: confidence HIGH/MEDIUM + ATR < 0.8%
  LOOSE_MODE: confidence LOW or ATR >= 0.8%

Output: data/playbook_mean_reversion.json
"""
import sys, os, json
from datetime import datetime, timezone
import urllib.request

SITE = "/home/maswilee/projects/pipeline-dashboard-v3"
DATA_DIR = os.path.join(SITE, "data")
OUTPUT = os.path.join(DATA_DIR, "playbook_mean_reversion.json")

# ── Helpers ──

def load_json(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None

def fetch_klines(symbol="BTCUSDT", interval="1h", limit=50):
    """Fetch OHLCV klines from Binance public API (no auth)."""
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        closes = [float(c[4]) for c in data]
        highs = [float(c[2]) for c in data]
        lows = [float(c[3]) for c in data]
        return {"close": closes, "high": highs, "low": lows}
    except Exception as e:
        print(f"[mean_reversion] Failed to fetch klines: {e}")
        return None

def calc_rsi(closes, period=14):
    """Calculate RSI for given period."""
    if len(closes) < period + 1:
        return [None] * len(closes)
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [max(d, 0) for d in deltas]
    losses = [max(-d, 0) for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    rsi = [None] * len(closes)
    if avg_loss == 0:
        rsi[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi[period] = 100.0 - (100.0 / (1.0 + rs))
    for i in range(period + 1, len(closes)):
        avg_gain = (avg_gain * (period - 1) + gains[i-1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i-1]) / period
        if avg_loss == 0:
            rsi[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[i] = 100.0 - (100.0 / (1.0 + rs))
    return rsi

def calc_stoch_rsi(closes, rsi_period=14, stoch_period=14, k_period=3, d_period=3):
    """Calculate Stochastic RSI."""
    rsi = calc_rsi(closes, rsi_period)
    valid_rsi = [v for v in rsi if v is not None]
    if len(valid_rsi) < stoch_period:
        return None, None

    # Last stoch_period values
    window = valid_rsi[-stoch_period:]
    min_rsi = min(window)
    max_rsi = max(window)

    if max_rsi == min_rsi:
        k = 50.0
    else:
        k = (valid_rsi[-1] - min_rsi) / (max_rsi - min_rsi) * 100

    # %K is smoothed with SMA(k_period)
    # For simplicity, return raw K and smoothed K from last k_period values
    recent_k = []
    for i in range(len(valid_rsi) - k_period, len(valid_rsi)):
        w = valid_rsi[max(0, i - stoch_period + 1):i+1]
        if len(w) < 2 or max(w) == min(w):
            recent_k.append(50.0)
        else:
            recent_k.append((valid_rsi[i] - min(w)) / (max(w) - min(w)) * 100)

    k_smoothed = sum(recent_k) / len(recent_k) if recent_k else k
    return k_smoothed, k  # smoothed K, raw K


# ── Main ──

def main():
    now = datetime.now(timezone.utc)

    # Load regime switch
    regime = load_json(os.path.join(DATA_DIR, "regime_switch.json"))
    if not regime:
        print("[mean_reversion] No regime_switch.json — exiting")
        return 1

    detected = regime.get("regime", "UNCERTAIN")
    if detected != "RANGING":
        print(f"[mean_reversion] Regime is {detected} — playbook inactive (RANGING only)")
        result = {"status": "inactive", "reason": f"Regime is {detected}, not RANGING", "timestamp": now.isoformat()}
        with open(OUTPUT, "w") as f:
            json.dump(result, f, indent=2)
        return 0

    # Mode selection
    confidence = regime.get("confidence", "LOW")
    # Get ATR from supplementary
    supp = load_json(os.path.join(DATA_DIR, "supplementary.json"))
    atr_pct = supp.get("atr_pct", 999) if supp else 999

    tight_mode = confidence in ("HIGH", "MEDIUM") and atr_pct < 0.8
    mode = "TIGHT" if tight_mode else "LOOSE"

    # Load market data
    liq = load_json(os.path.join(DATA_DIR, "liquidity_status.json"))
    market = load_json("/tmp/btc_market_state.json")
    amt_feed = load_json("/tmp/amt_feed.json")

    # Extract indicators
    price = None
    bb_upper = bb_lower = bb_mid = None
    taker_ratio = None
    cvd_trend = None
    funding_rate = None
    atr_value = None

    if amt_feed:
        price = amt_feed.get("btc_spot")
        amt_funding = amt_feed.get("funding", {})
        if amt_funding:
            funding_rate = amt_funding.get("rate")

    if supp:
        bb_upper = supp.get("bb_upper")
        bb_lower = supp.get("bb_lower")
        bb_mid = supp.get("bb_mid")
        atr_value = supp.get("atr_14")
        if price is None:
            price = supp.get("price")

    if liq:
        if taker_ratio is None:
            taker_ratio = liq.get("taker_buy_ratio")
        if cvd_trend is None:
            cvd_trend = liq.get("cvd_trend", "UNKNOWN")
        if funding_rate is None:
            funding_rate = liq.get("funding_rate")

    if market:
        if price is None:
            price = market.get("current_price")
        if taker_ratio is None:
            taker_ratio = market.get("taker_buy_ratio")
        if funding_rate is None:
            funding_rate = market.get("funding_rate")

    if price is None:
        print("[mean_reversion] No price data — exiting")
        return 1

    # Fetch klines for Stoch RSI
    klines = fetch_klines()
    stoch_k = None
    if klines and len(klines["close"]) >= 30:
        stoch_k, _ = calc_stoch_rsi(klines["close"])
        print(f"[mean_reversion] Stoch RSI K = {stoch_k:.1f}" if stoch_k else "[mean_reversion] Stoch RSI: insufficient data")
    else:
        print("[mean_reversion] Stoch RSI: klines unavailable")

    # ── Entry Checks ──

    long_entry = False
    short_entry = False
    long_checks = {}
    short_checks = {}

    if tight_mode:
        # TIGHT_MODE Long
        long_checks["bb_lower"] = price <= bb_lower if bb_lower else False
        long_checks["stoch_rsi"] = stoch_k is not None and stoch_k < 20
        long_checks["taker"] = taker_ratio is not None and taker_ratio > 0.45
        long_checks["cvd"] = cvd_trend is not None and cvd_trend != "NEGATIVE"
        long_checks["funding"] = funding_rate is not None and funding_rate < 0.0005
        long_entry = all(long_checks.values())

        # TIGHT_MODE Short
        short_checks["bb_upper"] = price >= bb_upper if bb_upper else False
        short_checks["stoch_rsi"] = stoch_k is not None and stoch_k > 80
        short_checks["taker"] = taker_ratio is not None and taker_ratio < 0.55
        short_checks["cvd"] = cvd_trend is not None and cvd_trend != "POSITIVE"
        short_checks["funding"] = funding_rate is not None and funding_rate > -0.0005
        short_entry = all(short_checks.values())

    else:
        # LOOSE_MODE Long
        long_checks["bb_lower"] = price <= bb_lower if bb_lower else False
        long_checks["stoch_rsi"] = stoch_k is not None and stoch_k < 25
        # Confirmations (not required individually)
        taker_ok = taker_ratio is not None and taker_ratio > 0.40
        funding_ok = funding_rate is not None and funding_rate < 0.0005
        confirmations = sum([taker_ok, funding_ok])
        long_entry = long_checks["bb_lower"] and long_checks["stoch_rsi"] and confirmations >= 1

        # LOOSE_MODE Short
        short_checks["bb_upper"] = price >= bb_upper if bb_upper else False
        short_checks["stoch_rsi"] = stoch_k is not None and stoch_k > 75
        # Short bias note: avoid aggressive shorts when 12% below MA50
        ma50 = supp.get("ma50", price * 1.5) if supp else price * 1.5
        below_ma50 = price < ma50 * 0.95  # >5% below MA50
        taker_weak = taker_ratio is not None and taker_ratio < 0.45
        cvd_negative = cvd_trend == "NEGATIVE"
        if below_ma50 and not (taker_weak and cvd_negative):
            short_entry = False
            short_checks["ma50_guard"] = "Blocked — price significantly below MA50 without strong sell momentum"
        else:
            short_entry = short_checks["bb_upper"] and short_checks["stoch_rsi"]

    # ── Stop & TP Calculation ──
    if atr_value is None or atr_value <= 0 or price <= 0:
        atr_value = price * 0.02  # fallback 2%

    stop_mult = 1.0 if tight_mode else 1.5
    stop_distance = stop_mult * atr_value

    # Take-profit: return to SMA20 (bb_mid)
    tp_primary = bb_mid
    tp_secondary_pct = 0.5 * (atr_value / price)  # 0.5x ATR as %

    # ── Build Result ──
    result = {
        "status": "active",
        "mode": mode,
        "timestamp": now.isoformat(),
        "btc_price": price,
        "atr": round(atr_value, 2),
        "atr_pct": round(atr_pct, 2),
        "stop_multiplier": stop_mult,
        "stop_distance_usd": round(stop_distance, 2),
        "indicators": {
            "bb_upper": bb_upper,
            "bb_lower": bb_lower,
            "bb_mid": bb_mid,
            "stoch_rsi_k": round(stoch_k, 1) if stoch_k else None,
            "taker_buy_ratio": taker_ratio,
            "cvd_trend": cvd_trend,
            "funding_rate": round(funding_rate * 100, 4) if funding_rate else None,
        },
        "long_signal": {
            "entry": long_entry,
            "entry_price": price if long_entry else None,
            "stop_loss": round(price - stop_distance, 2) if long_entry else None,
            "tp_primary": round(tp_primary, 2) if long_entry and tp_primary else None,
            "tp_secondary_pct": round(tp_secondary_pct * 100, 1) if long_entry else None,
            "checks": long_checks,
        },
        "short_signal": {
            "entry": short_entry,
            "entry_price": price if short_entry else None,
            "stop_loss": round(price + stop_distance, 2) if short_entry else None,
            "tp_primary": round(tp_primary, 2) if short_entry and tp_primary else None,
            "tp_secondary_pct": round(tp_secondary_pct * 100, 1) if short_entry else None,
            "checks": short_checks,
        },
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT, "w") as f:
        json.dump(result, f, indent=2)

    # Summary
    sig = "LONG" if long_entry else ("SHORT" if short_entry else "NONE")
    print(f"[mean_reversion] Mode: {mode} | Signal: {sig} | Price: ${price:,.0f} | ATR: {atr_pct:.2f}%")
    if long_entry:
        print(f"[mean_reversion] LONG entry: ${price:,.0f} | Stop: ${price - stop_distance:,.0f} | TP: ${tp_primary:,.0f}")
    elif short_entry:
        print(f"[mean_reversion] SHORT entry: ${price:,.0f} | Stop: ${price + stop_distance:,.0f} | TP: ${tp_primary:,.0f}")
    print(f"[mean_reversion] Written to {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
