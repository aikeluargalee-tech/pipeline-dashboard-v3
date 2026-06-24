#!/usr/bin/env python3
"""
Cross-Asset Macro Signal Playbook v1.0 — per GetClaw spec (June 24, 2026).
Activated when DISTRIBUTION or RISK_OFF regime detected.

Bias: SHORT only. This is the macro defense playbook.
Timeframe: 4H primary.
Macro inputs: DXY, VIX, SPY, Gold, US10Y.

Output: data/playbook_cross_asset_macro.json
"""
import sys, os, json
from datetime import datetime, timezone
from pathlib import Path
import urllib.request

PLAYBOOK_DIR = Path(__file__).parent
SITE = Path("/home/maswilee/projects/pipeline-dashboard-v3")
DATA_DIR = SITE / "data"
sys.path.insert(0, str(SITE / "playbooks"))

from regime_gate import get_regime, get_liquidity


def load_json(path):
    if not os.path.exists(str(path)):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def load_config():
    return load_json(PLAYBOOK_DIR / "config.json")


def load_macro():
    return load_json(DATA_DIR / "macro.json")


def load_amt():
    return load_json("/tmp/amt_feed.json")


def load_gate0():
    return load_json(DATA_DIR / "gate0.json")


def fetch_klines(symbol="BTCUSDT", interval="4h", limit=50):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        return {
            "close": [float(c[4]) for c in data],
            "high":  [float(c[2]) for c in data],
            "low":   [float(c[3]) for c in data],
            "open":  [float(c[1]) for c in data],
        }
    except Exception as e:
        print(f"[cross_asset] klines fetch failed: {e}")
        return None


def calc_rsi(closes, period=14):
    n = len(closes)
    if n < period + 1:
        return [None] * n
    deltas = [closes[i] - closes[i-1] for i in range(1, n)]
    gains = [max(d, 0) for d in deltas]
    losses = [max(-d, 0) for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    rsi = [None] * n
    if avg_loss == 0:
        rsi[period] = 100.0
    else:
        rsi[period] = 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))
    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i-1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i-1]) / period
        if avg_loss == 0:
            rsi[i] = 100.0
        else:
            rsi[i] = 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))
    return rsi


def rolling_mean(values, window=20):
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


# ═══════════════════════════════════════
# MACRO SCORING
# ═══════════════════════════════════════

def compute_macro_score(macro, cfg):
    """Score macro backdrop 0-10. Each signal confirming risk-off = +1."""
    if not macro:
        return 0, {}

    score = 0
    details = {}
    ms = cfg["macro_scoring"]

    # DXY
    dxy = macro.get("dxy", 100)
    if dxy > 105:
        score += 1
        details["dxy_strong"] = f"DXY {dxy:.1f} > 105"

    # VIX
    vix = macro.get("vix", 20)
    if vix > ms["vix"]["level_above_20"]:
        score += 1
        details["vix_elevated"] = f"VIX {vix:.1f} > 20"

    # SPY
    ra = macro.get("risk_assets", {})
    spy = ra.get("SPY", {})
    spy_chg = spy.get("change_pct", 0)
    if spy_chg < -ms["spy"]["change_1d_down"] * 100:
        score += 1
        details["spy_down"] = f"SPY {spy_chg:.1f}%"

    qqq = ra.get("QQQ", {})
    qqq_chg = qqq.get("change_pct", 0)
    if qqq_chg < -1:
        score += 1
        details["qqq_down"] = f"QQQ {qqq_chg:.1f}%"

    # Gold (GLD proxy)
    gld = ra.get("GLD", {})
    gld_chg = gld.get("change_pct", 0)
    if gld_chg > ms["gold"]["change_1d_up"] * 100:
        score += 1
        details["gold_bid"] = f"GLD +{gld_chg:.1f}%"

    # 10Y yield
    y10 = macro.get("us_10y_yield", 4.5)
    if y10 > 4.8:
        score += 1
        details["yields_high"] = f"10Y {y10:.2f}%"
    elif y10 < 4.0:
        score += 1
        details["yields_low"] = f"10Y {y10:.2f}% (recession fear)"

    # ETF flow
    etf = macro.get("etf_flow", {})
    daily = etf.get("daily_net", 0)
    if daily < -50:
        score += 1
        details["etf_outflow"] = f"ETF -${abs(daily)}M"

    return score, details


# ═══════════════════════════════════════
# ENTRY CHECK
# ═══════════════════════════════════════

