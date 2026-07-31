#!/usr/bin/env python3
"""Phase 6: Inject internal cross-links + related pages footer."""
import os

BASE = "/home/susiwilee/projects/pipeline-dashboard-v3"

# Related pages map — each page gets 3 complementary links
RELATED = {
    "pfc3l": [
        ("BTC AEGIS — Trap Avoidance", "../aegis/"),
        ("AI Factors — Macro Signals", "../ai-factors/"),
        ("Analysis — Live Verdict", "../analysis/"),
    ],
    "aegis": [
        ("PFC-3L — Signal Intelligence", "../pfc3l/"),
        ("Crash Precursor — Systemic Risk", "../analysis/"),
        ("Whale Wake — Order Footprint", "../whale-wake/"),
    ],
    "ai-factors": [
        ("PFC-3L — Signal Intelligence", "../pfc3l/"),
        ("Market Regime — Classification", "../market-regime/"),
        ("Analysis — Live Verdict", "../analysis/"),
    ],
    "analysis": [
        ("PFC-3L — Signal Intelligence", "../pfc3l/"),
        ("BTC AEGIS — Trap Avoidance", "../aegis/"),
        ("Data Packet — Raw Metrics", "../packet/"),
    ],
    "packet": [
        ("Analysis — Live Verdict", "../analysis/"),
        ("PFC-3L — Signal Intelligence", "../pfc3l/"),
        ("Regime Compass — Rotation Map", "../regime-compass/"),
    ],
    "volume-profile": [
        ("Psychological Levels — S/R Map", "../psychological-levels/"),
        ("Regime Compass — Rotation Map", "../regime-compass/"),
        ("Whale Wake — Order Footprint", "../whale-wake/"),
    ],
    "whale-wake": [
        ("BTC AEGIS — Trap Avoidance", "../aegis/"),
        ("Volume Profile — Auction Zones", "../volume-profile/"),
        ("Analysis — Live Verdict", "../analysis/"),
    ],
    "market-regime": [
        ("AI Factors — Macro Signals", "../ai-factors/"),
        ("Regime Compass — Rotation Map", "../regime-compass/"),
        ("PFC-3L — Signal Intelligence", "../pfc3l/"),
    ],
    "regime-compass": [
        ("Market Regime — Classification", "../market-regime/"),
        ("AI Factors — Macro Signals", "../ai-factors/"),
        ("Volume Profile — Auction Zones", "../volume-profile/"),
    ],
    "psychological-levels": [
        ("Volume Profile — Auction Zones", "../volume-profile/"),
        ("PFC-3L — Signal Intelligence", "../pfc3l/"),
        ("BTC AEGIS — Trap Avoidance", "../aegis/"),
    ],
}

FOOTER_HTML = """
<section id="related-pages" aria-labelledby="related-heading" style="margin-top:28px;padding-top:16px;border-top:1px solid rgba(128,128,128,.15)">
  <h2 id="related-heading" style="font-size:14px;margin-bottom:10px;font-weight:600">📎 Related Pages</h2>
  <nav style="display:flex;flex-wrap:wrap;gap:10px;font-size:13px">
%s
  </nav>
</section>
"""

LINK_HTML = '    <a href="%s" style="color:var(--accent);text-decoration:none;padding:6px 12px;border:1px solid rgba(128,128,128,.15);border-radius:8px;white-space:nowrap">%s</a>\n'


def inject_related(html: str, links: list) -> str:
    """Inject related pages before provenance card or </html>."""
    link_html = "".join(LINK_HTML % (url, label) for label, url in links)
    footer = FOOTER_HTML % link_html

    if "provenance-card" in html:
        html = html.replace('<section id="data-provenance"', footer + '\n<section id="data-provenance"', 1)
    elif "</html>" in html:
        html = html.replace("</html>", footer + "\n</html>", 1)
    elif "</body>" in html:
        html = html.replace("</body>", footer + "\n</body>", 1)
    else:
        html += footer

    return html


def main():
    for slug, links in RELATED.items():
        path = os.path.join(BASE, slug, "index.html")
        if not os.path.exists(path):
            print(f"⚠️  {slug}: not found")
            continue

        with open(path) as f:
            html = f.read()

        if "related-pages" in html:
            print(f"⏭️  {slug}: already has related pages")
            continue

        html = inject_related(html, links)

        with open(path, "w") as f:
            f.write(html)

        print(f"✅ {slug}: {len(links)} related links")

    print("\nDone — Phase 6 complete.")


if __name__ == "__main__":
    main()
