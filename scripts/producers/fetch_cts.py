#!/usr/bin/env python3
"""
Fetch Corporate Treasury Stress (CTS) Monitor — Strategy (MSTR/STRK)
Produces data/corporate_treasury_stress.json.
"""
import json
import os
import sys
from datetime import datetime, timezone
import yfinance as yf

# ─── Configuration ───────────────────────────────────────────────
SITE = "/home/maswilee/projects/pipeline-dashboard-v3"
STATE_FILE = os.path.join(SITE, "data/corporate_treasury_stress.json")
LOG_FILE = os.path.join(SITE, "data/corporate_treasury_stress.log")

PAR_VALUE = 100.0  # STRK preferred share par value
BTC_HOLDINGS = 500_000  # estimated Strategy BTC holdings
ANNUAL_INTEREST_BURDEN = 500_000_000  # ~$500M annual debt service on ~10B debt

THRESHOLDS = {
    "WATCH": {
        "strc_below_par_pct": 5.0,   # 5% below par
        "coverage_years": 40.0,      # less than 40yr coverage
    },
    "ALERT": {
        "strc_below_par_pct": 10.0,  # 10% below par
        "coverage_years": 25.0,      # less than 25yr coverage
    },
    "FIRING": {
        "strc_below_par_pct": 15.0,  # 15% below par
        "coverage_years": 20.0,      # less than 20yr coverage
    },
}

def fetch_ticker_price(symbol):
    """Fetch ticker price from yfinance with multiple fallbacks."""
    ticker = yf.Ticker(symbol)
    
    # Try 1: history
    try:
        hist = ticker.history(period="1d")
        if not hist.empty:
            price = float(hist["Close"].iloc[-1])
            if price > 0:
                return price
    except Exception:
        pass
        
    # Try 2: fast_info
    try:
        price = float(ticker.fast_info.last_price)
        if price > 0:
            return price
    except Exception:
        pass

    # Try 3: info (fallback)
    try:
        price = float(ticker.info.get("regularMarketPrice") or ticker.info.get("currentPrice"))
        if price > 0:
            return price
    except Exception:
        pass

    raise ValueError(f"Could not fetch price for ticker {symbol}")

def read_btc_price():
    """Read BTC price from data/btc_price.json."""
    btc_path = os.path.join(SITE, "data/btc_price.json")
    if not os.path.exists(btc_path):
        raise FileNotFoundError(f"BTC price file not found at {btc_path}")
    with open(btc_path, "r") as f:
        data = json.load(f)
    if "price" not in data:
        raise KeyError("Field 'price' not found in btc_price.json")
    return float(data["price"])

def load_previous_state():
    """Load last known state to detect tier changes."""
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"tier": "UNKNOWN", "timestamp": None}

def save_state(result):
    """Persist current state atomically for next run."""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    tmp_file = STATE_FILE + ".tmp"
    with open(tmp_file, "w") as f:
        json.dump(result, f, indent=4)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_file, STATE_FILE)

def log_event(message):
    """Append to log file."""
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    with open(LOG_FILE, "a") as f:
        f.write(f"[{timestamp}] {message}\n")

def check_thresholds(strc_dist, coverage):
    """Compare metrics against WATCH/ALERT/FIRING thresholds."""
    breaches = []
    
    # Guard: missing critical data → UNKNOWN, not CLEAR
    if strc_dist is None and coverage is None:
        return "UNKNOWN", ["Error: STRK and BTC price data unavailable"]
    if strc_dist is None:
        return "UNKNOWN", ["Error: STRK price data unavailable"]
    if coverage is None:
        return "UNKNOWN", ["Error: BTC price data unavailable"]

    # Check all tiers, collect breaches and determine highest active tier
    max_tier = "CLEAR"
    tier_rank = {"CLEAR": 0, "WATCH": 1, "ALERT": 2, "FIRING": 3}

    # FIRING
    if strc_dist >= THRESHOLDS["FIRING"]["strc_below_par_pct"]:
        max_tier = "FIRING"
        breaches.append(f"STRC {strc_dist}% below par (threshold: {THRESHOLDS['FIRING']['strc_below_par_pct']}%)")
    if coverage < THRESHOLDS["FIRING"]["coverage_years"]:
        max_tier = "FIRING"
        breaches.append(f"Coverage {coverage}yr (threshold: <{THRESHOLDS['FIRING']['coverage_years']}yr)")

    # ALERT
    if strc_dist >= THRESHOLDS["ALERT"]["strc_below_par_pct"]:
        if tier_rank[max_tier] < tier_rank["ALERT"]:
            max_tier = "ALERT"
        breaches.append(f"STRC {strc_dist}% below par (threshold: {THRESHOLDS['ALERT']['strc_below_par_pct']}%)")
    if coverage < THRESHOLDS["ALERT"]["coverage_years"]:
        if tier_rank[max_tier] < tier_rank["ALERT"]:
            max_tier = "ALERT"
        breaches.append(f"Coverage {coverage}yr (threshold: <{THRESHOLDS['ALERT']['coverage_years']}yr)")

    # WATCH
    if strc_dist >= THRESHOLDS["WATCH"]["strc_below_par_pct"]:
        if tier_rank[max_tier] < tier_rank["WATCH"]:
            max_tier = "WATCH"
        breaches.append(f"STRC {strc_dist}% below par (threshold: {THRESHOLDS['WATCH']['strc_below_par_pct']}%)")
    if coverage < THRESHOLDS["WATCH"]["coverage_years"]:
        if tier_rank[max_tier] < tier_rank["WATCH"]:
            max_tier = "WATCH"
        breaches.append(f"Coverage {coverage}yr (threshold: <{THRESHOLDS['WATCH']['coverage_years']}yr)")

    # Deduplicate breaches while preserving order
    seen = set()
    deduped_breaches = []
    for b in breaches:
        if b not in seen:
            seen.add(b)
            deduped_breaches.append(b)

    return max_tier, deduped_breaches

