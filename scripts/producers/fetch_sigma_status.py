#!/usr/bin/env python3
"""
Fetch SIGMA Status
Produces manual placeholder for SIGMA Conviction status in data/sigma_status.json.
"""
import sys
import os
import json
from datetime import datetime, timezone

SITE = "/home/maswilee/projects/pipeline-dashboard-v3"
OUTPUT_PATH = os.path.join(SITE, "data/sigma_status.json")

def main():
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    # Check if existing sigma_status.json has a real manual last_updated value
    existing_last_updated = None
    if os.path.exists(OUTPUT_PATH):
        try:
            with open(OUTPUT_PATH) as f:
                existing = json.load(f)
            # Preserve existing last_updated only if it's a real manual timestamp (not None)
            existing_last_updated = existing.get("last_updated")
        except Exception:
            pass

    payload = {
        "sigma_state": "NEUTRAL",
        "sigma_trend": "compressing",
        "sigma_percentile": 17,
        "sigma_gate": "CAUTION",
        "sigma_regime": "LOW_VOL",
        "sigma_1h_realized": 58.54,
        "sigma_1d_realized": 53.08,
        "direction": "NEUTRAL",
        "conviction": "MEDIUM",
        # Preserve real manual timestamp if exists; otherwise mirror the auto-timestamp
        "last_updated": existing_last_updated if existing_last_updated else ts,
        "source": "GetClaw via Milo",
        "timestamp": ts
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"[sigma_status] Wrote manual placeholder")
    return 0

if __name__ == "__main__":
    sys.exit(main())
