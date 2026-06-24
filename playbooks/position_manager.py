#!/usr/bin/env python3
"""
Portfolio Position Manager v2.0 — June 24, 2026.
Shared module for cross-playbook exposure enforcement.

Two guards:
  1. COMBINED EXPOSURE CAP — 2% hard cap across all TRENDING playbooks.
     If Turtle is already in at 1.2%, Volume Breakout gets max 0.8%.
  2. RETEST OVERLAP DETECTOR — prevents Volume Breakout RETEST from
     stacking on the same breakout level Turtle already entered.

v2.0 adds fcntl.flock atomic locking (OpenCode audit + GetClaw approved).
"""
import os, json, fcntl, time

SITE = "/home/maswilee/projects/pipeline-dashboard-v3"
DATA_DIR = os.path.join(SITE, "data")
LOCK_FILE = os.path.join(DATA_DIR, ".positions.lock")

# Playbook output files
PLAYBOOK_FILES = {
    "turtle_breakout":      os.path.join(DATA_DIR, "playbook_turtle_breakout.json"),
    "mean_reversion":       os.path.join(DATA_DIR, "playbook_mean_reversion.json"),
    "liquidation_momentum": os.path.join(DATA_DIR, "playbook_liquidation_momentum.json"),
    "funding_rate_mr":      os.path.join(DATA_DIR, "playbook_funding_rate_mr.json"),
    "volume_breakout":      os.path.join(DATA_DIR, "playbook_volume_breakout.json"),
    "cross_asset_macro":    os.path.join(DATA_DIR, "playbook_cross_asset_macro.json"),
}

# Portfolio hard caps
COMBINED_EXPOSURE_CAP_PCT = 2.0          # Hard cap: total risk across all active positions
TRENDING_GROUP_CAP_PCT = 2.0             # Cap for Turtle + Volume Breakout combined
RETEST_OVERLAP_TOLERANCE_PCT = 0.3       # Within 0.3% of same breakout level = overlap

# Lock settings
LOCK_TIMEOUT_SECONDS = 5                 # Max wait for lock acquisition
LOCK_RETRY_INTERVAL = 0.1                # Retry every 100ms


