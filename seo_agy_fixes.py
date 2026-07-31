#!/usr/bin/env python3
"""Agy review fixes: noscript, breadcrumb polish, GDPR consent banner."""
import os, re

BASE = "/home/susiwilee/projects/pipeline-dashboard-v3"
PAGES = ["pfc3l", "aegis", "ai-factors", "analysis", "packet",
         "volume-profile", "whale-wake", "market-regime",
         "regime-compass", "psychological-levels", "dashboard"]

NOSCRIPT_HTML = """<noscript>
  <div style="padding:20px;background:rgba(128,128,128,.08);border:1px solid rgba(128,128,128,.2);border-radius:10px;margin:16px 0;text-align:center">
    <p style="font-size:15px;font-weight:600;margin-bottom:8px">⚡ Pipeline Dashboard — JavaScript Required</p>
    <p style="color:var(--muted);font-size:13px">This page displays live Bitcoin market data updated every 15 minutes. Please enable JavaScript to view real-time signals, or visit our static <a href="../packet/" style="color:var(--accent)">Data Packet</a> for raw metrics.</p>
    <p style="color:var(--muted);font-size:12px;margin-top:10px">Latest pipeline data is always available at <a href="../packet/data.json" style="color:var(--accent)">packet/data.json</a></p>
  </div>
</noscript>
"""

GDPR_HTML = """<!-- GDPR Cookie Consent Banner -->
<div id="cookie-banner" style="display:none;position:fixed;bottom:0;left:0;right:0;background:rgba(15,15,20,.97);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);border-top:1px solid rgba(128,128,128,.15);padding:14px 20px;z-index:9999;font-size:13px;color:var(--text);display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px">
  <div style="flex:1;min-width:250px">🍪 This site uses cookies from Google AdSense for ad personalization and measurement. By continuing, you consent to our <a href="../privacy/" style="color:var(--accent)">Privacy Policy</a> and <a href="../terms/" style="color:var(--accent)">Terms</a>.</div>
  <div style="display:flex;gap:8px;flex-shrink:0">
    <button onclick="acceptCookies()" style="padding:8px 18px;background:var(--accent);color:#000;border:none;border-radius:6px;font-weight:600;cursor:pointer;font-size:13px">Accept</button>
    <button onclick="declineCookies()" style="padding:8px 18px;background:rgba(128,128,128,.1);color:var(--text);border:1px solid rgba(128,128,128,.2);border-radius:6px;cursor:pointer;font-size:13px">Decline</button>
  </div>
</div>
<script>
(function(){
  if (localStorage.getItem('cookie-consent')) return;
  var b = document.getElementById('cookie-banner');
  if (b) b.style.display = 'flex';
  window.acceptCookies = function() { localStorage.setItem('cookie-consent','accepted'); b.style.display='none'; };
  window.declineCookies = function() { localStorage.setItem('cookie-consent','declined'); b.style.display='none'; };
})();
</script>
"""

BREADCRUMB_CSS = """.breadcrumb { display:inline-flex;align-items:center;gap:6px;font-size:13px;color:var(--muted);margin-bottom:8px;padding:6px 14px;border:1px solid rgba(128,128,128,.15);border-radius:20px;background:rgba(128,128,128,.04);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);margin-top:4px }
.breadcrumb a { color:var(--accent);text-decoration:none }
.breadcrumb a:hover { text-decoration:underline }
.breadcrumb span { opacity:0.6 }
@media (max-width:480px) { .breadcrumb { font-size:11px;padding:4px 10px } }
"""


def inject_all(html: str, slug: str) -> str:
    # 1. Noscript fallback (right after <body> or after nav)
    if "<noscript>" not in html:
        if '<div id="nav-placeholder">' in html:
            html = html.replace('<div id="nav-placeholder">', NOSCRIPT_HTML + '\n<div id="nav-placeholder">', 1)
        elif "<body>" in html:
            html = html.replace("<body>", "<body>\n" + NOSCRIPT_HTML, 1)
        elif "</head>" in html:
            html = html.replace("</head>", "</head>\n<body>\n" + NOSCRIPT_HTML, 1)

    # 2. GDPR banner (before </body> or </html>)
    if "cookie-banner" not in html:
        if "</body>" in html:
            html = html.replace("</body>", GDPR_HTML + "\n</body>", 1)
        elif "</html>" in html:
            html = html.replace("</html>", GDPR_HTML + "\n</html>", 1)
        else:
            html += GDPR_HTML

    # 3. Breadcrumb polish (replace inline breadcrumb with styled version)
    if 'class="breadcrumb"' in html and ".breadcrumb {" not in html:
        # Add CSS to existing <style> block
        if "</style>" in html:
            html = html.replace("</style>", BREADCRUMB_CSS + "</style>", 1)
        elif "</head>" in html:
            html = html.replace("</head>", "<style>" + BREADCRUMB_CSS + "</style>\n</head>", 1)

    return html


def main():
    for slug in PAGES:
        path = os.path.join(BASE, slug, "index.html")
        if not os.path.exists(path):
            print(f"⚠️  {slug}: not found")
            continue

        with open(path) as f:
            html = f.read()

        html = inject_all(html, slug)

        with open(path, "w") as f:
            f.write(html)

        has_noscript = "<noscript>" in html
        has_gdpr = "cookie-banner" in html
        has_breadcrumb_css = ".breadcrumb {" in html
        print(f"✅ {slug}: noscript={has_noscript} gdpr={has_gdpr} breadcrumb_css={has_breadcrumb_css}")

    print("\nDone — Agy fixes complete.")


if __name__ == "__main__":
    main()
