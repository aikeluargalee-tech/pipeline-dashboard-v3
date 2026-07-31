#!/usr/bin/env python3
"""Inject breadcrumb bars + FAQ accordions + anchor IDs into subpages."""
import os, re

BASE = "/home/susiwilee/projects/pipeline-dashboard-v3"

FAQ_DATA = {
    "pfc3l": {
        "name": "PFC-3L Signal Intelligence",
        "home_crumb": "PFC-3L Signal",
        "faqs": [
            ("What is the PFC-3L signal?", "PFC-3L stands for Positioning, Flow, Catalyst, and Level. It is a deterministic six-state signal engine that analyzes Bitcoin market structure across four strategic components. Each component produces a score; the final signal (LONG_CANDIDATE, SHORT_CANDIDATE, WATCH_LONG, WATCH_SHORT, NO_TRADE, or DATA_UNRELIABLE) is determined by whether all four gates exceed their thresholds simultaneously."),
            ("How is confidence calculated?", "Confidence is the minimum score across all passing gates — a weak gate is never averaged away by strong ones. This conservative approach ensures you only act when all four strategic components (positioning, flow, catalyst, and psychological level) independently confirm the same direction."),
            ("What does DATA_UNRELIABLE mean?", "DATA_UNRELIABLE is a fail-safe state that blocks all directional signals when critical data feeds (AMT, AI Factors, derivatives) are stale, missing, or have timestamp issues. This is a data quality veto — it protects you from acting on bad or outdated information."),
            ("Does PFC-3L use AI or LLMs?", "No. All scoring and signal decisions are deterministic Python rules. An LLM may summarize the output for readability but is explicitly prohibited from creating or overriding any signal, score, or threshold."),
            ("What are the four gates (P, F, C, L)?", "<b>P</b> (Positioning) evaluates open interest, funding rates, and long/short ratios to find the vulnerable leveraged side. <b>F</b> (Flow) tracks spot CVD, taker buy/sell ratios, and Coinbase premium for genuine money movement. <b>C</b> (Catalyst) monitors VIX, US10Y, volume anomalies, and macro triggers. <b>L</b> (Level) identifies active psychological price zones (support/resistance) near current price."),
        ],
    },
    "aegis": {
        "name": "BTC AEGIS",
        "home_crumb": "BTC AEGIS",
        "faqs": [
            ("What is BTC AEGIS?", "BTC AEGIS is a trap avoidance control centre that monitors eight systemic risk signals (S1-S8), a crash precursor indicator, and a breakout validator. It is designed to help traders avoid market traps — situations where price action attracts traders into positions before reversing against them."),
            ("What are the S1-S8 trap signals?", "S1-S3 are leverage signals (funding rate extremity, OI spikes, OI-price divergence). S4-S5 are orderflow signals (Coinbase premium deviation, CVD divergence). S6-S7 are on-chain signals (exchange netflow spike, UTXO age band shift). S8 is an options signal (25 delta skew). Each contributes to a composite trap risk score from 0-8."),
            ("What is the Crash Precursor?", "The Crash Precursor monitors five systemic breakdown indicators: aggressive sell orders, support wall retreat, futures holding fees, leverage flushes, and momentum divergence. A composite score of 3+/5 in ELEVATED or DANGER status signals elevated systemic risk."),
            ("How should I use the Breakout Validator?", "The Breakout Validator assesses whether a price move through a configured level is genuine or likely to be a trap. It evaluates market evidence (volume, taker ratio, funding, OI delta, ATR) and produces a verdict on whether the breakout is accepted, unconfirmed, or a likely trap."),
        ],
    },
    "analysis": {
        "name": "BTC Live Analysis",
        "home_crumb": "Analysis",
        "faqs": [
            ("What does the Analysis page show?", "The Analysis page provides a live multi-layer verdict on Bitcoin market conditions, combining technical indicators (RSI, MACD, moving averages), on-chain metrics (MVRV-Z, SOPR, NUPL), derivatives data (funding, OI, liquidation levels), and macro correlations into a single actionable summary."),
            ("How often is the analysis updated?", "Every 15 minutes, synchronized with the full BTC data pipeline. All data sources (Binance, Yahoo Finance, FRED, on-chain providers) are refreshed before each analysis run."),
            ("What is the Gate0 risk framework?", "Gate0 is a pre-flight risk gating system that evaluates market conditions before any trade setup is considered. It uses six layers (macro regime, positioning, flow, derivatives, on-chain, and technical structure) to produce a go/no-go decision with explicit risk parameters."),
        ],
    },
}