def load_json(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        print(f"[position_manager] Error loading {path}: {e}")
        return None


class PositionLock:
    """
    Context manager for atomic position updates.
    Acquires exclusive lock before reading active positions,
    releases after write. Blocks with timeout.
    """
    def __init__(self, lock_path=None):
        self.lock_path = lock_path or LOCK_FILE
        self.lock_fd = None

    def __enter__(self):
        # Ensure lock file exists
        if not os.path.exists(self.lock_path):
            open(self.lock_path, 'w').close()
        self.lock_fd = open(self.lock_path, 'r')
        deadline = time.time() + LOCK_TIMEOUT_SECONDS
        while True:
            try:
                fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except BlockingIOError:
                if time.time() >= deadline:
                    raise TimeoutError(f"Could not acquire position lock after {LOCK_TIMEOUT_SECONDS}s")
                time.sleep(LOCK_RETRY_INTERVAL)

    def __exit__(self, *args):
        if self.lock_fd:
            fcntl.flock(self.lock_fd, fcntl.LOCK_UN)
            self.lock_fd.close()
            self.lock_fd = None


def acquire_position_lock():
    """Returns a PositionLock context manager. Use: with acquire_position_lock(): ..."""
    return PositionLock()


def get_active_positions():
    """
    Scan all playbook outputs. Return dict keyed by playbook name.
    Each entry: {signal, direction, position_size_pct, entry_price, stop_loss, tp_primary, breakout_level, timestamp}
    Only includes positions with signal != "NO_SIGNAL" and status != "inactive"/"offline".

    NOTE: Callers should hold the position lock before calling this during
    the read→check→write critical section.
    """
    active = {}
    for name, path in PLAYBOOK_FILES.items():
        data = load_json(path)
        if not data:
            continue
        # Skip inactive/offline
        status = data.get("status", "")
        if status in ("inactive", "offline"):
            continue
        signal = data.get("signal", "NO_SIGNAL")
        if signal == "NO_SIGNAL":
            continue
        active[name] = {
            "signal": signal,
            "direction": "LONG" if signal == "LONG" else "SHORT",
            "position_size_pct": data.get("position_size_pct", 0),
            "entry_price": data.get("entry_price"),
            "stop_loss": data.get("stop_loss"),
            "tp_primary": data.get("tp_primary"),
            "breakout_level": data.get("breakout_level"),
            "donchian_high_20h": data.get("donchian_high_20h"),
            "donchian_low_20h": data.get("donchian_low_20h"),
            "timestamp": data.get("timestamp"),
            "regime": data.get("regime"),
        }
    return active


def get_total_exposure():
    """Sum of all active position sizes across all playbooks."""
    positions = get_active_positions()
    return sum(p["position_size_pct"] for p in positions.values())


def get_trending_exposure():
    """Sum of Turtle + Volume Breakout positions only."""
    positions = get_active_positions()
    total = 0
    for name in ("turtle_breakout", "volume_breakout"):
        if name in positions:
            total += positions[name]["position_size_pct"]
    return total


def check_exposure_cap(requested_size_pct, playbook_name):
    """
    Check if the requested position size would breach the combined cap.
    Returns (allowed_size_pct, reason).

    allowed_size_pct: the position size after capping (never negative, never > requested)
    reason: None if uncapped, or explanation string if capped

    NOTE: Callers should hold the position lock before calling this.
    """
    positions = get_active_positions()

    # If this playbook already has an active position, count it as replaced not added
    existing_self = positions.get(playbook_name, {}).get("position_size_pct", 0)

    # Total exposure from OTHER playbooks (excluding self)
    other_exposure = sum(
        p["position_size_pct"]
        for name, p in positions.items()
        if name != playbook_name
    )

    available = COMBINED_EXPOSURE_CAP_PCT - other_exposure

    if available <= 0:
        return 0, f"Portfolio cap {COMBINED_EXPOSURE_CAP_PCT}% reached — {other_exposure:.1f}% already allocated"

    if requested_size_pct <= available:
        return requested_size_pct, None

    capped = round(available, 2)
    return capped, f"Capped from {requested_size_pct}% → {capped}% (portfolio cap {COMBINED_EXPOSURE_CAP_PCT}%, {other_exposure:.1f}% in use)"


def check_turtle_overlap(breakout_level, direction, tolerance_pct=None):
    """
    Check if Turtle Breakout has already entered at or near the same breakout level.
    Returns (overlap_detected, detail_dict).
    """
    if tolerance_pct is None:
        tolerance_pct = RETEST_OVERLAP_TOLERANCE_PCT

    positions = get_active_positions()
    turtle = positions.get("turtle_breakout")

    if not turtle:
        return False, {"reason": "Turtle Breakout not active"}

    if turtle["direction"] != direction:
        return False, {"reason": f"Turtle direction ({turtle['direction']}) != RETEST direction ({direction})"}

    turtle_level = None
    if direction == "LONG":
        turtle_level = turtle.get("donchian_high_20h")
    else:
        turtle_level = turtle.get("donchian_low_20h")

    if turtle_level is None or breakout_level is None:
        return False, {"reason": "Missing breakout level data"}

    if turtle_level == 0 or breakout_level == 0:
        return False, {"reason": "Zero breakout level"}

    distance_pct = abs(breakout_level - turtle_level) / turtle_level * 100

    if distance_pct <= tolerance_pct:
        return True, {
            "reason": f"Turtle already entered at ${turtle_level:,.0f} — RETEST level ${breakout_level:,.0f} is {distance_pct:.2f}% away (≤ {tolerance_pct}% tolerance)",
            "turtle_level": turtle_level,
            "retest_level": breakout_level,
            "distance_pct": round(distance_pct, 2),
            "turtle_size": turtle["position_size_pct"],
            "remaining_cap": round(COMBINED_EXPOSURE_CAP_PCT - turtle["position_size_pct"], 2),
        }

    return False, {
        "reason": f"Different breakout level — Turtle ${turtle_level:,.0f}, RETEST ${breakout_level:,.0f} = {distance_pct:.1f}% apart",
        "distance_pct": round(distance_pct, 2),
    }
