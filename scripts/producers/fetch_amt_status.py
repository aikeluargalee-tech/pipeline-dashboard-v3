#!/usr/bin/env python3
"""
Fetch AMT Status
Reads from /tmp/amt_feed.json and ~/projects/amt-feed/state/amt_signal_log.jsonl
and produces data/amt_status.json.
"""
import sys
import os
import json
from datetime import datetime, timezone

SITE = "/home/maswilee/projects/pipeline-dashboard-v3"
sys.path.insert(0, SITE)

OUTPUT_PATH = os.path.join(SITE, "data/amt_status.json")

def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default

def main():
    warmup_progress = "0/96"
    d1_layer = "offline"
    latest_signal = None
    last_whale_pivot = None

    # 1. Read /tmp/amt_feed.json for warmup stats
    amt_feed = read_json("/tmp/amt_feed.json")
    if amt_feed and "4layer" in amt_feed:
        layer_data = amt_feed["4layer"]
        warmup = layer_data.get("warmup", {})
        history_len = 0
        try:
            history_len = int(warmup.get("history_len", 0))
        except (ValueError, TypeError):
            pass
        warmup_progress = f"{min(history_len, 96)}/96"

        if warmup.get("1D") == "active" or history_len >= 96:
            d1_layer = "online"
        else:
            d1_layer = "offline"

    # 2. Read amt_signal_log.jsonl for whale pivot and signals
    log_path = os.path.expanduser("~/projects/amt-feed/state/amt_signal_log.jsonl")
    if os.path.exists(log_path):
        try:
            with open(log_path, "r") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        entry = json.loads(line)
                        pivot_sig = entry.get("whale_pivot_signal")
                        if pivot_sig:
                            last_whale_pivot = {
                                "direction": pivot_sig,
                                "price": entry.get("price")
                            }
                            latest_signal = {
                                "type": "Whale Pivot",
                                "timestamp": entry.get("ts"),
                                "summary": f"Whale Pivot {pivot_sig} at ${entry.get('price'):,.0f}"
                            }
                    except Exception:
                        pass
        except Exception as e:
            print(f"[amt_status] Error reading signal log: {e}")

    # Build payload
    payload = {
        "warmup_progress": warmup_progress,
        "1d_layer": d1_layer,
        "latest_signal": latest_signal,
        "last_whale_pivot": last_whale_pivot,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    }

    # Ensure output dir exists
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"[amt_status] Progress {warmup_progress}, 1D {d1_layer}, Signal {latest_signal}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
