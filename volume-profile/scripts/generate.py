#!/usr/bin/env python3
"""
VP V3.1 Data Generator — Enhanced with delta, OI, funding, developing POC, verdict engine.
Produces vp_card.json for the Volume Profile V3 site.
"""
import json, time, math, os, urllib.request
from datetime import datetime, timezone

BIN_STEP = 50
NOISE_BUFFER = 50  # $50 or 0.05% of price — whichever larger
STATE_FILE = "/tmp/vp_sentinel_state.json"

def fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

# ── DATA FETCHING ──────────────────────────────────

def fetch_klines():
    klines = fetch("https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1h&limit=168")
    return klines

def fetch_perp_metrics():
    """Futures: taker buy/sell ratio, OI, funding, 24hr ticker."""
    # Taker buy/sell ratio for last 24h
    taker = fetch("https://fapi.binance.com/futures/data/takerlongshortRatio?symbol=BTCUSDT&period=1h&limit=24")
    buy_vol = sum(float(t["buyVol"]) for t in taker)
    sell_vol = sum(float(t["sellVol"]) for t in taker)
    total_vol = buy_vol + sell_vol
    perp_delta_pct = round((buy_vol - sell_vol) / max(total_vol, 0.001) * 100, 2)

    # OI
    oi = fetch("https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT")
    oi_current = float(oi["openInterest"])

    # OI 1h ago
    oi_hist = fetch("https://fapi.binance.com/futures/data/openInterestHist?symbol=BTCUSDT&period=1h&limit=2")
    if len(oi_hist) >= 2:
        oi_1h_ago = float(oi_hist[0]["sumOpenInterest"])
        oi_change_pct = round((oi_current - oi_1h_ago) / max(oi_1h_ago, 0.001) * 100, 2)
    else:
        oi_change_pct = 0.0

    # Funding rate
    prem = fetch("https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT")
    funding_rate = float(prem["lastFundingRate"])
    mark_price = float(prem["markPrice"])

    # 24hr ticker for volume context
    ticker = fetch("https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=BTCUSDT")
    perp_24h_vol = float(ticker["volume"])  # in BTC

    return {
        "perp_delta_pct": perp_delta_pct,
        "perp_buy_vol": round(buy_vol),
        "perp_sell_vol": round(sell_vol),
        "oi_current": round(oi_current),
        "oi_change_pct": oi_change_pct,
        "funding_rate": round(funding_rate * 100, 4),  # as percentage
        "mark_price": round(mark_price),
        "perp_24h_vol": round(perp_24h_vol)
    }

def fetch_spot_metrics():
    """Spot delta from 24hr ticker + recent trades sample."""
    ticker = fetch("https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT")
    spot_24h_vol = float(ticker["volume"])
    quote_vol = float(ticker["quoteVolume"])

    # Estimate spot delta from recent aggTrades (sample last 1000)
    trades = fetch("https://api.binance.com/api/v3/aggTrades?symbol=BTCUSDT&limit=1000")
    buy_vol = sum(float(t["q"]) for t in trades if not t["m"])  # m=false = buyer is taker = aggressive buy
    sell_vol = sum(float(t["q"]) for t in trades if t["m"])     # m=true = seller is taker = aggressive sell
    total = buy_vol + sell_vol
    spot_delta_pct = round((buy_vol - sell_vol) / max(total, 0.001) * 100, 2)

    return {
        "spot_delta_pct": spot_delta_pct,
        "spot_24h_vol": round(spot_24h_vol),
        "spot_quote_vol": round(quote_vol)
    }

# ── VOLUME PROFILE ─────────────────────────────────