BREADCRUMB_HTML = """<nav class="breadcrumb" aria-label="Breadcrumb" style="font-size:13px;color:var(--muted);margin-bottom:8px;padding:4px 0">
  <a href="../" style="color:var(--accent);text-decoration:none">Home</a> › <span style="color:var(--text)">%s</span>
</nav>
"""

BREADCRUMB_CSS = """.breadcrumb a:hover { text-decoration: underline; opacity: 0.8; }
.breadcrumb { user-select: none; -webkit-user-select: none; }
"""

FAQ_HTML = """
<hr style="opacity:0.1;margin:28px 0 20px">
<section id="faq" aria-labelledby="faq-heading">
  <h2 id="faq-heading" style="font-size:1.2rem;margin-bottom:14px">Frequently Asked Questions</h2>
  <div class="faq-list">
%s
  </div>
</section>
"""

FAQ_ITEM = """    <details class="faq-item" id="faq-%d" style="border:1px solid rgba(128,128,128,.15);border-radius:10px;padding:12px 16px;margin-bottom:8px;background:rgba(128,128,128,.03);cursor:pointer">
      <summary style="font-weight:600;font-size:14px;outline:none;user-select:none">%s</summary>
      <div style="margin-top:10px;color:var(--muted);font-size:13px;line-height:1.8">%s</div>
    </details>
"""

FAQ_SCHEMA = """  <!-- FAQPage Schema -->
  <script type="application/ld+json">
  {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    "mainEntity": [
%s
    ]
  }
  </script>
"""

FAQ_ENTITY = """      {
        "@type": "Question",
        "name": "%s",
        "acceptedAnswer": {
          "@type": "Answer",
          "text": "%s"
        }
      }"""


def inject_breadcrumb(html: str, name: str) -> str:
    """Inject breadcrumb bar above the first H1 tag."""
    breadcrumb_html = BREADCRUMB_HTML % name
    # Insert after <main> or after <body> if <main> not found
    if "<main" in html:
        html = html.replace("<main", breadcrumb_html + "\n<main", 1)
    else:
        # Insert after the first <h1> or first content div
        m = re.search(r"<h1[^>]*>.*?</h1>", html)
        if m:
            html = html[: m.start()] + breadcrumb_html + html[m.start() :]
    return html


def inject_faq(html: str, faqs: list, slug: str) -> tuple[str, str]:
    """Return (updated_html, faq_schema_jsonld)."""
    items = []
    entities = []
    for i, (q, a) in enumerate(faqs):
        items.append(FAQ_ITEM % (i + 1, q, a))
        entities.append(FAQ_ENTITY % (q.replace('"', '\\"'), a.replace('"', '\\"')))
    faq_html = FAQ_HTML % "\n".join(items)
    faq_schema = FAQ_SCHEMA % ",\n".join(entities)

    # Inject before closing </main> or before <footer> or before </body>
    if "</main>" in html:
        html = html.replace("</main>", faq_html + "\n</main>", 1)
    elif "<footer" in html:
        html = html.replace("<footer", faq_html + "\n<footer", 1)
    else:
        html = html.replace("</body>", faq_html + "\n</body>", 1)

    return html, faq_schema


def inject_faq_schema(html: str, faq_schema: str) -> str:
    """Inject FAQPage JSON-LD into <head>."""
    if '"@type": "FAQPage"' not in html:
        html = html.replace("</head>", faq_schema + "\n</head>")
    return html


def main():
    for slug, data in FAQ_DATA.items():
        path = os.path.join(BASE, slug, "index.html")
        if not os.path.exists(path):
            print(f"⚠️  {slug}/index.html not found")
            continue

        with open(path) as f:
            html = f.read()

        # Breadcrumb
        html = inject_breadcrumb(html, data["home_crumb"])

        # FAQ accordions
        html, faq_schema = inject_faq(html, data["faqs"], slug)

        # FAQPage schema in head
        html = inject_faq_schema(html, faq_schema)

        # Breadcrumb CSS (only if not already present)
        if "class=\"breadcrumb" in html and ".breadcrumb a:hover" not in html:
            html = html.replace("</style>", BREADCRUMB_CSS + "</style>", 1)

        with open(path, "w") as f:
            f.write(html)

        print(f"✅ {slug}: breadcrumb + {len(data['faqs'])} FAQs + FAQPage schema")

    print("\nDone — Phase 3 complete.")


if __name__ == "__main__":
    main()
