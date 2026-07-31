#!/usr/bin/env python3
"""Batch SEO metadata injector for Pipeline Dashboard V3 subpages."""
import os, re

BASE = "/home/susiwilee/projects/pipeline-dashboard-v3"
DOMAIN = "https://aikeluargalee-tech.github.io/pipeline-dashboard-v3"

PAGES = {
    "pfc3l": {
        "title": "PFC-3L Signal Intelligence — Positioning, Flow, Catalyst & Levels | Pipeline Dashboard",
        "desc": "Deterministic BTC signal intelligence combining Positioning, Flow, Catalyst and Psychological Levels into a six-state decision engine. Updated every 15 minutes. No LLM control — all rules are Python.",
    },
    "aegis": {
        "title": "BTC AEGIS — Trap Avoidance & Systemic Risk Control Centre | Pipeline Dashboard",
        "desc": "Real-time BTC trap detection with S1-S8 signals, crash precursor monitoring, breakout validation, and evidence ledger. Avoid market traps before they execute. Updated every 15 minutes.",
    },
    "ai-factors": {
        "title": "AI Factors Monitor — VIX, US10Y & Volume Anomaly BTC Signals | Pipeline Dashboard",
        "desc": "Live AI-to-BTC transmission channel monitoring. VIX rate-of-change, US10Y yield deviation, and volume anomaly detection. See what macro factors are signalling for Bitcoin in real time.",
    },
    "psychological-levels": {
        "title": "BTC Psychological Levels — Live Cost-Basis & Round-Number Support/Resistance Map | Pipeline Dashboard",
        "desc": "Interactive map of Bitcoin psychological price levels — round numbers, cost-basis zones, and sentiment anchors that drive trader behavior. Updated every 15 minutes.",
    },
    "regime-compass": {
        "title": "BTC Market Regime Compass — RORO × BTC Rotation Map | Pipeline Dashboard",
        "desc": "Live risk-on/risk-off rotation map for Bitcoin. See which macro regime BTC is trading in — accumulation, distribution, risk-on rally, or risk-off breakdown. Updated every 15 minutes.",
    },
    "volume-profile": {
        "title": "Volume Profile V3.1 Sentinel — BTC Market Structure & Auction Zones | Pipeline Dashboard",
        "desc": "Real-time Bitcoin Volume Profile showing POC, VAL, VAH, and HVN zones. Market auction structure analysis — where institutions are accumulating and distributing. Updated every 15 minutes.",
    },
    "whale-wake": {
        "title": "Whale Wake — BTC Large-Order Footprint & CVD Divergence | Pipeline Dashboard",
        "desc": "Detect large-order BTC footprints before price moves. CVD divergence, absorption patterns, and whale activity tracker. See what big money is doing in real time.",
    },
    "market-regime": {
        "title": "BTC Market Regime Detector — Causal K-Means Classification | Pipeline Dashboard",
        "desc": "Machine-learning market regime classification for Bitcoin. K-means clustering identifies trend, momentum, and volatility regimes to contextualize trading decisions. Updated every 15 minutes.",
    },
    "packet": {
        "title": "BTC Data Packet — Live Trading Signals & Multi-Layer Gating | Pipeline Dashboard",
        "desc": "Raw pipeline metrics and enriched signal fields for Bitcoin. Full data packet with Gate0 risk parameters, liquidation magnets, derivatives positioning, and on-chain cycle metrics.",
    },
    "analysis": {
        "title": "BTC Live Analysis — Technicals, On-Chain & Derivatives Verdict | Pipeline Dashboard",
        "desc": "Live Bitcoin technical analysis combining on-chain metrics, derivatives positioning, and macro correlations into a single actionable verdict. Updated every 15 minutes.",
    },
}

SCHEMA_TEMPLATE = """  <!-- Schema.org -->
  <script type="application/ld+json">
  {
    "@context": "https://schema.org",
    "@type": "WebPage",
    "name": "%s",
    "description": "%s",
    "url": "%s",
    "isPartOf": {
      "@type": "WebSite",
      "name": "BTC Pipeline Dashboard",
      "url": "%s/"
    }
  }
  </script>
"""

BREADCRUMB_TEMPLATE = """  <!-- BreadcrumbList -->
  <script type="application/ld+json">
  {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    "itemListElement": [
      {"@type": "ListItem", "position": 1, "name": "Home", "item": "%s/"},
      {"@type": "ListItem", "position": 2, "name": "%s", "item": "%s"}
    ]
  }
  </script>
"""


def inject_seo(html_path: str, page_slug: str, config: dict):
    with open(html_path) as f:
        html = f.read()

    title = config["title"]
    desc = config["desc"]
    url = f"{DOMAIN}/{page_slug}/"
    name = title.split(" — ")[0] if " — " in title else title.split(" | ")[0]
    title_clean = name.strip()

    # Replace or add title
    if "<title>" in html:
        html = re.sub(r"<title>[^<]*</title>", f"<title>{title}</title>", html)
    else:
        html = html.replace("</head>", f"  <title>{title}</title>\n</head>")

    # Replace or add meta description
    if '<meta name="description"' in html:
        html = re.sub(
            r'<meta name="description"[^>]*>',
            f'<meta name="description" content="{desc}">',
            html,
        )
    else:
        # Insert after title or after charset
        insert_after = "<title>" if "<title>" in html else '<meta charset="UTF-8">'
        idx = html.find(insert_after)
        if idx > 0:
            end = html.find("\n", idx)
            html = html[: end + 1] + f'<meta name="description" content="{desc}">\n' + html[end + 1 :]

    # Replace or add canonical URL
    if '<link rel="canonical"' in html:
        html = re.sub(
            r'<link rel="canonical"[^>]*>',
            f'<link rel="canonical" href="{url}">',
            html,
        )
    else:
        html = html.replace("</head>", f'  <link rel="canonical" href="{url}">\n</head>')

    # Add Schema.org WebPage if missing
    if '"@type": "WebPage"' not in html:
        schema = SCHEMA_TEMPLATE % (title_clean, desc, url, DOMAIN)
        html = html.replace("</head>", schema + "\n</head>")

    # Add BreadcrumbList if missing
    if '"@type": "BreadcrumbList"' not in html:
        breadcrumb = BREADCRUMB_TEMPLATE % (DOMAIN, name, url)
        html = html.replace("</head>", breadcrumb + "\n</head>")

    # Remove any remaining no-cache/pragma/expires (double-check)
    html = re.sub(r'<meta http-equiv="Cache-Control"[^>]*>\n?', "", html)
    html = re.sub(r'<meta http-equiv="Pragma"[^>]*>\n?', "", html)
    html = re.sub(r'<meta http-equiv="Expires"[^>]*>\n?', "", html)

    with open(html_path, "w") as f:
        f.write(html)

    return f"✅ {page_slug}"


def main():
    for slug, config in PAGES.items():
        path = os.path.join(BASE, slug, "index.html")
        if os.path.exists(path):
            result = inject_seo(path, slug, config)
            print(result)
        else:
            print(f"⚠️  {slug}/index.html not found")


if __name__ == "__main__":
    main()