def build_bins(klines):
    bins = {}
    for k in klines:
        high, low, vol = float(k[2]), float(k[3]), float(k[5])
        lo_bin = int(low // BIN_STEP) * BIN_STEP
        hi_bin = int(high // BIN_STEP) * BIN_STEP
        if hi_bin == lo_bin:
            bins[lo_bin] = bins.get(lo_bin, 0) + vol
        else:
            n_bins = (hi_bin - lo_bin) // BIN_STEP + 1
            vol_per_bin = vol / n_bins
            for lvl in range(lo_bin, hi_bin + BIN_STEP, BIN_STEP):
                bins[lvl] = bins.get(lvl, 0) + vol_per_bin
    return bins

def compute_va(bins, total_vol):
    sorted_prices = sorted(bins.keys())
    sorted_by_vol = sorted(bins.items(), key=lambda x: x[1], reverse=True)
    poc = sorted_by_vol[0][0]

    va_target = total_vol * 0.7
    va_vol = bins[poc]
    va_low, va_high = poc, poc
    poc_idx = sorted_prices.index(poc)
    lo_i, hi_i = poc_idx, poc_idx

    while va_vol < va_target:
        expand_lo = bins.get(sorted_prices[lo_i - 1], 0) if lo_i > 0 else 0
        expand_hi = bins.get(sorted_prices[hi_i + 1], 0) if hi_i < len(sorted_prices) - 1 else 0
        if expand_lo == 0 and expand_hi == 0:
            break
        if expand_lo >= expand_hi:
            lo_i -= 1
            va_low = sorted_prices[lo_i]
            va_vol += expand_lo
        else:
            hi_i += 1
            va_high = sorted_prices[hi_i]
            va_vol += expand_hi

    return poc, va_low, va_high

def classify_bin_types(bins, poc, vah, val, hvns, lvns):
    hvn_prices = {h["price"] for h in hvns}
    lvn_prices = {l["price"] for l in lvns}
    result = []
    for price in sorted(bins.keys()):
        vol = round(bins[price])
        if price == poc:
            result.append({"price": price, "volume": vol, "type": "poc"})
        elif price == vah:
            result.append({"price": price, "volume": vol, "type": "vah"})
        elif price == val:
            result.append({"price": price, "volume": vol, "type": "val"})
        elif price in hvn_prices:
            result.append({"price": price, "volume": vol, "type": "hvn"})
        elif price in lvn_prices:
            result.append({"price": price, "volume": vol, "type": "lvn"})
        else:
            result.append({"price": price, "volume": vol, "type": "normal"})
    return result

def count_touches(klines, vah, val):
    vah_t, val_t = 0, 0
    for k in klines:
        high, low = float(k[2]), float(k[3])
        if low <= vah <= high:
            vah_t += 1
        if low <= val <= high:
            val_t += 1
    return vah_t, val_t

def compute_consecutive_closes(klines, vah, val):
    closes = [float(k[4]) for k in klines]
    count_above = 0
    count_below = 0
    for c in reversed(closes):
        if c > vah:
            count_above += 1
        else:
            break
    for c in reversed(closes):
        if c < val:
            count_below += 1
        else:
            break
    return max(count_above, count_below)

def get_btc_price():
    try:
        return float(fetch("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT")["price"])
    except Exception:
        return None

def get_session():
    now = datetime.now(timezone.utc)
    hour = now.hour
    if 13 <= hour < 21:
        return "US"
    elif 7 <= hour < 16:
        return "EU"
    else:
        return "ASIA"

# ── DEVELOPING POC ─────────────────────────────────

def track_developing_poc(poc):
    """Compare current POC vs previous snapshot to detect migration."""
    state = {}
    try:
        if os.path.exists(STATE_FILE):
            state = json.load(open(STATE_FILE))
    except Exception:
        pass

    prev_poc = state.get("poc")
    prev_poc_5 = state.get("poc_5min_ago")
    prev_poc_15 = state.get("poc_15min_ago")
    now_ts = time.time()

    # Rotate snapshots
    if prev_poc and prev_poc != poc:
        if prev_poc_5 is None or (now_ts - state.get("poc_ts", 0) > 300):
            prev_poc_15 = prev_poc_5
            prev_poc_5 = prev_poc

    state["poc"] = poc
    state["poc_5min_ago"] = prev_poc_5
    state["poc_15min_ago"] = prev_poc_15
    state["poc_ts"] = now_ts

    try:
        json.dump(state, open(STATE_FILE, "w"))
    except Exception:
        pass

    # Determine direction
    if prev_poc_15 is not None:
        if poc > prev_poc_15:
            return "rising"
        elif poc < prev_poc_15:
            return "falling"
    return "flat"

# ── VERDICT ENGINE ─────────────────────────────────

def compute_verdict(price, poc, vah, val, consecutive_closes, perp, spot):
    """
    6-verdict system:
    BULLISH_ACCEPTANCE, BEARISH_ACCEPTANCE, UPPER_REJECTION,
    LOWER_REJECTION, BALANCED_ROTATION, NO_TRADE
    """
    buffer = max(NOISE_BUFFER, price * 0.0005)
    evidence = []
    warnings = []
    confirmation_needed = []
    positive_score = 0
    negative_score = 0

    # Determine price location
    if price > vah + buffer:
        location = "ABOVE_VAH"
    elif price < val - buffer:
        location = "BELOW_VAL"
    elif val <= price <= vah:
        location = "INSIDE_VALUE"
    else:
        location = "NEAR_BOUNDARY"

    # ── BULLISH ACCEPTANCE scoring ──
    if location == "ABOVE_VAH":
        positive_score += 20
        evidence.append("Price above VAH+${} buffer".format(int(buffer)))

        if consecutive_closes >= 3:
            positive_score += 20
            evidence.append("3+ hourly closes above VAH")
        elif consecutive_closes >= 1:
            positive_score += 10
            evidence.append("Price above VAH")

        close_count_above = consecutive_closes  # already above VAH
        if close_count_above >= 3:
            positive_score += 10
            evidence[-1] = "3 of last 5 closes above VAH"

        if perp["perp_delta_pct"] > 2:
            positive_score += 10
            evidence.append("Perpetual delta positive ({:.1f}%)".format(perp["perp_delta_pct"]))
        elif perp["perp_delta_pct"] < -2:
            negative_score += 15
            warnings.append("Perpetual delta negative despite price above VAH")

        if spot["spot_delta_pct"] > 2:
            positive_score += 15
            evidence.append("Spot delta positive ({:.1f}%)".format(spot["spot_delta_pct"]))
        elif spot["spot_delta_pct"] < -2:
            negative_score += 20
            warnings.append("Spot delta is negative — futures-led move, vulnerable")

        if 0 < perp["oi_change_pct"] < 3:
            positive_score += 5
            evidence.append("OI rising moderately ({:+.1f}%)".format(perp["oi_change_pct"]))
        elif perp["oi_change_pct"] > 5:
            negative_score += 10
            warnings.append("OI surging rapidly ({:+.1f}%) — leverage building fast".format(perp["oi_change_pct"]))

        if abs(perp["funding_rate"]) < 0.02:
            positive_score += 5
        else:
            negative_score += 10
            warnings.append("Funding elevated ({:.4f}%) — crowded trade risk".format(perp["funding_rate"]))

        # Price distance from VAH
        distance_pct = (price - vah) / vah * 100
        if distance_pct > 2:
            negative_score += 10
            warnings.append("Price extended {:.1f}% above VAH — late to enter".format(distance_pct))
            confirmation_needed.append("Pullback to VAH retest before entry")

    # ── BEARISH ACCEPTANCE scoring ──
    elif location == "BELOW_VAL":
        positive_score += 20
        evidence.append("Price below VAL–${} buffer".format(int(buffer)))

        if consecutive_closes >= 3:
            positive_score += 20
            evidence.append("3+ hourly closes below VAL")
        elif consecutive_closes >= 1:
            positive_score += 10
            evidence.append("Price below VAL")

        if perp["perp_delta_pct"] < -2:
            positive_score += 10
            evidence.append("Perpetual delta negative ({:.1f}%)".format(perp["perp_delta_pct"]))
        elif perp["perp_delta_pct"] > 2:
            negative_score += 15
            warnings.append("Perpetual delta positive despite price below VAL")

        if spot["spot_delta_pct"] < -2:
            positive_score += 15
            evidence.append("Spot delta negative ({:.1f}%)".format(spot["spot_delta_pct"]))
        elif spot["spot_delta_pct"] > 2:
            negative_score += 20
            warnings.append("Spot delta is positive — divergence, shorts vulnerable")

        if perp["oi_change_pct"] < -1:
            positive_score += 5
            evidence.append("OI declining — shorts unwinding")
        elif perp["oi_change_pct"] > 5:
            negative_score += 10
            warnings.append("OI rising during breakdown — short squeeze risk")

        distance_pct = (val - price) / val * 100
        if distance_pct > 2:
            negative_score += 10
            warnings.append("Price extended {:.1f}% below VAL — late to enter".format(distance_pct))

    # ── INSIDE VALUE — check for rejection patterns ──
    elif location in ("INSIDE_VALUE", "NEAR_BOUNDARY"):
        # Upper rejection: was above VAH, now back inside
        if consecutive_closes < 2 and price <= vah:
            evidence.append("Price returned inside value after excursion above VAH")
            positive_score += 25
            if perp["perp_delta_pct"] < 0:
                positive_score += 15
                evidence.append("Perpetual delta weakening — confirms rejection")
            if spot["spot_delta_pct"] < 0:
                positive_score += 15
                evidence.append("Spot delta negative — reinforces rejection")

            if positive_score >= 40:
                return {
                    "verdict": "UPPER_REJECTION",
                    "status": "DEVELOPING",
                    "confidence": min(85, positive_score),
                    "bias": "SHORT",
                    "price_location": location,
                    "summary": "Breakout above VAH failed. Price has returned inside value.",
                    "evidence": evidence,
                    "warnings": warnings,
                    "confirmation_needed": ["VAH reclaim attempt must fail"] + confirmation_needed,
                    "invalidation": "Two closes above VAH + buffer",
                    "target": "POC (${:,})".format(poc)
                }

        # Lower rejection: was below VAL, now back inside
        if consecutive_closes < 2 and price >= val:
            evidence.append("Price returned inside value after excursion below VAL")
            positive_score += 25
            if perp["perp_delta_pct"] > 0:
                positive_score += 15
                evidence.append("Perpetual delta strengthening — confirms rejection")
            if spot["spot_delta_pct"] > 0:
                positive_score += 15
                evidence.append("Spot delta positive — reinforces rejection")

            if positive_score >= 40:
                return {
                    "verdict": "LOWER_REJECTION",
                    "status": "DEVELOPING",
                    "confidence": min(85, positive_score),
                    "bias": "LONG",
                    "price_location": location,
                    "summary": "Breakdown below VAL failed. Price has returned inside value.",
                    "evidence": evidence,
                    "warnings": warnings,
                    "confirmation_needed": ["VAL reclaim attempt must fail"] + confirmation_needed,
                    "invalidation": "Two closes below VAL - buffer",
                    "target": "POC (${:,})".format(poc)
                }

        # Near POC — balanced/no trade likely
        poc_distance_pct = abs(price - poc) / poc * 100
        if poc_distance_pct < 0.5:
            evidence.append("Price near POC — choppy two-way auction")
            warnings.append("Near POC — poor entry location, wait for direction")

    # ── FINAL VERDICT ──

    # Bullish acceptance
    if location == "ABOVE_VAH" and (positive_score - negative_score) >= 50:
        return {
            "verdict": "BULLISH_ACCEPTANCE",
            "status": "DEVELOPING" if (positive_score - negative_score) < 70 else "CONFIRMED",
            "confidence": min(90, positive_score - negative_score),
            "bias": "LONG",
            "price_location": location,
            "summary": "Price is holding above value with evidence of acceptance.",
            "evidence": evidence,
            "warnings": warnings,
            "confirmation_needed": confirmation_needed or ["VAH must hold on pullback"],
            "invalidation": "Two hourly closes back inside value",
            "target": "Next major HVN or liquidity zone"
        }

    # Bearish acceptance
    if location == "BELOW_VAL" and (positive_score - negative_score) >= 50:
        return {
            "verdict": "BEARISH_ACCEPTANCE",
            "status": "DEVELOPING" if (positive_score - negative_score) < 70 else "CONFIRMED",
            "confidence": min(90, positive_score - negative_score),
            "bias": "SHORT",
            "price_location": location,
            "summary": "Price is holding below value with evidence of acceptance.",
            "evidence": evidence,
            "warnings": warnings,
            "confirmation_needed": confirmation_needed or ["VAL must hold as resistance"],
            "invalidation": "Two hourly closes back inside value",
            "target": "Next major LVN or liquidity zone"
        }

    # Balanced rotation
    if location in ("INSIDE_VALUE", "NEAR_BOUNDARY"):
        return {
            "verdict": "BALANCED_ROTATION",
            "status": "ONGOING",
            "confidence": 0,
            "bias": "NEUTRAL",
            "price_location": location,
            "summary": "Price is rotating inside the value area — no directional edge.",
            "evidence": evidence or ["Price inside value area (VAH–VAL)"],
            "warnings": warnings or ["Choppy conditions near POC — avoid initiating new trades"],
            "confirmation_needed": ["Wait for clear acceptance or rejection"],
            "invalidation": "N/A — no trade setup active",
            "target": "N/A — no trade setup active"
        }

    # Fallback — NO TRADE
    return {
        "verdict": "NO_TRADE",
        "status": "UNCERTAIN",
        "confidence": 0,
        "bias": "NEUTRAL",
        "price_location": location,
        "summary": "Evidence is insufficient or conflicting. No clear edge.",
        "evidence": evidence,
        "warnings": warnings or ["Conflicting signals", "Insufficient confirmation"],
        "confirmation_needed": ["Wait for clearer market structure"],
        "invalidation": "N/A",
        "target": "N/A"
    }

# ── TRADE SETUPS ──────────────────────────────────

def compute_trade_setups(price, poc, vah, val, verdict):
    """Generate trade setups only when verdict has a directional bias."""
    setups = []
    bias = verdict.get("bias", "NEUTRAL")

    # Don't generate setups for NO_TRADE or BALANCED_ROTATION
    if verdict.get("verdict") in ("NO_TRADE", "BALANCED_ROTATION"):
        return setups

    if bias in ("LONG", "NEUTRAL"):
        entry = val + 100
        setups.append({
            "direction": "LONG",
            "entry": round(entry),
            "t1": round(poc),
            "t2": round(vah),
            "stop_loss": round(val - BIN_STEP * 4),
            "invalidation": round(val - BIN_STEP * 2),
            "rr_t1": round(abs(poc - entry) / max(abs(entry - (val - BIN_STEP * 4)), 1), 1),
            "rr_t2": round(abs(vah - entry) / max(abs(entry - (val - BIN_STEP * 4)), 1), 1),
            "status": "ACTIVE" if bias == "LONG" else "PENDING"
        })

    if bias in ("SHORT", "NEUTRAL"):
        entry = vah - 100
        setups.append({
            "direction": "SHORT",
            "entry": round(entry),
            "t1": round(poc),
            "t2": round(val),
            "stop_loss": round(vah + BIN_STEP * 4),
            "invalidation": round(vah + BIN_STEP * 2),
            "rr_t1": round(abs(poc - entry) / max(abs(entry - (vah + BIN_STEP * 4)), 1), 1),
            "rr_t2": round(abs(val - entry) / max(abs(entry - (vah + BIN_STEP * 4)), 1), 1),
            "status": "ACTIVE" if bias == "SHORT" else "PENDING"
        })

    return setups

# ── MAIN ───────────────────────────────────────────

def main():
    print("Fetching Binance klines...")
    klines = fetch_klines()
    print(f"  {len(klines)} hourly candles")

    print("Fetching futures metrics (delta, OI, funding)...")
    try:
        perp = fetch_perp_metrics()
        print(f"  Perp delta: {perp['perp_delta_pct']:+.2f}% | OI chg: {perp['oi_change_pct']:+.2f}% | Funding: {perp['funding_rate']:.4f}%")
    except Exception as e:
        print(f"  ⚠ Perp metrics failed: {e}")
        perp = {"perp_delta_pct": 0, "perp_buy_vol": 0, "perp_sell_vol": 0,
                "oi_current": 0, "oi_change_pct": 0, "funding_rate": 0,
                "mark_price": 0, "perp_24h_vol": 0}

    print("Fetching spot metrics...")
    try:
        spot = fetch_spot_metrics()
        print(f"  Spot delta: {spot['spot_delta_pct']:+.2f}% | 24h vol: {spot['spot_24h_vol']:,} BTC")
    except Exception as e:
        print(f"  ⚠ Spot metrics failed: {e}")
        spot = {"spot_delta_pct": 0, "spot_24h_vol": 0, "spot_quote_vol": 0}

    print("Building volume profile...")
    bins = build_bins(klines)
    total_vol = sum(bins.values())
    poc, val, vah = compute_va(bins, total_vol)
    if val > vah:
        val, vah = vah, val
    print(f"  POC: ${poc:,} | VAH: ${vah:,} | VAL: ${val:,} | Bins: {len(bins)}")

    sorted_by_vol = sorted(bins.items(), key=lambda x: x[1], reverse=True)
    hvns = [{"price": b[0], "volume": round(b[1])} for b in sorted_by_vol[1:6]]
    lvns_all = sorted(bins.items(), key=lambda x: x[1])
    lvns = [{"price": b[0], "volume": round(b[1])} for b in lvns_all[:3] if b[1] > 0]

    btc_price = get_btc_price() or float(klines[-1][4])
    print(f"  BTC price: ${btc_price:,.0f}")

    vah_t, val_t = count_touches(klines, vah, val)
    consecutive = compute_consecutive_closes(klines, vah, val)
    session = get_session()
    developing_poc = track_developing_poc(poc)

    print("Computing verdict...")
    verdict = compute_verdict(btc_price, poc, vah, val, consecutive, perp, spot)
    print(f"  Verdict: {verdict['verdict']} | Confidence: {verdict['confidence']}% | Bias: {verdict['bias']}")

    setups = compute_trade_setups(btc_price, poc, vah, val, verdict)

    # HVN range
    hvn_prices = sorted([h["price"] for h in hvns])
    if len(hvn_prices) >= 2:
        hvn_range = f"{min(hvn_prices)}-{max(hvn_prices)}"
    else:
        hvn_range = str(hvn_prices[0]) if hvn_prices else "N/A"

    # Chart bins
    chart_bins = classify_bin_types(bins, poc, vah, val, hvns, lvns)

    # Build output
    now_iso = datetime.now(timezone.utc).isoformat()
    output = {
        "vp_card": {
            "btc_price": round(btc_price),
            "poc": poc,
            "vah": vah,
            "val": val,
            "consecutive_closes_outside_va": consecutive,
            "shape": "b" if verdict["bias"] == "SHORT" else ("P" if verdict["bias"] == "LONG" else "D"),
            "direction": verdict["bias"] if verdict["bias"] in ("LONG", "SHORT") else "DUAL",
            "strategy_bias": {"LONG": "FOLLOW", "SHORT": "FOLLOW", "NEUTRAL": "WAIT"}.get(verdict["bias"], "WAIT"),
            "trade_setups": setups,
            "session": session,
            "touch_count_vah": vah_t,
            "touch_count_val": val_t,
            "hvn_range": hvn_range,
            "size_recommendation": "NORMAL",
            "amt_lockout": False,
            "last_updated": now_iso,
            "generated_at": now_iso,
            # ── NEW FIELDS (V3.1) ──
            "verdict": verdict,
            "developing_poc": developing_poc,
            "perp_delta_pct": perp["perp_delta_pct"],
            "perp_buy_vol": perp["perp_buy_vol"],
            "perp_sell_vol": perp["perp_sell_vol"],
            "spot_delta_pct": spot["spot_delta_pct"],
            "oi_current": perp["oi_current"],
            "oi_change_pct": perp["oi_change_pct"],
            "funding_rate": perp["funding_rate"],
            "mark_price": perp["mark_price"],
            "noise_buffer": max(NOISE_BUFFER, round(btc_price * 0.0005)),
            "spot_24h_vol": spot["spot_24h_vol"],
            "perp_24h_vol": perp["perp_24h_vol"]
        },
        "chart_data": {
            "bins": chart_bins,
            "bin_size": BIN_STEP
        }
    }

    out_path = "/home/maswilee/projects/volume-profile-v3/data/vp_card.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n✓ Written to {out_path}")
    print(f"  Verdict: {verdict['verdict']} ({verdict['confidence']}% confidence)")
    print(f"  Perp Δ: {perp['perp_delta_pct']:+.2f}% | Spot Δ: {spot['spot_delta_pct']:+.2f}%")
    print(f"  OI Δ: {perp['oi_change_pct']:+.2f}% | Funding: {perp['funding_rate']:.4f}%")
    print(f"  Developing POC: {developing_poc}")

if __name__ == "__main__":
    main()