def check_short_entry(mode, cfg, price, rsi_val, amt, liq, gate0, regime_signals):
    rules = cfg["entry"]["short"][mode]
    checks = {}

    # Price vs 20h high
    pv = regime_signals.get("price_vs_20h_high")
    checks["price_vs_20h_high"] = pv is not None and pv <= rules["price_vs_20h_high_max"]

    # RSI
    checks["rsi"] = rsi_val is not None and rsi_val < rules["rsi_max"]

    # Taker
    taker = None
    if amt:
        tv = amt.get("taker_volume", {})
        r = tv.get("ratio_24h")
        if r is not None:
            taker = r / (1 + r)
    checks["taker"] = taker is not None and taker < rules["taker_ratio_max"]

    # OI delta
    oi = amt.get("funding", {}).get("oi_change_1h") if amt else 0
    oi_label = "EXPANDING" if oi > 2 else ("DECLINING" if oi < -2 else "FLAT")
    checks["oi_delta"] = oi_label in rules["oi_delta_allowed"]

    # Funding
    funding = amt.get("funding", {}).get("rate") if amt else 0
    req = rules["funding_required"]
    if req == "neutral_or_positive":
        checks["funding"] = funding >= -0.0001
    elif req == "positive":
        checks["funding"] = funding > 0
    else:
        checks["funding"] = True

    # Liquidity
    liq_v = liq.get("liquidity_verdict", "UNKNOWN") if liq else "UNKNOWN"
    if "liquidity_disallowed" in rules:
        checks["liquidity"] = liq_v not in rules["liquidity_disallowed"]
    else:
        checks["liquidity"] = liq_v in rules.get("liquidity_allowed", ["HEALTHY"])

    # Black Swan
    bs_clear = True
    if gate0:
        bs_mod = gate0.get("modules", {}).get("black_swan", {})
        bs_det = bs_mod.get("detail", "")
        if "score:" in bs_det:
            try:
                s = int(bs_det.split("score:")[1].split("/")[0])
                bs_clear = s <= rules["black_swan_max"]
            except:
                pass
    checks["black_swan"] = bs_clear

    passed = all(checks.values())
    return passed, checks


# ═══════════════════════════════════════
# INVALIDATION
# ═══════════════════════════════════════

def check_invalidation(regime_data, amt, liq, macro, cfg, macro_score):
    triggers = []
    inv = cfg["invalidation"]

    # 1. Regime flip
    if regime_data.get("regime") not in ["DISTRIBUTION", "RISK_OFF"]:
        triggers.append(f"regime_flip: {regime_data.get('regime')}")

    # 2. Macro score collapse
    if macro_score <= inv["macro_score_collapse"]:
        triggers.append(f"macro_score_collapse: {macro_score}")

    # 3. VIX reversal
    vix = macro.get("vix", 20) if macro else 20
    if vix < inv["vix_reversal_below"]:
        triggers.append(f"vix_reversal: {vix}")

    # 4. SPY recovery
    ra = macro.get("risk_assets", {}) if macro else {}
    spy = ra.get("SPY", {})
    spy_chg = spy.get("change_pct", 0)
    if spy_chg > inv["spy_recovery_pct"] * 100:
        triggers.append(f"spy_recovery: +{spy_chg:.1f}%")

    # 5. Liquidity collapse
    liq_v = liq.get("liquidity_verdict", "UNKNOWN") if liq else "UNKNOWN"
    if liq_v in inv["liquidity_kill"]:
        triggers.append(f"liquidity_evaporating")

    return triggers


# ═══════════════════════════════════════
# SIZING
# ═══════════════════════════════════════

def compute_size(mode, phase, cfg):
    base = cfg["sizing"]["base_risk_pct"][mode]
    ps = cfg["sizing"]["phase_scalar"].get(phase, 0.75)
    return min(round(base * ps, 2), cfg["sizing"]["hard_cap_pct"])


# ═══════════════════════════════════════
# MAIN
# ═══════════════════════════════════════

