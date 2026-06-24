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
    current_price = None

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
    latest_entry = None
    if os.path.exists(log_path):
        try:
            with open(log_path, "r") as f:
                lines = f.readlines()
                if lines:
                    # Get current price from latest entry
                    latest_line = lines[-1].strip()
                    if latest_line:
                        try:
                            latest_entry = json.loads(latest_line)
                            current_price = latest_entry.get("price")
                        except Exception:
                            pass

                # Scan for whale pivots (lines read in order, last pivot wins)
                for line in lines:
                    if not line.strip():
                        continue
                    try:
                        entry = json.loads(line)
                        pivot_sig = entry.get("whale_pivot_signal")
                        if pivot_sig:
                            pivot_ts = entry.get("ts")
                            pivot_price = entry.get("price")
                            last_whale_pivot = {
                                "direction": pivot_sig,
                                "price": pivot_price,
                                "timestamp": pivot_ts,
                                "conviction": entry.get("whale_pivot_conviction"),
                                "checklist": entry.get("checklist", {}),
                                "balance_state": entry.get("balance_state")
                            }
                            latest_signal = {
                                "type": "Whale Pivot",
                                "timestamp": pivot_ts,
                                "summary": f"Whale Pivot {pivot_sig} at ${pivot_price:,.0f}"
                            }
                    except Exception:
                        pass
        except Exception as e:
            print(f"[amt_status] Error reading signal log: {e}")

    # 3. Enrich whale pivot with staleness/validity metadata
    if last_whale_pivot and current_price:
        now = datetime.now(timezone.utc)
        try:
            pivot_ts_str = last_whale_pivot.get("timestamp", "")
            if pivot_ts_str:
                pivot_dt = datetime.fromisoformat(pivot_ts_str.replace("Z", "+00:00"))
                age_seconds = (now - pivot_dt).total_seconds()
                age_minutes = age_seconds / 60
                age_hours = age_minutes / 60

                if age_minutes < 1:
                    age_display = "just now"
                elif age_minutes < 60:
                    age_display = f"{int(age_minutes)}m ago"
                elif age_hours < 24:
                    age_display = f"{int(age_hours)}h {int(age_minutes % 60)}m ago"
                else:
                    days = int(age_hours / 24)
                    age_display = f"{days}d ago"

                pivot_price = last_whale_pivot["price"]
                direction = last_whale_pivot["direction"]
                checklist = last_whale_pivot.get("checklist", {})

                # Distance from pivot to current price
                distance_pct = ((current_price - pivot_price) / pivot_price) * 100
                distance_abs = current_price - pivot_price
                distance_display = f"{'+' if distance_abs >= 0 else ''}{distance_pct:.1f}% (${abs(distance_abs):,.0f})"

                # Signal validity
                if direction == "LONG" and current_price < pivot_price:
                    validity = "invalidated"
                    validity_reason = f"Price dropped below pivot ({pivot_price:,.0f})"
                elif direction == "SHORT" and current_price > pivot_price:
                    validity = "invalidated"
                    validity_reason = f"Price rose above pivot ({pivot_price:,.0f})"
                elif age_minutes > 120:
                    validity = "stale"
                    validity_reason = f"No follow-through after {int(age_hours)}h — still ranging"
                elif age_minutes > 30:
                    validity = "monitoring"
                    validity_reason = f"Pivot triggered {age_display}, awaiting confirmation"
                else:
                    validity = "fresh"
                    validity_reason = "Pivot just fired — watching for follow-through"

                last_whale_pivot["age"] = age_display
                last_whale_pivot["distance"] = distance_display
                last_whale_pivot["distance_pct"] = round(distance_pct, 2)
                last_whale_pivot["current_price"] = current_price
                last_whale_pivot["validity"] = validity
                last_whale_pivot["validity_reason"] = validity_reason

                # Build checklist details (like 4-layer detail bullets)
                checklist_labels = {
                    "at_key_level": "At Key Level",
                    "absorption_detected": "Absorption",
                    "aggression_opposing": "Aggression Opposing",
                    "delta_confirms": "Delta Confirms"
                }
                last_whale_pivot["checklist_details"] = [
                    {"label": checklist_labels.get(k, k), "passed": v}
                    for k, v in checklist.items()
                ]
                last_whale_pivot["checklist_score"] = f"{sum(1 for v in checklist.values() if v)}/{len(checklist)}"

        except Exception as e:
            print(f"[amt_status] Error enriching pivot: {e}")

    # Build payload
    payload = {
        "warmup_progress": warmup_progress,
        "1d_layer": d1_layer,
        "current_price": current_price,
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
