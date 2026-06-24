#!/usr/bin/env python3
"""
Fetch TRP Status
Reads from ~/TRP/state/ and ~/TRP/intents/ and produces data/trp_status.json.
"""
import sys
import os
import json
from datetime import datetime, timezone

SITE = "/home/maswilee/projects/pipeline-dashboard-v3"
sys.path.insert(0, SITE)

OUTPUT_PATH = os.path.join(SITE, "data/trp_status.json")

def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default

def get_file_mtime_date(path):
    try:
        mtime = os.path.getmtime(path)
        return datetime.fromtimestamp(mtime, tz=timezone.utc).date()
    except Exception:
        return None

def main():
    last_poll = None
    signals_today = 0
    last_tier = None
    last_classification = None
    cron_active = True

    # 1. Read last success time
    success_data = read_json(os.path.expanduser("~/TRP/state/last_success.json"))
    if success_data:
        last_poll = success_data.get("timestamp")

    # 2. Count signals today (files in intents, detected_signals, or processed_signals modified today)
    today = datetime.now(timezone.utc).date()
    search_dirs = [
        os.path.expanduser("~/TRP/intents"),
        os.path.expanduser("~/TRP/detected_signals"),
        os.path.expanduser("~/TRP/processed_signals")
    ]

    all_intents = []
    for d in search_dirs:
        if os.path.exists(d):
            try:
                for f_name in os.listdir(d):
                    f_path = os.path.join(d, f_name)
                    if os.path.isfile(f_path):
                        mdate = get_file_mtime_date(f_path)
                        if mdate == today:
                            signals_today += 1
                        
                        # Gather all json intent files to find the latest
                        if f_name.endswith(".json"):
                            all_intents.append(f_path)
            except Exception as e:
                print(f"[trp_status] Error scanning {d}: {e}")

    # 3. Find last tier and classification from the latest intent file
    if all_intents:
        # Sort by modification time
        all_intents.sort(key=os.path.getmtime)
        latest_intent_path = all_intents[-1]
        intent = read_json(latest_intent_path)
        if intent:
            classif = intent.get("classification", {})
            last_tier = classif.get("tier")
            last_classification = classif.get("direction") or classif.get("type") or intent.get("abort_reason")

    payload = {
        "last_poll": last_poll,
        "signals_today": signals_today,
        "last_tier": last_tier,
        "last_classification": last_classification,
        "cron_active": cron_active,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    }

    # Ensure output dir exists
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"[trp_status] Poll {last_poll}, Today {signals_today}, Tier {last_tier}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
