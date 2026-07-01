#!/usr/bin/env python3
"""
Liquidity Status Producer for Pipeline V3 — per GetClaw spec.
Tracks 4 layers of "liquidity drying up":
  1. Order Book Depth (Coinbase Premium proxy)
  2. Taker Volume (buy ratio + CVD)
  3. Stablecoin/ETF Flows (Glassnode → fallback UNKNOWN)
  4. Derivatives (Funding rate + OI delta)

Sources: AMT feed, Coinbase/Binance APIs, Glassnode MCP (best-effort)
Output: data/liquidity_status.json
"""
import sys
import os
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone

SITE = "/home/maswilee/projects/pipeline-dashboard-v3"
OUTPUT_PATH = os.path.join(SITE, "data/liquidity_status.json")
AMT_FEED = "/tmp/amt_feed.json"

def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default

def http_get(url, timeout=8):
    """Fetch JSON from URL, return dict or None."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PipelineV3/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None

def get_coinbase_premium():
    """Compute Coinbase-Binance spot premium (%). Positive = US institutional bid."""
    cb = http_get("https://api.coinbase.com/v2/prices/BTC-USD/spot")
    bn = http_get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT")
    if cb and bn:
        try:
            cb_price = float(cb["data"]["amount"])
            bn_price = float(bn["price"])
            premium_pct = round((cb_price - bn_price) / bn_price * 100, 4)
            return premium_pct, cb_price
        except (KeyError, ValueError, ZeroDivisionError):
            pass
    return None, None

def get_etf_flows():
    """Read local ETF flow cache produced by fetch_etf_flow.py, with Glassnode MCP fallback."""
    # 1. Try reading the local collector cache first (highly reliable, scrapes Farside/news)
    cache_path = "/tmp/btc_etf_flow.json"
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r") as f:
                data = json.load(f)
            flows = data.get("flows", [])
            if flows:
                # Find the latest non-zero flow (on weekends, the absolute latest entry is 0.0,
                # so we scan backwards to find the last active trading day's net flow).
                target_flow = None
                for entry in reversed(flows):
                    val = float(entry.get("total", 0.0))
                    if val != 0.0:
                        target_flow = val
                        break
                if target_flow is None and flows:
                    target_flow = float(flows[-1].get("total", 0.0))
                
                if target_flow is not None:
                    # Convert from Millions of USD to raw USD
                    return int(target_flow * 1_000_000)
        except Exception as e:
            print(f"Error parsing local ETF flow cache: {e}")

    # 2. Fallback to Glassnode MCP tool if cache is missing
    try:
        # Try Glassnode style MCP call
        import asyncio
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        async def _fetch():
            async with streamablehttp_client('http://localhost:8001/mcp') as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    balance_tool = None
                    for t in tools.tools:
                        if 'balance' in t.name.lower() and 'issuer' in t.name.lower():
                            balance_tool = t.name
                            break
                    if not balance_tool:
                        return None
                    
                    # Fetch IBIT + FBTC + GBTC balances
                    issuers = ['IBIT', 'FBTC', 'GBTC']
                    total_current = 0
                    total_1d_ago = 0
                    for ticker in issuers:
                        try:
                            result = await session.call_tool(balance_tool, {"ticker": ticker})
                            # Result structure varies by Glassnode MCP version
                            content = result.content[0].text if result.content else ""
                            data = json.loads(content) if content else {}
                            total_current += data.get("balance", 0) or data.get("current_balance", 0) or 0
                            total_1d_ago += data.get("balance_1d_ago", 0) or data.get("previous_balance", 0) or 0
                        except Exception:
                            pass
                    
                    if total_current > 0 and total_1d_ago > 0:
                        return round(total_current - total_1d_ago)
                    return None

        return asyncio.run(_fetch())
    except Exception:
        return None

def main():
    now = datetime.now(timezone.utc)
    signals_dry = 0

    amt = read_json(AMT_FEED)
    btc_price = amt.get("btc_spot") if amt else None

    # ═══════ LAYER 1: Taker Volume ═══════
    taker_buy_ratio = None
    taker_signal = "UNKNOWN"
    cvd_trend = "UNKNOWN"

    if amt:
        tv = amt.get("taker_volume", {})
        ratio_24h = tv.get("ratio_24h")
        if ratio_24h is not None:
            taker_buy_ratio = round(ratio_24h / (1 + ratio_24h), 3)
            if taker_buy_ratio < 0.38:
                taker_signal = "ABANDONMENT"
                signals_dry += 1
            elif taker_buy_ratio < 0.45:
                taker_signal = "WEAK"
            else:
                taker_signal = "NORMAL"

        # CVD trend from candle_delta (session cumulative)
        cd = tv.get("candle_delta", [])
        if cd:
            session_cvd = sum(d.get("delta", 0) for d in cd)
            recent_3 = [d.get("delta", 0) for d in cd[-3:]]
            if session_cvd < -1000 and all(d < 0 for d in recent_3):
                cvd_trend = "NEGATIVE"
            elif session_cvd < -300:
                cvd_trend = "NEGATIVE"
            elif abs(session_cvd) < 300:
                cvd_trend = "FLAT"
            else:
                cvd_trend = "POSITIVE"

    # ═══════ LAYER 2: Derivatives (Funding + OI) ═══════
    funding_rate = None
    funding_signal = "UNKNOWN"
    oi_delta = "UNKNOWN"
    oi_change_pct = None

    if amt:
        f = amt.get("funding", {})
        funding_rate = f.get("rate")
        if funding_rate is not None:
            if funding_rate < -0.00003:
                funding_signal = "NEGATIVE"
            elif funding_rate > 0.00005:
                funding_signal = "POSITIVE"
            else:
                funding_signal = "NEUTRAL"

        oi_change_pct = f.get("oi_change_24h", 0) or 0
        if oi_change_pct < -0.5:
            oi_delta = "DECLINING"
            signals_dry += 1
        elif oi_change_pct > 0.5:
            oi_delta = "EXPANDING"
        else:
            oi_delta = "FLAT"

    # ═══════ LAYER 3: ETF Flows ═══════
    etf_flow_usd = None
    etf_signal = "UNKNOWN"

    etf_flow_raw = get_etf_flows()
    if etf_flow_raw is not None:
        etf_flow_usd = etf_flow_raw
        if etf_flow_usd < -200_000_000:
            etf_signal = "OUTFLOW"
            signals_dry += 1
        elif etf_flow_usd < 0:
            etf_signal = "OUTFLOW"
        elif etf_flow_usd > 50_000_000:
            etf_signal = "INFLOW"
        else:
            etf_signal = "NEUTRAL"

    # ═══════ LAYER 4: Coinbase Premium ═══════
    coinbase_premium = None
    coinbase_signal = "UNKNOWN"
    coinbase_spot = None

    premium_pct, cb_spot = get_coinbase_premium()
    coinbase_spot = cb_spot
    if premium_pct is not None:
        coinbase_premium = premium_pct
        if premium_pct < -1.0:
            coinbase_signal = "NEGATIVE"
            signals_dry += 1
        elif premium_pct < -0.1:
            coinbase_signal = "NEGATIVE"
        elif premium_pct > 0.3:
            coinbase_signal = "POSITIVE"
        else:
            coinbase_signal = "NEUTRAL"

    # ═══════ VERDICT ═══════
    signals_total = 4
    if signals_dry <= 1:
        verdict = "HEALTHY"
    elif signals_dry == 2:
        verdict = "THINNING"
    elif signals_dry == 3:
        verdict = "DRY"
    else:
        verdict = "EVAPORATING"

    # ═══════ TACTICAL NOTE ═══════
    if verdict == "EVAPORATING":
        tactical = ("CRITICAL: All 4 liquidity signals dry. "
                    "No natural stopping point between levels. "
                    "$59K path open if $61,900 breaks with thin depth.")
    elif verdict == "DRY":
        dry_layers = []
        if taker_signal == "ABANDONMENT": dry_layers.append("taker volume")
        if oi_delta == "DECLINING": dry_layers.append("OI")
        if etf_signal == "OUTFLOW": dry_layers.append("ETF flows")
        if coinbase_signal == "NEGATIVE": dry_layers.append("Coinbase premium")
        tactical = f"3/4 signals dry ({', '.join(dry_layers)}). Monitor — one more triggers EVAPORATING."
    elif verdict == "THINNING":
        tactical = "2/4 signals weakening. Liquidity thinning — watch taker ratio and OI for acceleration."
    elif taker_buy_ratio and taker_buy_ratio < 0.40:
        tactical = "Taker buy ratio borderline. If sustained < 38% for 2+ hours, concern escalates."
    else:
        tactical = "All liquidity signals healthy. Normal market functioning."

    # ═══════ BUILD PAYLOAD ═══════
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
        "coinbase_spot": coinbase_spot,
        "timestamp": now.strftime("%Y-%m-%d %H:%M UTC"),
        "data_age_minutes": 0
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(payload, f, indent=2)

    status_line = (f"[liquidity] Verdict: {verdict} ({signals_dry}/{signals_total} dry) | "
                   f"Taker {taker_buy_ratio} ({taker_signal}) | CVD {cvd_trend} | "
                   f"OI {oi_delta} | ETF {etf_signal} | CB {coinbase_signal}")
    print(status_line)
    return 0

if __name__ == "__main__":
    sys.exit(main())
