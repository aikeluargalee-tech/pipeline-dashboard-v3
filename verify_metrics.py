import json
import ccxt
import urllib.request
import re
import math
from datetime import datetime, timezone

def fetch_yahoo_price(symbol):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        result = data["chart"]["result"][0]
        meta = result.get("meta", {})
        price = meta.get("regularMarketPrice")
        prev_close = meta.get("chartPreviousClose") or meta.get("previousClose")
        change_pct = None
        if price and prev_close and prev_close > 0:
            change_pct = (price - prev_close) / prev_close * 100
        return {"price": price, "change_pct": change_pct}
    except Exception as e:
        return {"price": None, "change_pct": None, "error": str(e)}

def fetch_vix():
    return fetch_yahoo_price("%5EVIX")

def fetch_dxy():
    return fetch_yahoo_price("DX-Y.NYB")

def main():
    print("Fetching live data...")
    print("=" * 60)

    # 3. Coinbase Premium
    try:
        cb = ccxt.coinbase()
        bn = ccxt.binance()
        cb_ticker = cb.fetch_ticker('BTC/USD')
        bn_ticker = bn.fetch_ticker('BTC/USDT')
        cb_price = cb_ticker['last']
        bn_price = bn_ticker['last']
        coinbase_premium = (cb_price - bn_price) / bn_price * 100
        print(f"Coinbase price: {cb_price}, Binance price: {bn_price}, Coinbase Premium: {coinbase_premium:.4f}%")
    except Exception as e:
        print("Coinbase Premium Error:", e)

    # 4. DXY
    dxy = fetch_dxy()
    print(f"DXY: {dxy}")

    # 5. VIX
    vix = fetch_vix()
    print(f"VIX: {vix}")

    # 6. Funding Rate
    try:
        exchange = ccxt.binanceusdm()
        mark = exchange.fetch_mark_price('BTC/USDT')
        funding_rate = mark.get('lastFundingRate')
        if isinstance(funding_rate, str):
            funding_rate = float(funding_rate)
        print(f"Binance USD-M Funding Rate: {funding_rate} ({funding_rate*100:.6f}%)")
    except Exception as e:
        print("Funding Rate Error:", e)

    # 7. OI Change 24h
    try:
        exchange = ccxt.binanceusdm()
        oi_hist = exchange.fetch_open_interest_history('BTC/USDT', '1h', limit=24)
        if oi_hist:
            oi_values = []
            for entry in oi_hist:
                if isinstance(entry, dict):
                    val = entry.get('openInterestValue', 0) or 0
                elif isinstance(entry, list):
                    val = entry[4] if len(entry) > 4 else 0
                else:
                    val = 0
                oi_values.append(float(val))
            first_oi = oi_values[0]
            last_oi = oi_values[-1]
            oi_change = (last_oi - first_oi) / first_oi * 100 if first_oi else 0
            print(f"OI 24h change: {oi_change:.4f}% (First: {first_oi}, Last: {last_oi})")
    except Exception as e:
        print("OI Change Error:", e)

    # 8. L/S Ratio
    try:
        r = urllib.request.urlopen("https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol=BTCUSDT&period=1h&limit=1", timeout=10)
        ls = json.loads(r.read())
        if ls:
            print("Binance L/S Ratio:", ls[0].get("longShortRatio"))
    except Exception as e:
        print("L/S Ratio Error:", e)

    # 9. CVD 24h
    try:
        r = urllib.request.urlopen("https://fapi.binance.com/futures/data/takerlongshortRatio?symbol=BTCUSDT&period=1h&limit=24", timeout=10)
        data = json.loads(r.read())
        if data:
            cvd = 0
            for candle in data:
                buy_vol = float(candle.get("buyVol", 0))
                sell_vol = float(candle.get("sellVol", 0))
                cvd += (buy_vol - sell_vol)
            print(f"CVD 24h: {cvd:.2f} BTC")
    except Exception as e:
        print("CVD Error:", e)

    # 10. Equities
    for symbol in ["SPY", "QQQ", "GLD"]:
        res = fetch_yahoo_price(symbol)
        chg = res['change_pct']
        chg_str = f"{chg:.4f}%" if chg is not None else "None"
        print(f"{symbol}: Price={res['price']}, Change={chg_str}")

    # 11. Perp Basis Pct
    try:
        perp = ccxt.binanceusdm()
        spot = ccxt.binance()
        perp_ticker = perp.fetch_ticker('BTC/USDT')
        spot_ticker = spot.fetch_ticker('BTC/USDT')
        perp_basis = (perp_ticker['last'] - spot_ticker['last']) / spot_ticker['last'] * 100
        print(f"Perp: {perp_ticker['last']}, Spot: {spot_ticker['last']}, Basis: {perp_basis:.4f}%")
    except Exception as e:
        print("Perp Basis Error:", e)

    # 12. Fear & Greed
    try:
        import requests
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        data = r.json()
        print("Fear & Greed:", data["data"][0]["value"])
    except Exception as e:
        print("FNG Error:", e)

if __name__ == "__main__":
    main()
