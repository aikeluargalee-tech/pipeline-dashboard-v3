#!/usr/bin/env python3
"""Gate0 news collectors — GDELT-based signals for elon + quantum modules.

Why GDELT: free, no API key, indexes global news within minutes. Replaces the
old trading-workflow collectors (X scraping not viable; no other free source).

Design constraints (learned):
- GDELT rate limit: 1 request / 5 seconds — cache aggressively, query at most
  once per CACHE_TTL per topic, and never in parallel.
- Outputs: data/gate0_news.json (consumed by fetch_gate0_full.py).

Topics:
  quantum — "quantum computing" + (bitcoin | crypto | encryption | SHA-256)
            threat signal: news about quantum breaking crypto
  elon    — "Elon Musk" + (bitcoin | crypto | dogecoin | sell | buy)
            signal: Musk crypto commentary / Tesla BTC moves
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

SITE = os.path.expanduser("~/projects/pipeline-dashboard-v3")
OUT_FILE = os.path.join(SITE, "data", "gate0_news.json")
CACHE_TTL = 3600  # seconds — re-query at most hourly (GDELT rate limit + news cadence)
LAST_REQ_FILE = "/tmp/gdelt_last_request.txt"

QUANTUM_QUERY = '"quantum computing" (bitcoin OR crypto OR encryption OR "SHA-256")'
ELON_QUERY = '"Elon Musk" (bitcoin OR crypto OR dogecoin OR "sell bitcoin" OR "buy bitcoin")'


def _last_request_ts() -> float:
    try:
        return float(open(LAST_REQ_FILE).read().strip())
    except Exception:
        return 0.0


def _mark_request() -> None:
    with open(LAST_REQ_FILE, "w") as f:
        f.write(str(time.time()))


def gdelt_query(query: str, maxrecords: int = 8, timespan: str = "72h") -> list:
    """Query GDELT doc API. Returns list of articles. Respects 1-req/5s limit."""
    wait = 5.5 - (time.time() - _last_request_ts())
    if wait > 0:
        time.sleep(wait)
    params = urllib.parse.urlencode({
        "query": query, "mode": "artlist", "maxrecords": maxrecords,
        "format": "json", "timespan": timespan, "sort": "datedesc",
    })
    url = f"https://api.gdeltproject.org/api/v2/doc/doc?{params}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "pipeline-dashboard/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode())
        _mark_request()
        return data.get("articles", [])
    except Exception as e:
        _mark_request()
        return []


def _score_articles(articles: list, threat_terms: list) -> dict:
    """Score articles: count + severity by term matching in title/url."""
    hits = []
    severity = 0
    for a in articles:
        title = (a.get("title") or "") + " " + (a.get("url") or "")
        matched = [t for t in threat_terms if t.lower() in title.lower()]
        if matched:
            hits.append({"title": a.get("title", "")[:120], "url": a.get("url", ""),
                         "date": (a.get("seendate") or "")[:8], "terms": matched})
            severity += min(len(matched), 3)
    return {"count": len(hits), "severity": severity, "hits": hits[:5]}


def collect() -> dict:
    # Load prior cache — return it if fresh (avoids hammering GDELT)
    cache = {}
    if os.path.exists(OUT_FILE):
        try:
            cache = json.load(open(OUT_FILE))
        except Exception:
            cache = {}
    cache_ts = cache.get("_cached_at", 0)
    if isinstance(cache_ts, str):
        try:
            cache_ts = datetime.fromisoformat(cache_ts.replace("Z", "+00:00")).timestamp()
        except Exception:
            cache_ts = 0
    if time.time() - float(cache_ts) < CACHE_TTL:
        return cache

    now_iso = datetime.now(timezone.utc).isoformat()

    # Quantum threat — severity by breaking-crypto terms
    q_arts = gdelt_query(QUANTUM_QUERY)
    q = _score_articles(q_arts, ["break", "crack", "threat", "shor", "attack", "NSA", "decrypt"])

    # Elon — severity by market-moving terms
    e_arts = gdelt_query(ELON_QUERY)
    e = _score_articles(e_arts, ["sell", "buy", "dump", "pump", "tesla", "accept", "reject", "prohibit"])

    out = {
        "_cached_at": now_iso,
        "quantum": {"state": "ELEVATED" if q["severity"] >= 3 else
                            "WATCH" if q["count"] > 0 else "CLEAR",
                    "article_count": q["count"], "severity": q["severity"],
                    "articles": q["hits"]},
        "elon": {"state": "ELEVATED" if e["severity"] >= 3 else
                         "WATCH" if e["count"] > 0 else "CLEAR",
                 "article_count": e["count"], "severity": e["severity"],
                 "articles": e["hits"]},
    }
    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w") as f:
        json.dump(out, f, indent=2)
    return out


if __name__ == "__main__":
    res = collect()
    print(f"gate0_news: quantum={res['quantum']['state']} ({res['quantum']['article_count']} arts) "
          f"elon={res['elon']['state']} ({res['elon']['article_count']} arts)")
    sys.exit(0)