def main():
    errors = {}
    
    # 1. Fetch MSTR and STRK prices
    mstr_price = None
    try:
        mstr_price = fetch_ticker_price("MSTR")
    except Exception as e:
        errors["mstr_error"] = str(e)
        print(f"Error fetching MSTR price: {e}", file=sys.stderr)

    strk_price = None
    try:
        strk_price = fetch_ticker_price("STRK")
    except Exception as e:
        errors["strc_error"] = str(e)  # maintain key as strc_error for frontend mapping
        print(f"Error fetching STRK price: {e}", file=sys.stderr)

    # 2. Read BTC price
    btc_price = None
    try:
        btc_price = read_btc_price()
    except Exception as e:
        errors["btc_error"] = str(e)
        print(f"Error reading BTC price: {e}", file=sys.stderr)

    # 3. Calculate metrics
    strc_par_distance_pct = None
    if strk_price is not None:
        strc_par_distance_pct = round(((PAR_VALUE - strk_price) / PAR_VALUE) * 100, 2)

    coverage_years = None
    holdings_value_b = None
    if btc_price is not None:
        holdings_value = BTC_HOLDINGS * btc_price
        holdings_value_b = round(holdings_value / 1e9, 2)
        coverage_years = round(holdings_value / ANNUAL_INTEREST_BURDEN, 1)

    mstr_btc_ratio = None
    if mstr_price is not None and btc_price is not None:
        mstr_btc_ratio = round(mstr_price / btc_price, 4)

    # 4. Check thresholds and load previous state
    tier, breaches = check_thresholds(strc_par_distance_pct, coverage_years)
    previous = load_previous_state()
    previous_tier = previous.get("tier", "UNKNOWN")

    # 5. Build output payload
    result = {
        "tier": tier,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "strc_price": strk_price,
        "mstr_price": mstr_price,
        "btc_price": btc_price,
        "strc_par_distance_pct": strc_par_distance_pct,
        "coverage_years": coverage_years,
        "holdings_value_b": holdings_value_b,
        "mstr_btc_ratio": mstr_btc_ratio,
        "breaches": breaches,
        "previous_tier": previous_tier,
        "errors": errors,
    }

    # Save state to file
    try:
        save_state(result)
    except Exception as e:
        print(f"Failed to write state file: {e}", file=sys.stderr)
        return 1

    # ─── Alert logging / stdout decision ────────────────────
    tier_rank = {"CLEAR": 0, "WATCH": 1, "ALERT": 2, "FIRING": 3, "UNKNOWN": -1}
    is_upgrade = tier_rank.get(tier, 0) > tier_rank.get(previous_tier, -1)
    is_first_run = previous_tier == "UNKNOWN"

    strc_s = f"${strk_price:.2f}" if strk_price is not None else "?"
    btc_s = f"${btc_price:,.0f}" if btc_price is not None else "?"
    cov_s = f"{coverage_years}yr" if coverage_years is not None else "?"

    if tier == "CLEAR":
        log_event(f"CLEAR — STRC {strc_s}, BTC {btc_s}, coverage {cov_s}")
    elif not is_upgrade and not is_first_run:
        log_event(f"{tier} (no change) — STRC {strc_s}, coverage {cov_s}")
    else:
        # Upgrade or first run
        log_event(f"⚠ {tier} UPGRADE from {previous_tier}: {'; '.join(breaches)}")
        
        # Build and print human-readable alert message to stdout
        par_s = f"{strc_par_distance_pct}%" if strc_par_distance_pct is not None else "?"
        mstr_s = f"${mstr_price:.2f}" if mstr_price is not None else "?"
        val_s = f"${holdings_value_b}B" if holdings_value_b is not None else "?"
        
        lines = [
            "⚠️ CORPORATE TREASURY STRESS — TIER CHANGE",
            "",
            f"New Tier: {tier} (was: {previous_tier})",
            f"STRC: {strc_s} ({par_s} below $100 par)",
            f"MSTR: {mstr_s}",
            f"BTC: {btc_s}",
            f"Coverage: {cov_s} years",
            f"Holdings: {val_s}",
        ]
        
        if breaches:
            lines.append("")
            lines.append("Breaches:")
            for b in breaches:
                lines.append(f"  • {b}")
                
        lines.append("")
        if tier == "WATCH":
            lines.append("→ Pipeline: synthesis unchanged. Monitor only.")
        elif tier == "ALERT":
            lines.append("→ Pipeline: cap BULLISH at CAUTIOUS BULL. Review EVENT 005.")
        elif tier == "FIRING":
            lines.append("→ Pipeline: cap at NEUTRAL. Consider Gate 0 review.")
            
        print("\n".join(lines))

    # Exit with proper code: if errors occurred in fetching critical data, return 1
    if errors:
        print(f"Warning: Script completed with errors: {errors}", file=sys.stderr)
        return 1

    return 0

if __name__ == "__main__":
    sys.exit(main())
