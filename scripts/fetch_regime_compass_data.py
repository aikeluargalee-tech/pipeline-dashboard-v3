#!/usr/bin/env python3
"""
Regime Compass — Missing Data Collector
Fetches the 5 offline inputs and outputs a JSON file for the regime-compass page.

Sources (all free, no API keys):
  1. BTC/ETH relative perf — Binance API
  2. BTC/Gold relative perf — yfinance (GC=F)
  3. HYG vs LQD credit spreads — yfinance
  4. BTC ETF net flows — existing /tmp/btc_etf_flow.json
  5. BTC Dominance — CoinGecko free API

Output: packet/regime-compass-data.json (alongside data.json)
"""

import json
import os
import time
import urllib.request
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)  # go up from scripts/ to project root
OUTPUT_PATH = os.path.join(PROJECT_DIR, "packet", "regime-compass-data.json")
ETF_FLOW_PATH = "/tmp/btc_etf_flow.json"


def log(msg):
    print(f"[regime-compass] {msg}", flush=True)


def http_get(url, timeout=15):
    """Simple HTTP GET returning parsed JSON or text."""
    req = urllib.request.Request(url, headers={"User-Agent": "BTC-Pipeline/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read().decode("utf-8")
            return json.loads(data)
    except json.JSONDecodeError:
        return None
    except Exception as e:
        log(f"  HTTP error: {e}")
        return None


# ---------------------------------------------------------------------------
# 1. BTC/ETH Relative Performance (Binance — free, no key)
# ---------------------------------------------------------------------------

def fetch_btc_eth():
    """Return BTC and ETH prices and 7-day relative performance."""
    try:
        btc = http_get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT")
        eth = http_get("https://api.binance.com/api/v3/ticker/price?symbol=ETHUSDT")
        if not btc or not eth:
            return None
        btc_p = float(btc["price"])
        eth_p = float(eth["price"])
        ratio = btc_p / eth_p  # BTC per ETH — higher = BTC outperforming

        # Get 7-day change for both (use 24h stats as proxy for recent perf)
        btc_24h = http_get("https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT")
        eth_24h = http_get("https://api.binance.com/api/v3/ticker/24hr?symbol=ETHUSDT")
        btc_chg = float(btc_24h["priceChangePercent"]) if btc_24h else 0
        eth_chg = float(eth_24h["priceChangePercent"]) if eth_24h else 0
        rel_perf = btc_chg - eth_chg  # positive = BTC outperforming ETH

        log(f"  BTC/ETH: ratio={ratio:.1f}, rel_24h={rel_perf:+.1f}%")
        return {
            "btc_price": btc_p,
            "eth_price": eth_p,
            "btc_eth_ratio": round(ratio, 2),
            "btc_24h_pct": round(btc_chg, 2),
            "eth_24h_pct": round(eth_chg, 2),
            "rel_perf_24h_pct": round(rel_perf, 2),
            "label": f"BTC {btc_chg:+.1f}% vs ETH {eth_chg:+.1f}%",
        }
    except Exception as e:
        log(f"  BTC/ETH error: {e}")
        return None


# ---------------------------------------------------------------------------
# 2. BTC/Gold & 3. HYG/LQD — via yfinance
# ---------------------------------------------------------------------------

def fetch_yahoo():
    """Fetch gold price, HYG, LQD from Yahoo Finance."""
    try:
        import yfinance as yf
    except ImportError:
        log("  yfinance not installed — skipping HYG/LQD/Gold")
        return {}

    result = {}
    symbols = {"GC=F": "gold", "HYG": "hyg", "LQD": "lqd"}

    for sym, name in symbols.items():
        try:
            t = yf.Ticker(sym)
            # Try fast_info first, fall back to history
            price = None
            try:
                price = t.fast_info.get("lastPrice") or t.fast_info.get("regularMarketPrice")
            except Exception:
                pass
            if price is None:
                hist = t.history(period="5d")
                if not hist.empty:
                    price = hist["Close"].iloc[-1]
            if price:
                result[name] = round(float(price), 2)
                log(f"  {sym}: ${result[name]:.2f}")
        except Exception as e:
            log(f"  {sym} error: {e}")

    return result


def compute_btc_gold(btc_price, yahoo_data):
    """Compute BTC/Gold ratio and relative performance."""
    gold = yahoo_data.get("gold")
    if not gold or not btc_price:
        return None
    ratio = btc_price / gold
    log(f"  BTC/Gold ratio: {ratio:.2f} (1 BTC = {ratio:.1f} oz gold)")
    return {
        "btc_price": btc_price,
        "gold_price": gold,
        "btc_gold_ratio": round(ratio, 2),
        "label": f"1 BTC = {ratio:.1f} oz gold",
    }


def compute_credit_spread(yahoo_data):
    """Compute HYG/LQD relative performance as credit spread proxy."""
    hyg = yahoo_data.get("hyg")
    lqd = yahoo_data.get("lqd")
    if not hyg or not lqd:
        return None
    # Higher HYG/LQD ratio = risk-on (junk outperforming IG)
    ratio = hyg / lqd
    spread_bps = round((hyg - lqd) * 100, 0)  # price difference in "bps" style
    label = "Risk-On (HYG > LQD)" if ratio > 1 else "Risk-Off (LQD > HYG)"
    log(f"  HYG/LQD: ratio={ratio:.4f}, spread={spread_bps}bps, {label}")
    return {
        "hyg_price": hyg,
        "lqd_price": lqd,
        "hyg_lqd_ratio": round(ratio, 5),
        "spread_display": f"{spread_bps:.0f} bps",
        "label": label,
    }


# ---------------------------------------------------------------------------
# 4. ETF Net Flows — from existing collector
# ---------------------------------------------------------------------------

def fetch_etf_flows():
    """Read ETF flow data from /tmp/btc_etf_flow.json if recent."""
    if not os.path.exists(ETF_FLOW_PATH):
        log("  ETF flows: no data file found")
        return None
    try:
        mtime = os.path.getmtime(ETF_FLOW_PATH)
        age_h = (time.time() - mtime) / 3600
        with open(ETF_FLOW_PATH) as f:
            data = json.load(f)
        if "error" in data:
            log(f"  ETF flows: error in data — {data.get('error')}")
            return None
        latest = data.get("latest", {})
        weekly = data.get("weekly_net", 0)
        direction = data.get("direction", "flat")
        label = data.get("signal_display", "N/A")
        date = latest.get("date", "?")
        log(f"  ETF flows: {date} | weekly=${weekly:+.1f}M | {direction} ({age_h:.1f}h old)")
        return {
            "latest_date": date,
            "latest_daily_m": latest.get("total", 0),
            "weekly_net_m": weekly,
            "direction": direction,
            "label": label,
            "age_hours": round(age_h, 1),
        }
    except Exception as e:
        log(f"  ETF flows error: {e}")
        return None


# ---------------------------------------------------------------------------
# 5. BTC Dominance — CoinGecko free API
# ---------------------------------------------------------------------------

def fetch_btc_dominance():
    """Fetch BTC dominance percentage from CoinGecko."""
    try:
        data = http_get("https://api.coingecko.com/api/v3/global")
        if not data:
            return None
        dom = data["data"]["market_cap_percentage"]["btc"]
        log(f"  BTC Dominance: {dom:.1f}%")
        return {
            "dominance_pct": round(dom, 1),
            "label": f"BTC {dom:.1f}% of total crypto market cap",
        }
    except Exception as e:
        log(f"  BTC Dominance error: {e}")
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    log("Collecting missing inputs for Regime Compass...")

    output = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "btc_eth": None,
        "btc_gold": None,
        "credit_spread": None,
        "etf_flows": None,
        "btc_dominance": None,
        "available": 0,
        "total": 5,
    }

    # Fetch BTC price once for btc_gold calc
    btc_data = http_get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT")
    btc_price = float(btc_data["price"]) if btc_data else None

    # 1. BTC/ETH
    output["btc_eth"] = fetch_btc_eth()
    if output["btc_eth"]:
        output["available"] += 1

    # 2 & 3. Yahoo Finance (gold, HYG, LQD)
    yahoo = fetch_yahoo()
    if yahoo:
        output["btc_gold"] = compute_btc_gold(btc_price, yahoo) if btc_price else None
        if output["btc_gold"]:
            output["available"] += 1
        output["credit_spread"] = compute_credit_spread(yahoo)
        if output["credit_spread"]:
            output["available"] += 1

    # 4. ETF Flows
    output["etf_flows"] = fetch_etf_flows()
    if output["etf_flows"]:
        output["available"] += 1

    # 5. BTC Dominance
    output["btc_dominance"] = fetch_btc_dominance()
    if output["btc_dominance"]:
        output["available"] += 1

    # Write output
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    log(f"✅ Written {output['available']}/{output['total']} inputs to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