def main():
    now = datetime.now(timezone.utc)
    cfg = load_config()
    if not cfg:
        print("[cross_asset] config missing")
        return 1

    regime = get_regime()
    if not regime:
        write_output({"status": "offline", "reason": "No regime data", "timestamp": now.isoformat()})
        return 0

    detected = regime.get("regime", "UNCERTAIN")

    if detected not in cfg["activation"]["regimes"]:
        write_output({
            "status": "idle",
            "reason": f"Regime is {detected} — not DISTRIBUTION/RISK_OFF",
            "timestamp": now.isoformat(),
            "btc_price": regime.get("btc_price"),
        })
        print(f"[cross_asset] Idle — regime is {detected}")
        return 0

    # ── ACTIVE ──
    phase = "ACUTE" if detected == "RISK_OFF" else "EARLY"
    macro = load_macro()
    macro_score, macro_details = compute_macro_score(macro, cfg)

    # Mode selection
    mode = None
    if phase == "ACUTE" and macro_score >= cfg["modes"]["SEVERE"]["macro_score_min"]:
        mode = "SEVERE"
    elif macro_score >= cfg["modes"]["ELEVATED"]["macro_score_min"]:
        mode = "ELEVATED"
    elif phase == "EARLY" and macro_score >= cfg["modes"]["CAUTIOUS"]["macro_score_min"]:
        mode = "CAUTIOUS"

    if not mode:
        result = {
            "status": "idle",
            "reason": f"Regime {detected} but macro score {macro_score} below minimum",
            "macro_score": macro_score,
            "macro_details": macro_details,
            "timestamp": now.isoformat(),
            "btc_price": regime.get("btc_price"),
        }
        write_output(result)
        print(f"[cross_asset] {detected} but macro score {macro_score} insufficient")
        return 0

    # Load market data
    amt = load_amt()
    liq = get_liquidity()
    gate0 = load_gate0()
    klines = fetch_klines()

    if not klines or len(klines["close"]) < 20:
        write_output({"status": "offline", "reason": "Klines unavailable", "timestamp": now.isoformat()})
        return 0

    price = klines["close"][-1]
    rsi_vals = calc_rsi(klines["close"])
    rsi_val = rsi_vals[-1] if rsi_vals and rsi_vals[-1] is not None else None
    mean_20_4h = rolling_mean(klines["close"], 20)

    regime_signals = {"price_vs_20h_high": regime.get("price_vs_20h_high")}

    # Entry check
    passed, checks = check_short_entry(mode, cfg, price, rsi_val, amt, liq, gate0, regime_signals)

    # Stops
    atr_norm = regime.get("atr_normalized", 1.85) if isinstance(regime.get("atr_normalized"), (int, float)) else 1.85
    atr_price = price * (atr_norm / 100)
    stop_mult = cfg["stops"][mode]["atr_mult"]
    stop_distance = stop_mult * atr_price

    high_20h = amt.get("high_24h") if amt else None
    hard_stop = max(price + stop_distance, high_20h * cfg["stops"]["structural_guard_mult"]) if high_20h else price + stop_distance

    # R:R
    rr = None
    if passed and mean_20_4h:
        reward = price - mean_20_4h
        risk = hard_stop - price
        rr = round(reward / risk, 2) if risk > 0 else 0
        if rr < cfg["take_profit"]["rr_min"][mode]:
            passed = False
            checks["rr_check"] = f"FAIL: {rr} < {cfg['take_profit']['rr_min'][mode]}"

    signal = "SHORT" if passed else "NO_SIGNAL"

    # Invalidation
    inval_triggers = []
    if signal != "NO_SIGNAL":
        inval_triggers = check_invalidation(regime, amt, liq, macro, cfg, macro_score)
        if inval_triggers:
            signal = "NO_SIGNAL"

    # TP
    tp1 = round(price - cfg["take_profit"]["tier1_atr_mult"] * atr_price, 2) if signal != "NO_SIGNAL" else None
    tp2 = round(mean_20_4h, 2) if signal != "NO_SIGNAL" and mean_20_4h else None

    # Size
    pos_size = compute_size(mode, phase, cfg)

    # Time
    max_hold = cfg["time_limits"][f"{mode}_max_hold_hours"]

    result = {
        "strategy": cfg["strategy"],
        "version": cfg["version"],
        "status": "active",
        "mode": mode,
        "phase": phase,
        "signal": signal,
        "timestamp": now.isoformat(),
        "btc_price": round(price, 2),
        "macro_score": macro_score,
        "macro_details": macro_details,
        "atr_pct": round(atr_norm, 2),
        "rsi_14_4h": round(rsi_val, 1) if rsi_val else None,
        "mean_20_4h": round(mean_20_4h, 2) if mean_20_4h else None,
        "position_size_pct": pos_size,
        "max_hold_hours": max_hold,
        "stop_distance_usd": round(stop_distance, 2),
        "entry_price": round(price, 2) if signal != "NO_SIGNAL" else None,
        "stop_loss": round(hard_stop, 2) if signal != "NO_SIGNAL" else None,
        "tp1": tp1,
        "tp2": tp2,
        "tp1_pct": cfg["take_profit"]["tier1_pct"],
        "tp2_pct": cfg["take_profit"]["tier2_pct"],
        "rr_ratio": rr,
        "checks": checks,
        "invalidation_triggers": inval_triggers,
        "regime": detected,
        "rescore_interval_hours": cfg["time_limits"]["rescore_interval_hours"],
    }
    write_output(result)

    print(f"[cross_asset] {mode} | {phase} | Signal: {signal} | Score: {macro_score}/10 | Price: ${price:,.0f}")
    if signal != "NO_SIGNAL":
        print(f"[cross_asset] SHORT: entry ${price:,.0f} | stop ${hard_stop:,.0f} | TP1 ${tp1:,.0f} | TP2 ${tp2:,.0f} | R:R {rr}")
        print(f"[cross_asset] Macro: {macro_details}")
    else:
        fails = [k for k, v in checks.items() if v is False or (isinstance(v, str) and 'FAIL' in v)]
        print(f"[cross_asset] No signal — failing: {fails[:4]}")
    print(f"[cross_asset] Written to data/playbook_cross_asset_macro.json")
    return 0


def write_output(data):
    DATA_DIR.mkdir(exist_ok=True)
    out = DATA_DIR / "playbook_cross_asset_macro.json"
    tmp = out.with_name(f".{out.name}.tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, out)


if __name__ == "__main__":
    sys.exit(main())
