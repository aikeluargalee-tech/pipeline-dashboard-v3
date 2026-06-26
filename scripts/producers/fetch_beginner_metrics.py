#!/usr/bin/env python3
"""
Fetch Beginner Metrics for BTC dashboard.
- Fear & Greed Index (api.alternative.me)
- Bitcoin Dominance (api.coingecko.com)
Writes to /tmp/btc_beginner_metrics.json
"""

import json
import os
import requests
from datetime import datetime, timezone

OUTPUT_PATH = "/tmp/btc_beginner_metrics.json"

def fetch_fng():
    """Fetch Crypto Fear & Greed Index from Alternative.me"""
    try:
        resp = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if "data" in data and len(data["data"]) > 0:
            val = int(data["data"][0]["value"])
            classification = data["data"][0]["value_classification"]
            return val, classification
    except Exception as e:
        print(f"[fetch_beginner_metrics] Error fetching FNG: {e}")
    return None, None

def fetch_btc_dominance():
    """Fetch Bitcoin Dominance from CoinGecko Global API"""
    try:
        resp = requests.get("https://api.coingecko.com/api/v3/global", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if "data" in data and "market_cap_percentage" in data["data"]:
            btc_d = data["data"]["market_cap_percentage"].get("btc")
            return round(float(btc_d), 2) if btc_d else None
    except Exception as e:
        print(f"[fetch_beginner_metrics] Error fetching BTC Dominance: {e}")
    return None

def main():
    print("[fetch_beginner_metrics] Fetching beginner metrics...")
    
    fng_value, fng_class = fetch_fng()
    btc_dominance = fetch_btc_dominance()
    
    payload = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "fear_and_greed_value": fng_value,
        "fear_and_greed_class": fng_class,
        "btc_dominance": btc_dominance
    }
    
    with open(OUTPUT_PATH, "w") as f:
        json.dump(payload, f, indent=2)
        
    print(f"✅ Saved to {OUTPUT_PATH}")
    print(json.dumps(payload, indent=2))

if __name__ == "__main__":
    main()
