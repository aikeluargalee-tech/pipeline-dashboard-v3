#!/usr/bin/env python3
"""
Volume Profile V3.0 Producer
Reads AMT footprint data → computes POC/VAH/VAL/shape → writes vp_card.json
Output: /tmp/btc_vp_card.json (collected by collect.py into dashboard data/)
"""
import json
import os
import tempfile
from datetime import datetime, timezone

AMT_FEED = "/tmp/amt_feed.json"
VP_OUTPUT = "/tmp/btc_vp_card.json"
VA_PCT = 0.70  # 70% of volume = value area


def load_feed():
    if not os.path.exists(AMT_FEED):
        return None
    with open(AMT_FEED) as f:
        return json.load(f)


def compute_vp(feed):
    """Extract footprint levels and compute VP metrics."""
    fp = feed.get("footprint", {})
    levels = fp.get("levels", [])
    tick_size = fp.get("tick_size", 8)

    if not levels or len(levels) < 5:
        return None  # insufficient data

    # Sort by price descending
    levels.sort(key=lambda x: x["price"], reverse=True)

    # Compute total volume per level
    for lvl in levels:
        lvl["total_vol"] = lvl["buy"] + lvl["sell"]

    total_volume = sum(l["total_vol"] for l in levels)
    if total_volume == 0:
        return None

    # 1. POC — level with highest total volume
    poc_level = max(levels, key=lambda x: x["total_vol"])
    poc = poc_level["price"]

    # 2. Value Area (70%) — accumulate from POC outward
    va_volume = 0
    va_levels = []
    lvl_dict = {l["price"]: l for l in levels}

    # Walk outward from POC
    poc_idx = next(i for i, l in enumerate(levels) if l["price"] == poc)
    left = poc_idx - 1
    right = poc_idx + 1

    va_volume += poc_level["total_vol"]
    va_levels.append(poc_level)

    while va_volume < total_volume * VA_PCT and (left >= 0 or right < len(levels)):
        # Pick the side with higher volume
        left_vol = levels[left]["total_vol"] if left >= 0 else 0
        right_vol = levels[right]["total_vol"] if right < len(levels) else 0

        if left_vol >= right_vol and left >= 0:
            va_volume += left_vol
            va_levels.append(levels[left])
            left -= 1
        elif right < len(levels):
            va_volume += right_vol
            va_levels.append(levels[right])
            right += 1
        else:
            break

    vah = max(l["price"] for l in va_levels)
    val = min(l["price"] for l in va_levels)

    # 3. Classify bins for chart
    bins = build_chart_bins(levels, poc, vah, val, tick_size)

    # 4. Touch counts (from feed metadata or default)
    touch_val = feed.get("footprint", {}).get("touch_val", 0)
    touch_vah = feed.get("footprint", {}).get("touch_vah", 0)

    # 5. Shape detection
    btc_price = feed.get("btc_spot", levels[0]["price"])
    shape, strategy, state = detect_shape(bins, btc_price, vah, val, poc)

    # 6. AMT layer check
    regime = feed.get("meta", {}).get("regime", "UNKNOWN")
    adx = feed.get("meta", {}).get("adx", 0)
    amt_verdict = feed.get("meta", {}).get("verdict", "NO_TRADE")
    amt_lockout = amt_verdict == "NO_TRADE" or regime == "BEARISH"

    # 7. Trade setup
    entry = val - tick_size * 2 if shape in ("D", "b") else vah + tick_size * 2
    t1 = poc
    t2 = vah if strategy == "FADE" else vah + (vah - val)
    stop = val - (vah - val) * 0.3 if strategy == "FADE" else val

    rr_t1 = round(abs((t1 - entry) / (entry - stop)), 2) if entry != stop else 0
    rr_t2 = round(abs((t2 - entry) / (entry - stop)), 2) if entry != stop else 0

    size = "SKIP" if amt_lockout else "STANDARD"

    return {
        "vp_card": {
            "shape": shape,
            "poc": int(poc),
            "vah": int(vah),
            "val": int(val),
            "hvn_range": f"{int(val + (poc - val) * 0.4)}-{int(vah - (vah - poc) * 0.4)}",
            "touch_count_val": touch_val,
            "touch_count_vah": touch_vah,
            "probability_tier": "HIGH" if touch_val >= 2 else "BASELINE",
            "acceptance_rejection_state": state,
            "rejection_direction": None,
            "consecutive_closes_outside_va": 0,
            "confirmation_status": "PENDING",
            "active_pattern": "POC_MAGNET",
            "strategy_bias": strategy,
            "amt_lockout": amt_lockout,
            "amt_verdict": amt_verdict,
            "adx": adx,
            "entry_level": int(entry),
            "t1": int(t1),
            "t2": int(t2),
            "stop_loss": int(stop),
            "invalidation": int(vah + (vah - val) * 0.1),
            "rr_t1": rr_t1,
            "rr_t2": rr_t2,
            "size_recommendation": size,
            "btc_price": int(btc_price),
            "session": "LONDON",  # TODO: detect from time
            "last_updated": datetime.now(timezone.utc).isoformat()
        },
        "chart_data": {
            "bin_size": int(tick_size),
            "max_volume": max(b["volume"] for b in bins) if bins else 1,
            "bins": bins
        }
    }


def build_chart_bins(levels, poc, vah, val, tick_size):
    """Classify each level for chart rendering."""
    bins = []
    for lvl in levels:
        price = lvl["price"]
        total = lvl["total_vol"]

        # Classify type
        if abs(price - poc) <= tick_size:
            btype = "poc"
        elif abs(price - vah) <= tick_size * 2:
            btype = "vah"
        elif abs(price - val) <= tick_size * 2:
            btype = "val"
        elif val < price < vah and total > 0.3 * max(l["total_vol"] for l in levels):
            btype = "hvn"
        elif total < 0.1 * max(l["total_vol"] for l in levels):
            btype = "lvn"
        else:
            btype = "normal"

        bins.append({
            "price": int(price),
            "volume": round(total, 2),
            "type": btype
        })
    return bins


def detect_shape(bins, price, vah, val, poc):
    """Determine shape, strategy bias, and acceptance state."""
    top_vol = sum(b["volume"] for b in bins if b["price"] > poc)
    bot_vol = sum(b["volume"] for b in bins if b["price"] < poc)

    ratio = top_vol / bot_vol if bot_vol > 0 else 999

    if price > vah:
        return "P", "FOLLOW", "REJECTION_UP"
    elif price < val:
        return "b", "FOLLOW", "REJECTION_DOWN"
    elif ratio > 1.5:
        return "P", "FADE", "ACCEPTANCE"
    elif ratio < 0.67:
        return "b", "FADE", "ACCEPTANCE"
    else:
        return "D", "FADE", "ACCEPTANCE"


def atomic_write(path, data):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        os.unlink(tmp)
        raise


def main():
    feed = load_feed()
    if not feed:
        print("[vp_producer] No AMT feed data — skipping")
        return

    result = compute_vp(feed)
    if not result:
        print("[vp_producer] Insufficient footprint data — skipping")
        return

    atomic_write(VP_OUTPUT, result)
    s = result["vp_card"]
    print(f"[vp_producer] Shape={s['shape']} POC=${s['poc']} "
          f"VAH=${s['vah']} VAL=${s['val']} "
          f"Bias={s['strategy_bias']} Lockout={s['amt_lockout']}")


if __name__ == "__main__":
    main()
