#!/usr/bin/env python3
"""
Liquidity Status Producer for Pipeline V3
Tracks 4 dimensions of "liquidity drying up" per GetClaw spec.
Reads AMT feed + Pipeline derivatives + ETF flow + market data.
Output: data/liquidity_status.json
"""
import sys
import os
import json
from datetime import datetime, timezone

SITE = "/home/maswilee/projects/pipeline-dashboard-v3"
OUTPUT_PATH = os.path.join(SITE, "data/liquidity_status.json")
AMT_FEED = "/tmp/amt_feed.json"
DERIVATIVES = os.path.join(SITE, "data/derivatives.json")
ETF_FLOW = "/tmp/btc_etf_flow.json"
MARKET_DATA = "/tmp/btc_market_data.json"

def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default

def main():
    now = datetime.now(timezone.utc)
    signals_dry = 0
    
    # ── 1. Taker Buy/Sell Ratio (from AMT feed) ──
    taker_buy_ratio = None
    taker_signal = "UNKNOWN"
    cvd_trend = "UNKNOWN"
    
    amt = read_json(AMT_FEED)
    if amt:
        tv = amt.get("taker_volume", {})
        ratio_24h = tv.get("ratio_24h")
        if ratio_24h is not None:
            # ratio_24h is buy/sell — convert to buy/(buy+sell)
            taker_buy_ratio = round(ratio_24h / (1 + ratio_24h), 3)
            
            if taker_buy_ratio < 0.38:
                taker_signal = "ABANDONMENT"
                signals_dry += 1
            elif taker_buy_ratio < 0.45:
                taker_signal = "WEAK"
            else:
                taker_signal = "NORMAL"
        
        # CVD trend from candle_delta
        cd = tv.get("candle_delta", [])
        if cd:
            session_cvd = sum(d.get("delta", 0) for d in cd)
            recent_deltas = [d.get("delta", 0) for d in cd[-4:]]
            if session_cvd < -500 and all(d < 0 for d in recent_deltas):
                cvd_trend = "NEGATIVE"
            elif session_cvd < -200:
                cvd_trend = "NEGATIVE"
            elif abs(session_cvd) < 200:
                cvd_trend = "FLAT"
            else:
                cvd_trend = "POSITIVE"

    # ── 2. Derivatives (Funding + OI from Pipeline) ──
    funding_rate = None
    funding_signal = "UNKNOWN"
    oi_delta = "UNKNOWN"
    oi_change_pct = None
    
    derivs = read_json(DERIVATIVES)
    if derivs:
        funding_rate = derivs.get("funding_rate")
        if funding_rate is not None:
            if funding_rate < -0.0003:
                funding_signal = "NEGATIVE"
                signals_dry += 1
            elif funding_rate > 0.0005:
                funding_signal = "POSITIVE"
            else:
                funding_signal = "NEUTRAL"
        
        # OI delta from history
        oi_hist = derivs.get("oi_history", [])
        if len(oi_hist) >= 2:
            latest_oi = oi_hist[-1].get("btc", 0)
            prev_oi = oi_hist[-3].get("btc", latest_oi) if len(oi_hist) >= 3 else oi_hist[0].get("btc", latest_oi)
            if prev_oi > 0:
                oi_change_pct = round((latest_oi - prev_oi) / prev_oi * 100, 2)
                if oi_change_pct < -0.5:
                    oi_delta = "DECLINING"
                    signals_dry += 1
                elif oi_change_pct > 0.5:
                    oi_delta = "EXPANDING"
                else:
                    oi_delta = "FLAT"

    # ── 3. ETF Flow ──
    etf_flow_usd = None
    etf_signal = "UNKNOWN"
    
    etf = read_json(ETF_FLOW)
    if etf:
        etf_flow_usd = etf.get("daily_flow_usd") or etf.get("total_flow")
        if etf_flow_usd is not None:
            if etf_flow_usd < -200_000_000:
                etf_signal = "OUTFLOW"
                signals_dry += 1
            elif etf_flow_usd < 0:
                etf_signal = "OUTFLOW"
            elif etf_flow_usd > 50_000_000:
                etf_signal = "INFLOW"
            else:
                etf_signal = "NEUTRAL"

    # ── 4. Coinbase Premium (from market data) ──
    coinbase_premium = None
    coinbase_signal = "UNKNOWN"
    
    mkt = read_json(MARKET_DATA)
    if mkt:
        coinbase_premium = mkt.get("coinbase_premium")
        if coinbase_premium is not None:
            if coinbase_premium < -0.5:
                coinbase_signal = "NEGATIVE"
                signals_dry += 1
            elif coinbase_premium < 0:
                coinbase_signal = "NEGATIVE"
            else:
                coinbase_signal = "POSITIVE"

    # ── 5. BTC Price ──
    btc_price = amt.get("btc_spot") if amt else None

    # ── Verdict ──
    signals_total = 4
    if signals_dry <= 1:
        verdict = "HEALTHY"
    elif signals_dry == 2:
        verdict = "THINNING"
    elif signals_dry == 3:
        verdict = "DRY"
    else:
        verdict = "EVAPORATING"
    
    # ── Tactical note ──
    tactical = ""
    if verdict == "EVAPORATING":
        tactical = "CRITICAL: All 4 liquidity signals dry. No natural stopping point between levels. $59K path open if $61,900 breaks with thin depth."
    elif verdict == "DRY":
        dry_layers = []
        if taker_signal == "ABANDONMENT": dry_layers.append("taker volume")
        if oi_delta == "DECLINING": dry_layers.append("OI")
        if etf_signal == "OUTFLOW": dry_layers.append("ETF flows")
        if coinbase_signal == "NEGATIVE": dry_layers.append("Coinbase premium")
        tactical = f"3/4 signals dry ({', '.join(dry_layers)}). Monitor closely — one more signal triggers EVAPORATING."
    elif verdict == "THINNING":
        tactical = "2/4 signals weakening. Liquidity thinning but not yet dangerous. Watch taker ratio and OI for acceleration."
    elif taker_buy_ratio and taker_buy_ratio < 0.40:
        tactical = "Taker buy ratio borderline. If sustained < 38% for 2+ hours, liquidity concern escalates."
    else:
        tactical = "All liquidity signals healthy. Normal market functioning."

    # ── Build payload ──
    payload = {
        "liquidity_verdict": verdict,
        "taker_buy_ratio": taker_buy_ratio,
        "taker_signal": taker_signal,
        "cvd_trend": cvd_trend,
        "oi_delta": oi_delta,
        "oi_change_pct": oi_change_pct,
        "funding_rate": funding_rate,
        "funding_signal": funding_signal,
        "etf_flow_usd": etf_flow_usd,
        "etf_signal": etf_signal,
        "coinbase_premium": coinbase_premium,
        "coinbase_signal": coinbase_signal,
        "signals_dry": signals_dry,
        "signals_total": signals_total,
        "tactical_note": tactical,
        "btc_price": btc_price,
        "timestamp": now.strftime("%Y-%m-%d %H:%M UTC"),
        "data_age_minutes": 0
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"[liquidity] Verdict: {verdict} ({signals_dry}/{signals_total} dry) | Taker {taker_buy_ratio} | OI {oi_delta} | ETF {etf_signal} | Coinbase {coinbase_signal}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
