"""
PFC-3L Signal Intelligence Engine — Phase 1
Reads pipeline data.json → 4 strategic components + data quality → 6-state output
Deterministic Python logic. No LLM control over signals.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Thresholds (from spec, configurable via YAML in Phase 2) ──

THRESHOLDS = {
    "positioning": {
        "score_min": 70,
        "balance_diff": 10,
        "balance_override": 80,
        "balance_under": 55,
        "funding_extreme_percentile": 10,  # bottom/top 10%
        "oi_elevation_z": 1.0,
    },
    "flow": {
        "score_min": 70,
        "derivatives_only_ratio": 1.8,
        "taker_strong": 0.55,
        "taker_moderate": 0.52,
        "taker_weak": 0.48,
        "cvd_agreement_min": 1,  # minimum venues agreeing
    },
    "catalyst": {
        "confidence_min": 70,
        "vix_spike": 25,
        "fng_extreme_fear": 20,
        "fng_extreme_greed": 80,
        "crash_active_max": 2,
        "black_swan_max": 2,
        "etf_outflow_daily_m": -200,
        "etf_inflow_daily_m": 200,
    },
    "levels": {
        "score_min": 60,
        "max_distance_pct": 1.5,
        "second_test_penalty": 10,
        "third_test_penalty": 25,
    },
    "data_quality": {
        "score_min": 90,
        "min_spot_venues": 2,
        "min_derivatives_venues": 1,
        "max_critical_age_seconds": 300,
        "max_warning_age_seconds": 900,
    },
    "signal": {
        "cooldown_minutes": 20,
        "max_chase_pct": 1.5,
        "watch_min_components": 3,
    },
}

# ── Data Quality Engine ──

def evaluate_data_quality(data: dict) -> dict[str, Any]:
    """Check feed health from status/sources sections."""
    status = data.get("status", {})
    sources = data.get("sources", {})
    timestamps = status.get("source_timestamps", {})
    warnings = status.get("staleness_warnings", [])
    header = data.get("header", {})
    ai_factors = data.get("ai_factors", {})

    score = 100
    reasons: list[str] = []
    vetoes: list[str] = []
    now = datetime.now(timezone.utc)
    healthy_count = 0
    T = THRESHOLDS["data_quality"]

    # Check each feed source
    feed_map = {
        "amt": {"ts_key": "amt", "label": "AMT feed"},
        "volume_profile": {"ts_key": "vp", "label": "Volume Profile"},
        "ai_factors": {"label": "AI Factors"},
        "redline": {"label": "Redline (optional)"},
        "trap_monitor": {"label": "Trap Monitor (optional)"},
    }

    for feed_key, cfg in feed_map.items():
        source = sources.get(feed_key)
        if not source:
            continue

        # Skip if source has error
        if isinstance(source, dict) and source.get("error"):
            if feed_key not in ("redline", "trap_monitor"):  # optional
                reasons.append(f"{cfg['label']} unavailable")
                score -= 15
            continue

        # Check timestamp
        ts_key = cfg.get("ts_key", feed_key)
        ts_str = timestamps.get(ts_key)

        # AI Factors has its own timestamp
        if feed_key == "ai_factors":
            ts_str = ai_factors.get("last_updated") or ts_str

        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                age = (now - ts).total_seconds()
                if age < T["max_critical_age_seconds"]:
                    healthy_count += 1
                elif age < T["max_warning_age_seconds"]:
                    reasons.append(f"{cfg['label']} stale ({int(age)}s)")
                    score -= 8
                else:
                    if feed_key not in ("redline", "trap_monitor"):
                        vetoes.append(f"{cfg['label']} >15min old ({int(age/60)}m)")
                        score -= 20
                    else:
                        reasons.append(f"{cfg['label']} stale ({int(age/60)}m)")
                    healthy_count += 1  # still present
            except (ValueError, TypeError):
                if feed_key not in ("redline", "trap_monitor"):
                    vetoes.append(f"{cfg['label']} timestamp unparseable")
                    score -= 20
        else:
            if feed_key not in ("redline", "trap_monitor"):
                reasons.append(f"{cfg['label']} no timestamp")
                score -= 10

    # Check minimum critical feeds (AMT + VP + AI Factors)
    if healthy_count < 2:
        vetoes.append(f"Only {healthy_count} critical feeds healthy (need 2+)")

    # Packet age from header
    header_ts = header.get("generated_timestamp")
    if header_ts:
        try:
            gen_ts = datetime.fromisoformat(header_ts.replace("Z", "+00:00"))
            age = (now - gen_ts).total_seconds()
            if age > T["max_warning_age_seconds"]:
                vetoes.append(f"Packet stale ({int(age/60)}m old)")
                score -= 30
        except (ValueError, TypeError):
            pass

    # Warnings deduct
    if isinstance(warnings, list):
        score -= len(warnings) * 5

    score = max(0, score)
    directional_allowed = score >= T["score_min"] and not vetoes

    return {
        "score": score,
        "directional_allowed": directional_allowed,
        "healthy_feeds": healthy_count,
        "total_critical_feeds": len([f for f in feed_map if f not in ("redline", "trap_monitor")]),
        "reasons": reasons,
        "vetoes": vetoes,
    }


# ── Positioning Engine ──

def evaluate_positioning(data: dict) -> dict[str, Any]:
    """Evaluate whether longs or shorts are vulnerable."""
    enriched = data.get("enriched", {})
    context = data.get("context", {})

    funding = enriched.get("funding_rate", 0) or 0
    oi_change = enriched.get("oi_change_24h_pct", 0) or 0
    oi_delta = enriched.get("oi_delta", "FLAT")
    oi_trend = enriched.get("oi_trend", "stable")
    long_short = context.get("long_short_ratio", 1.0) or 1.0
    basis = context.get("perp_basis_pct", 0) or 0

    reasons: list[str] = []
    vetoes: list[str] = []

    # ── Short vulnerability scoring ──
    short_score = 0

    # Negative funding (shorts paying longs → shorts vulnerable)
    if isinstance(funding, (int, float)) and funding < -0.0001:
        short_score += 25
        reasons.append(f"Funding strongly negative ({funding:.6f}) — shorts are paying")
    elif isinstance(funding, (int, float)) and funding < 0:
        short_score += 15
        reasons.append(f"Funding slightly negative ({funding:.6f})")

    # OI elevation (high OI + declining price = trapped longs OR trapped shorts)
    if isinstance(oi_change, (int, float)):
        if oi_change > 10:
            short_score += 20
            reasons.append(f"OI elevated +{oi_change:.1f}% — crowded positioning")
        elif oi_change > 5:
            short_score += 10
            reasons.append(f"OI rising +{oi_change:.1f}%")

    # OI acceleration
    if oi_delta == "RISING" and oi_trend != "declining":
        short_score += 10
        reasons.append("OI accelerating upward")

    # Basis — negative/compressed basis favors shorts being trapped
    if isinstance(basis, (int, float)) and basis < -0.5:
        short_score += 15
        reasons.append(f"Basis negative ({basis:.2f}%)")
    elif isinstance(basis, (int, float)) and basis < 0:
        short_score += 5

    # Long/short ratio
    if isinstance(long_short, (int, float)):
        if long_short < 0.8:
            short_score += 20
            reasons.append(f"Long/short ratio low ({long_short:.2f}) — shorts crowded")
        elif long_short < 0.95:
            short_score += 10

    # ── Long vulnerability scoring ──
    long_score = 0

    # Positive funding (longs paying shorts → longs vulnerable)
    if isinstance(funding, (int, float)) and funding > 0.0005:
        long_score += 25
        reasons.append(f"Funding strongly positive ({funding:.6f}) — longs are paying")
    elif isinstance(funding, (int, float)) and funding > 0.0001:
        long_score += 15
        reasons.append(f"Funding elevated ({funding:.6f})")

    # OI elevation for longs
    if isinstance(oi_change, (int, float)) and oi_change > 10:
        long_score += 20
    elif isinstance(oi_change, (int, float)) and oi_change > 5:
        long_score += 10

    if oi_delta == "RISING" and oi_trend != "declining":
        long_score += 10

    # Positive basis
    if isinstance(basis, (int, float)) and basis > 1.0:
        long_score += 15
        reasons.append(f"Basis elevated ({basis:.2f}%) — longs paying premium")
    elif isinstance(basis, (int, float)) and basis > 0.5:
        long_score += 5

    # Long/short ratio high
    if isinstance(long_short, (int, float)):
        if long_short > 1.5:
            long_score += 20
            reasons.append(f"Long/short ratio high ({long_short:.2f}) — longs crowded")
        elif long_short > 1.2:
            long_score += 10

    # ── State determination ──
    T = THRESHOLDS["positioning"]
    diff = abs(short_score - long_score)

    if short_score >= T["score_min"] and (short_score - long_score) > T["balance_diff"]:
        state = "SHORTS_VULNERABLE"
        score = short_score
        opposite = long_score
    elif long_score >= T["score_min"] and (long_score - short_score) > T["balance_diff"]:
        state = "LONGS_VULNERABLE"
        score = long_score
        opposite = short_score
    elif short_score >= T["balance_override"] and long_score < T["balance_under"]:
        state = "SHORTS_VULNERABLE"
        score = short_score
        opposite = long_score
    elif long_score >= T["balance_override"] and short_score < T["balance_under"]:
        state = "LONGS_VULNERABLE"
        score = long_score
        opposite = short_score
    else:
        state = "BALANCED"
        score = max(short_score, long_score)
        opposite = min(short_score, long_score)

    if not reasons:
        reasons.append("No significant positioning extremes detected")

    return {
        "state": state,
        "score": score,
        "long_vulnerability_score": long_score,
        "short_vulnerability_score": short_score,
        "opposite_score": opposite,
        "reasons": reasons,
        "vetoes": vetoes,
    }


# ── Flow Engine ──

def evaluate_flow(data: dict) -> dict[str, Any]:
    """Determine whether real spot money is buying or selling."""
    enriched = data.get("enriched", {})
    critical = data.get("critical", {})

    taker_ratio = enriched.get("taker_buy_ratio", 0.5) or 0.5
    coinbase_premium = enriched.get("coinbase_premium", 0) or 0
    liquidity = enriched.get("liquidity_verdict", "UNKNOWN")
    cvd_data = critical.get("cvd_per_tf", {}) or {}
    delta_trend = critical.get("delta_trend", "NEUTRAL")
    delta_sum = critical.get("delta_sum_6", 0) or 0

    reasons: list[str] = []
    vetoes: list[str] = []

    T = THRESHOLDS["flow"]

    # ── Bullish score ──
    bull_score = 0

    if isinstance(taker_ratio, (int, float)):
        if taker_ratio >= T["taker_strong"]:
            bull_score += 30
            reasons.append(f"Taker buy ratio strong ({taker_ratio:.3f})")
        elif taker_ratio >= T["taker_moderate"]:
            bull_score += 15
            reasons.append(f"Taker buy ratio moderate ({taker_ratio:.3f})")

    # Cross-exchange: Coinbase premium
    if isinstance(coinbase_premium, (int, float)):
        if coinbase_premium > 0.1:
            bull_score += 20
            reasons.append(f"Coinbase premium positive ({coinbase_premium:.2f}%) — US institutional buying")
        elif coinbase_premium > 0:
            bull_score += 10
        elif coinbase_premium < -0.3:
            bull_score -= 10
            reasons.append(f"Coinbase discount ({coinbase_premium:.2f}%) — US selling")

    # CVD momentum
    if delta_trend == "STRONG_BUY":
        bull_score += 20
        reasons.append(f"CVD delta trend: strong buy (sum: {delta_sum})")
    elif delta_trend == "BUY":
        bull_score += 10
        reasons.append(f"CVD delta trend: buy")

    # Spot leads perpetuals
    cvd_spot = cvd_data.get("spot", {}) if isinstance(cvd_data, dict) else {}
    cvd_perp = cvd_data.get("perpetual", {}) if isinstance(cvd_data, dict) else {}
    # Simplified check: if spot CVD is stronger
    if isinstance(cvd_spot, dict) and isinstance(cvd_perp, dict):
        spot_net = sum(v for v in cvd_spot.values() if isinstance(v, (int, float)))
        perp_net = sum(v for v in cvd_perp.values() if isinstance(v, (int, float)))
        if spot_net > perp_net * 1.1 and spot_net > 0:
            bull_score += 20
            reasons.append("Spot CVD leads perpetuals")
        elif perp_net > abs(spot_net) * T["derivatives_only_ratio"]:
            vetoes.append("Derivatives-led movement — spot not confirming")
    else:
        bull_score += 10  # No comparison possible, neutral bonus

    # Liquidity health
    if liquidity == "HEALTHY":
        bull_score += 10
    elif liquidity in ("DRY", "EVAPORATING"):
        bull_score -= 15
        reasons.append(f"Liquidity {liquidity} — caution")

    # ── Bearish score (mirror) ──
    bear_score = 0

    if isinstance(taker_ratio, (int, float)):
        if taker_ratio <= (1 - T["taker_strong"]):
            bear_score += 30
            reasons.append(f"Taker sell ratio strong ({1-taker_ratio:.3f})")
        elif taker_ratio <= (1 - T["taker_moderate"]):
            bear_score += 15
            reasons.append(f"Taker sell ratio moderate ({1-taker_ratio:.3f})")

    # Coinbase discount
    if isinstance(coinbase_premium, (int, float)):
        if coinbase_premium < -0.2:
            bear_score += 20
            reasons.append(f"Coinbase discount ({coinbase_premium:.2f}%) — US institutional selling")
        elif coinbase_premium < -0.05:
            bear_score += 10

    if delta_trend == "STRONG_SELL":
        bear_score += 20
        reasons.append(f"CVD delta trend: strong sell")
    elif delta_trend == "SELL":
        bear_score += 10
        reasons.append(f"CVD delta trend: sell")

    if liquidity in ("DRY", "EVAPORATING"):
        bear_score += 5

    # ── State determination ──
    if vetoes:
        # Check if derivatives-only
        if any("Derivatives-led" in v for v in vetoes):
            state = "DERIVATIVES_ONLY"
            score = 0
        else:
            state = "CONFLICTED"
            score = 0
    elif bull_score >= T["score_min"]:
        state = "STRONG_SPOT_BUYING" if bull_score >= 75 else "MODERATE_SPOT_BUYING"
        score = bull_score
    elif bear_score >= T["score_min"]:
        state = "STRONG_SPOT_SELLING" if bear_score >= 75 else "MODERATE_SPOT_SELLING"
        score = bear_score
    elif abs(bull_score - bear_score) < 10:
        state = "NEUTRAL"
        score = max(bull_score, bear_score)
    else:
        state = "NEUTRAL"
        score = max(bull_score, bear_score)

    if not reasons:
        reasons.append("Flow is balanced — no dominant direction")

    return {
        "state": state,
        "score": score,
        "bullish_score": bull_score,
        "bearish_score": bear_score,
        "taker_buy_ratio": taker_ratio,
        "coinbase_premium": coinbase_premium,
        "healthy_spot_venues": 2 if coinbase_premium is not None else 1,
        "reasons": reasons,
        "vetoes": vetoes,
    }


# ── Catalyst Engine ──

def evaluate_catalyst(data: dict) -> dict[str, Any]:
    """Evaluate whether a directional catalyst is active."""
    enriched = data.get("enriched", {})
    ai_factors = data.get("ai_factors", {})

    vix = enriched.get("vix", 20)
    fng = enriched.get("fng_value", 50)
    crash_status = enriched.get("crash_status", "NORMAL")
    crash_score = enriched.get("crash_score", 0)
    black_swan = enriched.get("black_swan_status", "NORMAL")
    black_swan_score = enriched.get("black_swan_score", 0)
    fng_class = enriched.get("fng_classification", "neutral")
    tripwires = ai_factors.get("tripwire_summary", {})

    reasons: list[str] = []
    vetoes: list[str] = []
    confidence = 0
    direction = "NONE"

    T = THRESHOLDS["catalyst"]

    # VIX spike detection
    if isinstance(vix, (int, float)):
        if vix >= T["vix_spike"]:
            confidence += 25
            reasons.append(f"VIX elevated at {vix} — risk-off environment")
            direction = "NEGATIVE"
        elif vix >= 22:
            confidence += 15
            reasons.append(f"VIX elevated at {vix} — caution")

    # Fear & Greed extremes
    if isinstance(fng, (int, float)):
        if fng <= T["fng_extreme_fear"]:
            confidence += 25
            reasons.append(f"Fear & Greed: extreme fear ({fng}) — contrarian bullish")
            # Extreme fear → contrarian bullish catalyst
            if direction == "NONE":
                direction = "POSITIVE"
        elif fng <= 35:
            confidence += 15
            reasons.append(f"Fear & Greed: fear ({fng})")
            if direction == "NONE":
                direction = "POSITIVE"
        elif fng >= T["fng_extreme_greed"]:
            confidence += 25
            reasons.append(f"Fear & Greed: extreme greed ({fng}) — contrarian bearish")
            if direction == "NONE" or direction == "POSITIVE":
                direction = "NEGATIVE"

    # Crash precursor
    if crash_status == "ACTIVE":
        confidence += 20
        reasons.append(f"Crash precursor ACTIVE ({crash_score}) — bearish catalyst")
        direction = "NEGATIVE"
    elif crash_status == "CAUTION":
        confidence += 10
        reasons.append(f"Crash precursor: CAUTION ({crash_score})")

    # Black swan
    if black_swan != "NORMAL":
        confidence += 20
        reasons.append(f"Black swan {black_swan} ({black_swan_score}/17)")

    # AI Factors tripwires
    active_trips = tripwires.get("active_count", 0) if isinstance(tripwires, dict) else 0
    if active_trips > 0:
        confidence += 15
        reasons.append(f"{active_trips} AI factor tripwire(s) active")

    # ETF flows from enriched
    etf_daily = enriched.get("etf_flow_daily", 0) or 0
    if etf_daily < T["etf_outflow_daily_m"]:
        confidence += 20
        reasons.append(f"ETF daily outflow {etf_daily}M — bearish flow catalyst")
        direction = "NEGATIVE"
    elif etf_daily > T["etf_inflow_daily_m"]:
        confidence += 20
        reasons.append(f"ETF daily inflow {etf_daily}M — bullish flow catalyst")
        if direction == "NONE":
            direction = "POSITIVE"

    # State determination
    if direction == "NONE":
        state = "NONE"
    elif confidence >= T["confidence_min"]:
        state = direction  # POSITIVE or NEGATIVE
    elif confidence >= 40:
        state = "MIXED"
    else:
        state = "NONE"

    if not reasons:
        reasons.append("No active catalyst detected")

    # Source quality (always official — data.json is vetted)
    source_quality = 25  # base
    source_quality += 15  # all data from known sources

    return {
        "state": state,
        "confidence": confidence,
        "direction": direction,
        "source_quality": min(100, confidence + source_quality),
        "reasons": reasons,
        "vetoes": vetoes,
    }


# ── Psychological Level Engine ──

def generate_levels(price: float, sr_1h: dict, sr_1d: dict, vp: dict) -> list[dict]:
    """Generate psychological levels around current price."""
    levels = []

    # Use S/R bands as primary levels
    if isinstance(sr_1h, dict):
        for role, p in [("ACCELERATOR", sr_1h.get("resistance")), ("ACCELERATOR", sr_1h.get("support"))]:
            if isinstance(p, (int, float)) and p > 0:
                dist = abs(p - price) / price * 100
                if dist < THRESHOLDS["levels"]["max_distance_pct"]:
                    levels.append({
                        "price": p,
                        "role": role,
                        "category": "MINOR",
                        "source": "sr_1h",
                        "distance_pct": round(dist, 2),
                        "score": min(100, 100 - int(dist * 10)),
                    })

    if isinstance(sr_1d, dict):
        for p in [sr_1d.get("resistance"), sr_1d.get("support")]:
            if isinstance(p, (int, float)) and p > 0:
                dist = abs(p - price) / price * 100
                if dist < 5:
                    levels.append({
                        "price": p,
                        "role": "ACCELERATOR",
                        "category": "STANDARD",
                        "source": "sr_1d",
                        "distance_pct": round(dist, 2),
                        "score": min(100, 100 - int(dist * 5)),
                    })

    # Volume Profile levels
    if isinstance(vp, dict):
        for key, label in [("poc", "POC"), ("val", "VAL"), ("vah", "VAH")]:
            p = vp.get(f"vp_{key}")
            if isinstance(p, (int, float)) and p > 0:
                dist = abs(p - price) / price * 100
                if dist < 5:
                    role = "ACCELERATOR" if dist < 1.5 else "ABSORBER"
                    levels.append({
                        "price": p,
                        "role": role,
                        "category": "STANDARD",
                        "source": f"vp_{key}",
                        "distance_pct": round(dist, 2),
                        "score": min(100, 80 - int(dist * 8)),
                    })

    # Sort by distance
    levels.sort(key=lambda l: l["distance_pct"])
    return levels[:6]


def evaluate_levels(data: dict) -> dict[str, Any]:
    """Evaluate which psychological level is active."""
    enriched = data.get("enriched", {})
    critical = data.get("critical", {})
    reference = data.get("reference", {})

    price = enriched.get("btc_price", 0) or 0
    sr_1h = reference.get("sr_1h", {}) or {}
    sr_1d = reference.get("sr_1d", {}) or {}
    vp = {
        "vp_poc": critical.get("vp_poc"),
        "vp_val": critical.get("vp_val"),
        "vp_vah": critical.get("vp_vah"),
    }

    if not price:
        return {
            "state": "INACTIVE",
            "score": 0,
            "role": "INACTIVE",
            "levels": [],
            "reasons": ["No BTC price available"],
            "vetoes": [],
        }

    all_levels = generate_levels(price, sr_1h, sr_1d, vp)
    reasons: list[str] = []

    # Find active level (closest significant one)
    active = None
    for lvl in all_levels:
        if lvl["score"] >= THRESHOLDS["levels"]["score_min"]:
            active = lvl
            break

    if active:
        reasons.append(
            f"Active {active['category'].lower()} level at ${active['price']:,.0f} "
            f"({active['distance_pct']:.2f}% away, role: {active['role']})"
        )
        return {
            "state": "ACTIVE",
            "score": active["score"],
            "role": active["role"],
            "active_level": active,
            "levels": all_levels,
            "reasons": reasons,
            "vetoes": [],
        }

    reasons.append("No significant psychological level near current price")
    return {
        "state": "INACTIVE",
        "score": 0,
        "role": "INACTIVE",
        "active_level": None,
        "levels": all_levels,
        "reasons": reasons,
        "vetoes": [],
    }


# ── Signal Engine ──

def evaluate_signal(
    positioning: dict,
    flow: dict,
    catalyst: dict,
    levels: dict,
    data_quality: dict,
) -> dict[str, Any]:
    """Combine all 4 engines into final signal state."""
    reasons: list[str] = []
    vetoes: list[str] = []
    T = THRESHOLDS["signal"]

    # Data quality override
    if not data_quality["directional_allowed"]:
        return {
            "state": "DATA_UNRELIABLE",
            "confidence": 0,
            "lifecycle_state": "ACTIVE",
            "reasons": data_quality.get("reasons", []),
            "vetoes": data_quality.get("vetoes", []) + ["DATA QUALITY VETO — directional signals blocked"],
            "gates": {
                "positioning": positioning["state"],
                "flow": flow["state"],
                "catalyst": catalyst["state"],
                "level": levels["role"],
                "data_quality": f"FAILED ({data_quality['score']}/100)",
            },
            "invalidation_conditions": [],
            "informational_zones": [],
        }

    # ── LONG_CANDIDATE check ──
    long_gates = {
        "positioning": positioning["state"] == "SHORTS_VULNERABLE" and positioning["score"] >= T.get("positioning_min", 70),
        "flow": flow["state"] in ("STRONG_SPOT_BUYING", "MODERATE_SPOT_BUYING") and flow["score"] >= T.get("flow_score_min", 70),
        "catalyst": catalyst["state"] == "POSITIVE" and catalyst["confidence"] >= THRESHOLDS["catalyst"]["confidence_min"],
        "level": levels["role"] in ("ACCELERATOR", "ABSORBER") and levels["score"] >= THRESHOLDS["levels"]["score_min"],
        "data_quality": data_quality["score"] >= THRESHOLDS["data_quality"]["score_min"],
    }

    # ── SHORT_CANDIDATE check ──
    short_gates = {
        "positioning": positioning["state"] == "LONGS_VULNERABLE" and positioning["score"] >= T.get("positioning_min", 70),
        "flow": flow["state"] in ("STRONG_SPOT_SELLING", "MODERATE_SPOT_SELLING") and flow["score"] >= T.get("flow_score_min", 70),
        "catalyst": catalyst["state"] == "NEGATIVE" and catalyst["confidence"] >= THRESHOLDS["catalyst"]["confidence_min"],
        "level": levels["role"] in ("ACCELERATOR", "ABSORBER") and levels["score"] >= THRESHOLDS["levels"]["score_min"],
        "data_quality": data_quality["score"] >= THRESHOLDS["data_quality"]["score_min"],
    }

    # ── Veto checks ──
    if flow["state"] == "DERIVATIVES_ONLY":
        vetoes.append("DERIVATIVES_ONLY — spot not confirming, no candidate allowed")
    if flow["state"] == "CONFLICTED":
        vetoes.append("CONFLICTED flow — venues disagree, no candidate")
    if catalyst["state"] in ("MIXED", "UNVERIFIED", "STALE"):
        vetoes.append(f"Catalyst is {catalyst['state']} — cannot produce candidate")
    if positioning["state"] == "BALANCED":
        vetoes.append("Positioning is balanced — no vulnerable side")

    # ── Signal decision ──
    long_pass = sum(long_gates.values()) - long_gates["data_quality"]  # data quality is binary gate
    short_pass = sum(short_gates.values()) - short_gates["data_quality"]

    if not vetoes:
        if all(long_gates.values()):
            base = min(
                positioning["score"],
                flow["score"],
                catalyst["confidence"],
                levels["score"],
            )
            return {
                "state": "LONG_CANDIDATE",
                "confidence": min(100, base + 5),
                "lifecycle_state": "CANDIDATE",
                "positioning": positioning,
                "flow": flow,
                "catalyst": catalyst,
                "levels": levels,
                "reasons": positioning["reasons"] + flow["reasons"] + catalyst["reasons"] + levels["reasons"],
                "vetoes": vetoes,
                "gates": long_gates,
                "invalidation_conditions": [
                    "Spot CVD turns strongly negative for 2+ evaluation intervals",
                    "Price returns below the trigger level for confirmation window",
                    "Flow becomes derivatives-only or conflicted",
                    "Catalyst expires or is corrected",
                    "Data becomes unreliable",
                ],
                "informational_zones": [l["price"] for l in levels.get("levels", [])[:3]],
            }

        if all(short_gates.values()):
            base = min(
                positioning["score"],
                flow["score"],
                catalyst["confidence"],
                levels["score"],
            )
            return {
                "state": "SHORT_CANDIDATE",
                "confidence": min(100, base + 5),
                "lifecycle_state": "CANDIDATE",
                "positioning": positioning,
                "flow": flow,
                "catalyst": catalyst,
                "levels": levels,
                "reasons": positioning["reasons"] + flow["reasons"] + catalyst["reasons"] + levels["reasons"],
                "vetoes": vetoes,
                "gates": short_gates,
                "invalidation_conditions": [
                    "Spot CVD turns strongly positive for 2+ evaluation intervals",
                    "Price returns above the trigger level for confirmation window",
                    "Flow becomes derivatives-only or conflicted",
                    "Catalyst expires or is corrected",
                    "Data becomes unreliable",
                ],
                "informational_zones": [l["price"] for l in levels.get("levels", [])[:3]],
            }

        # ── WATCH states ──
        if long_gates["positioning"] and long_pass >= T["watch_min_components"] - 1:  # positioning + 2 others
            missing = [k for k, v in long_gates.items() if not v and k != "data_quality"]
            return {
                "state": "WATCH_LONG",
                "confidence": min(100, (long_pass / 4) * 100),
                "lifecycle_state": "WATCH",
                "positioning": positioning,
                "flow": flow,
                "catalyst": catalyst,
                "levels": levels,
                "reasons": positioning["reasons"] + flow["reasons"] + catalyst["reasons"] + levels["reasons"],
                "vetoes": vetoes,
                "gates": long_gates,
                "missing_components": missing,
                "invalidation_conditions": [],
                "informational_zones": [],
            }

        if short_gates["positioning"] and short_pass >= T["watch_min_components"] - 1:
            missing = [k for k, v in short_gates.items() if not v and k != "data_quality"]
            return {
                "state": "WATCH_SHORT",
                "confidence": min(100, (short_pass / 4) * 100),
                "lifecycle_state": "WATCH",
                "positioning": positioning,
                "flow": flow,
                "catalyst": catalyst,
                "levels": levels,
                "reasons": positioning["reasons"] + flow["reasons"] + catalyst["reasons"] + levels["reasons"],
                "vetoes": vetoes,
                "gates": short_gates,
                "missing_components": missing,
                "invalidation_conditions": [],
                "informational_zones": [],
            }

    # ── Default: NO_TRADE ──
    if vetoes:
        reasons = vetoes + reasons

    return {
        "state": "NO_TRADE",
        "confidence": 0,
        "lifecycle_state": "ACTIVE",
        "positioning": positioning,
        "flow": flow,
        "catalyst": catalyst,
        "levels": levels,
        "reasons": reasons,
        "vetoes": vetoes,
        "gates": {**long_gates, **{f"short_{k}": v for k, v in short_gates.items()}},
        "invalidation_conditions": [],
        "informational_zones": [],
    }


# ── Main ──

def run(data: dict) -> dict:
    """Full PFC-3L evaluation pipeline."""
    dq = evaluate_data_quality(data)
    pos = evaluate_positioning(data)
    flo = evaluate_flow(data)
    cat = evaluate_catalyst(data)
    lvl = evaluate_levels(data)
    sig = evaluate_signal(pos, flo, cat, lvl, dq)

    btc_price = (data.get("enriched", {}) or {}).get("btc_price") or (data.get("header", {}) or {}).get("btc_price") or 0

    return {
        "signal": {
            "id": f"pfc3l-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
            "ts": datetime.now(timezone.utc).isoformat(),
            "symbol": "BTC/USD",
            "reference_price": btc_price,
            "state": sig["state"],
            "confidence": sig["confidence"],
            "lifecycle_state": sig.get("lifecycle_state", "ACTIVE"),
            "reasons": sig.get("reasons", []),
            "vetoes": sig.get("vetoes", []),
            "invalidation_conditions": sig.get("invalidation_conditions", []),
            "informational_zones": sig.get("informational_zones", []),
            "gates": sig.get("gates", {}),
        },
        "positioning": pos,
        "flow": flo,
        "catalyst": cat,
        "levels": lvl,
        "data_quality": dq,
    }


if __name__ == "__main__":
    # Read from stdin or file
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
    else:
        path = Path(__file__).parent.parent.parent / "packet" / "data.json"

    data = json.loads(path.read_text())
    result = run(data)
    print(json.dumps(result, indent=2, default=str))
