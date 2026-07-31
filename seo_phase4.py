#!/usr/bin/env python3
"""Phase 4: Inject data provenance cards + author schema + financial disclaimers."""
import os, re

BASE = "/home/susiwilee/projects/pipeline-dashboard-v3"
SUBPAGES = [
    "pfc3l", "aegis", "ai-factors", "psychological-levels", "regime-compass",
    "volume-profile", "whale-wake", "market-regime", "packet", "analysis",
]

PROVENANCE_HTML = """<section id="data-provenance" class="provenance-card" style="border:1px solid rgba(128,128,128,.15);border-radius:10px;padding:14px 18px;margin:22px 0;background:rgba(128,128,128,.03);font-size:12px;color:var(--muted);line-height:1.8" aria-labelledby="prov-heading">
  <h2 id="prov-heading" style="font-size:14px;margin:0 0 8px;font-weight:600">📊 Data Sources</h2>
  <div><b>Real-time:</b> Binance API (spot + derivatives) · Coinbase (premium index) · Coinglass (liquidations, OI)</div>
  <div><b>Macro:</b> Yahoo Finance (VIX, US10Y, SPY, QQQ, DXY, Gold) · FRED (M2, rates)</div>
  <div><b>On-chain:</b> Glassnode (MVRV-Z, SOPR, NUPL, LTH-SOPR, hashrate) · CoinMetrics</div>
  <div><b>Pipeline refresh:</b> Every 15 minutes · <b>Last generated:</b> <span id="prov-last-update">updating...</span></div>
  <div style="margin-top:8px;opacity:0.7"><b>⚠️ Disclaimer:</b> Educational decision-support only. Not financial advice. No exchange accounts, wallets, or private APIs are accessed. All signals are deterministic Python logic — LLMs may summarize but <b>never</b> override scores or thresholds. Users remain solely responsible for their trading decisions.</div>
</section>
"""

AUTHOR_SCHEMA = """  <!-- Organization Schema -->
  <script type="application/ld+json">
  {
    "@context": "https://schema.org",
    "@type": "Organization",
    "name": "Pipeline Dashboard",
    "description": "Open-source Bitcoin market intelligence platform — multi-layer analysis with Gate0 risk gating.",
    "url": "https://aikeluargalee-tech.github.io/pipeline-dashboard-v3/"
  }
  </script>
"""


def inject_provenance(html: str) -> str:
    """Inject data provenance card before </main> or closing content."""
    if "provenance-card" in html:
        return html

    if "</main>" in html:
        html = html.replace("</main>", PROVENANCE_HTML + "\n</main>", 1)
    elif "<footer" in html:
        html = html.replace("<footer", PROVENANCE_HTML + "\n<footer", 1)
    else:
        # Find the last <section> or last </div> before </body>
        if "</body>" in html:
            html = html.replace("</body>", PROVENANCE_HTML + "\n</body>", 1)
        elif "</html>" in html:
            html = html.replace("</html>", PROVENANCE_HTML + "\n</html>", 1)
        else:
            html += PROVENANCE_HTML
    return html


def inject_author_schema(html: str) -> str:
    """Inject Organization schema into head."""
    if '"@type": "Organization"' in html:
        return html
    return html.replace("</head>", AUTHOR_SCHEMA + "\n</head>")


def main():
    for slug in SUBPAGES:
        path = os.path.join(BASE, slug, "index.html")
        if not os.path.exists(path):
            print(f"⚠️  {slug}: not found")
            continue

        with open(path) as f:
            html = f.read()

        html = inject_provenance(html)
        html = inject_author_schema(html)

        with open(path, "w") as f:
            f.write(html)

        has_prov = "provenance-card" in html
        has_org = '"@type": "Organization"' in html
        print(f"✅ {slug}: provenance={has_prov} org_schema={has_org}")

    print("\nDone — Phase 4 complete.")


if __name__ == "__main__":
    main()
