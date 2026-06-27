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


def load_state():
    if os.path.exists(VP_STATE):
        try:
            with open(VP_STATE) as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            pass
    return {"consecutive_closes_outside_va": 0, "last_price": None,
            "last_state": None, "last_vah": None, "last_val": None}


def save_state(s):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(VP_STATE), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(s, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, VP_STATE)
    except Exception:
        os.unlink(tmp)
        raise


def update_consecutive_closes(vp_state, price, vah, val, current_state):
    """Track consecutive closes outside Value Area.
    Increments on same-state rejection; resets to 0 on acceptance;
    starts at 1 on first rejection outside VA."""
    prev = vp_state.get("consecutive_closes_outside_va", 0)

    # Same state as before → increment
    if current_state == vp_state.get("last_state"):
        if current_state in ("REJECTION_UP", "REJECTION_DOWN"):
            return prev + 1
        return prev
    # State changed → could be same direction or reset
    if current_state == "ACCEPTANCE":
        return 0  # reset when back inside
    if current_state in ("REJECTION_UP", "REJECTION_DOWN") and \
       current_state != vp_state.get("last_state"):
        return 1  # first close outside
    return prev


def compute_trade_setup(shape, btc_price, vah, val, poc, tick_size, amt_lockout):
    """GetClaw V3.0 directional trade setup.
    Returns (direction, trade_setups[], primary_setup_dict).
    D-shape: bidirectional via POC midpoint
    P-shape: LONG only — buy pullback to VA
    b-shape: SHORT only — sell rally to VA
    B-shape: DUAL — LONG at lower POC, SHORT at upper POC (WAIT bias)
    """
    range_va = vah - val
    mid = (vah + val) / 2

    def rr_long(t, entry, stop):
        return round(abs((t - entry) / (entry - stop)), 2) if entry != stop else 0

    def rr_short(t, entry, stop):
        return round(abs((entry - t) / (stop - entry)), 2) if stop != entry else 0

    if shape == "D":
        if btc_price <= mid:
            direction = "LONG"
            entry = val - tick_size * 2
            t1, t2 = poc, vah
            stop = val - range_va * 0.15
            invalidation = val - range_va * 0.25
        else:
            direction = "SHORT"
            entry = vah + tick_size * 2
            t1, t2 = poc, val
            stop = vah + range_va * 0.15
            invalidation = vah + range_va * 0.25

        setup = {
            "direction": direction,
            "entry": int(entry),
            "t1": int(t1),
            "t2": int(t2),
            "stop_loss": int(stop),
            "invalidation": int(invalidation),
        }
        if direction == "LONG":
            setup["rr_t1"] = rr_long(t1, entry, stop)
            setup["rr_t2"] = rr_long(t2, entry, stop)
        else:
            setup["rr_t1"] = rr_short(t1, entry, stop)
            setup["rr_t2"] = rr_short(t2, entry, stop)
        return direction, [setup], setup

    elif shape == "P":
        direction = "LONG"
        entry = val - tick_size * 2
        t1 = poc
        t2 = vah + range_va  # extension target in trend
        stop = val - range_va * 0.15
        invalidation = val - range_va * 0.25

        setup = {
            "direction": direction,
            "entry": int(entry),
            "t1": int(t1),
            "t2": int(t2),
            "stop_loss": int(stop),
            "invalidation": int(invalidation),
            "rr_t1": rr_long(t1, entry, stop),
            "rr_t2": rr_long(t2, entry, stop),
        }
        return direction, [setup], setup

    elif shape == "b":
        direction = "SHORT"
        entry = vah + tick_size * 2
        t1 = poc
        t2 = val
        stop = vah + range_va * 0.20
        invalidation = vah + range_va * 0.40

        setup = {
            "direction": direction,
            "entry": int(entry),
            "t1": int(t1),
            "t2": int(t2),
            "stop_loss": int(stop),
            "invalidation": int(invalidation),
            "rr_t1": rr_short(t1, entry, stop),
            "rr_t2": rr_short(t2, entry, stop),
        }
        return direction, [setup], setup

    elif shape == "B":
        direction = "DUAL"
        # Placeholder dual POC — upstream footprint needs to detect two POC clusters
        poc_lower = val + range_va * 0.25
        poc_upper = vah - range_va * 0.25

        long_setup = {
            "direction": "LONG",
            "poc_ref": "lower",
            "entry": int(poc_lower - tick_size * 2),
            "t1": int(poc_upper),
            "t2": int(vah),
            "stop_loss": int(val - range_va * 0.10),
            "invalidation": int(val - range_va * 0.25),
            "status": "PENDING",
        }
        long_setup["rr_t1"] = rr_long(long_setup["t1"], long_setup["entry"], long_setup["stop_loss"])
        long_setup["rr_t2"] = rr_long(long_setup["t2"], long_setup["entry"], long_setup["stop_loss"])

        short_setup = {
            "direction": "SHORT",
            "poc_ref": "upper",
            "entry": int(poc_upper + tick_size * 2),
            "t1": int(poc_lower),
            "t2": int(val),
            "stop_loss": int(vah + range_va * 0.10),
            "invalidation": int(vah + range_va * 0.25),
            "status": "PENDING",
        }
        short_setup["rr_t1"] = rr_short(short_setup["t1"], short_setup["entry"], short_setup["stop_loss"])
        short_setup["rr_t2"] = rr_short(short_setup["t2"], short_setup["entry"], short_setup["stop_loss"])

        trade_setups = [long_setup, short_setup]
        primary = long_setup  # default LONG as primary
        return direction, trade_setups, primary

    # Fallback — should never reach here
    return "LONG", [], {}


AMT_FEED = "/tmp/amt_feed.json"
VP_OUTPUT = "/tmp/btc_vp_card.json"
VP_STATE = "/tmp/btc_vp_state.json"  # persists consecutive_closes across runs
VA_PCT = 0.70  # 70% of volume = value area


def load_feed():
    if not os.path.exists(AMT_FEED):
        return None
    try:
        with open(AMT_FEED) as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return None


def compute_vp(feed):
    """Extract footprint levels and compute VP metrics."""
    fp = feed.get("footprint") or {}
    levels = fp.get("levels") or []
    tick_size = fp.get("tick_size", 8)

    if not levels or len(levels) < 5:
        return None  # insufficient data

    # Sort by price descending
    levels.sort(key=lambda x: x["price"], reverse=True)

    # Compute total volume per level
    for lvl in levels:
        lvl["total_vol"] = (lvl.get("buy") or 0) + (lvl.get("sell") or 0)

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
    touch_val = (feed.get("footprint") or {}).get("touch_val", 0)
    touch_vah = (feed.get("footprint") or {}).get("touch_vah", 0)

    # 5. Shape detection
    btc_price = feed.get("btc_spot") or levels[0]["price"]
    shape, strategy, state = detect_shape(bins, btc_price, vah, val, poc)

    # 5a. State persistence — track consecutive closes across runs
    vp_state = load_state()
    consecutive = update_consecutive_closes(vp_state, btc_price, vah, val, state)
    vp_state["consecutive_closes_outside_va"] = consecutive
    vp_state["last_price"] = btc_price
    vp_state["last_state"] = state
    vp_state["last_vah"] = vah
    vp_state["last_val"] = val
    save_state(vp_state)

    # Re-detect shape with corrected consecutive count
    if consecutive >= 2 and btc_price > vah:
        shape, strategy = "P", "FOLLOW"
    elif consecutive >= 2 and btc_price < val:
        shape, strategy = "b", "FOLLOW"

    # 6. AMT layer check
    regime = feed.get("meta", {}).get("regime", "UNKNOWN")
    adx = feed.get("meta", {}).get("adx", 0)
    amt_verdict = feed.get("meta", {}).get("verdict", "NO_TRADE")
    amt_lockout = amt_verdict == "NO_TRADE" or regime == "BEARISH"

    # 7. Trade setup — GetClaw V3.0 bidirectional logic
    direction, trade_setups, primary = compute_trade_setup(
        shape, btc_price, vah, val, poc, tick_size, amt_lockout
    )

    # Override strategy for B-shape
    display_strategy = strategy
    if shape == "B":
        display_strategy = "WAIT"

    size = "SKIP" if amt_lockout else "STANDARD"

    return {
        "vp_card": {
            "shape": shape,
            "direction": direction,
            "poc": int(poc),
            "vah": int(vah),
            "val": int(val),
            "hvn_range": f"{int(val + (poc - val) * 0.4)}-{int(vah - (vah - poc) * 0.4)}",
            "touch_count_val": touch_val,
            "touch_count_vah": touch_vah,
            "probability_tier": "HIGH" if touch_val >= 2 else "BASELINE",
            "acceptance_rejection_state": state,
            "rejection_direction": None,
            "consecutive_closes_outside_va": consecutive,
            "confirmation_status": "PENDING",
            "active_pattern": "POC_MAGNET",
            "strategy_bias": display_strategy,
            "amt_lockout": amt_lockout,
            "amt_verdict": amt_verdict,
            "adx": adx,
            # Flat fields — backward compat, mirror primary setup
            "entry_level": primary.get("entry"),
            "t1": primary.get("t1"),
            "t2": primary.get("t2"),
            "stop_loss": primary.get("stop_loss"),
            "invalidation": primary.get("invalidation"),
            "rr_t1": primary.get("rr_t1"),
            "rr_t2": primary.get("rr_t2"),
            "size_recommendation": size,
            # Canonical trade setups array
            "trade_setups": trade_setups,
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

    ratio = top_vol / bot_vol if bot_vol > 0 else (1 if top_vol == 0 else 999)

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
    print(f"[vp_producer] Shape={s['shape']} Dir={s['direction']} POC=${s['poc']} "
          f"VAH=${s['vah']} VAL=${s['val']} "
          f"Bias={s['strategy_bias']} Lockout={s['amt_lockout']}")


if __name__ == "__main__":
    main()
