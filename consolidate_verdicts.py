#!/usr/bin/env python3
"""Consolidate 31 daily verdict pages into monthly archives + add noindex to dailies."""
import os, json, glob
from collections import defaultdict

BASE = "/home/susiwilee/projects/pipeline-dashboard-v3"
VERDICTS = os.path.join(BASE, "verdicts")

# Step 1: Add noindex to all daily verdict pages
daily_dirs = sorted(glob.glob(os.path.join(VERDICTS, "20*")))
monthly = defaultdict(list)

for d in daily_dirs:
    date_str = os.path.basename(d)
    monthly[date_str[:7]].append(date_str)
    
    idx = os.path.join(d, "index.html")
    if not os.path.exists(idx):
        continue
    
    with open(idx) as f:
        html = f.read()
    
    if 'name="robots"' in html:
        html = html.replace(
            '<meta name="robots" content="noindex, follow">',
            '<meta name="robots" content="noindex, follow">',
        )
    elif "</head>" in html:
        html = html.replace("</head>", '  <meta name="robots" content="noindex, follow">\n</head>')
    
    # Add canonical to monthly page
    month_slug = date_str[:7]
    if '<link rel="canonical"' not in html:
        html = html.replace(
            "</head>",
            f'  <link rel="canonical" href="https://aikeluargalee-tech.github.io/pipeline-dashboard-v3/verdicts/{month_slug}/">\n</head>',
        )
    
    with open(idx, "w") as f:
        f.write(html)

print(f"Added noindex + canonical to {len(daily_dirs)} daily verdict pages")

# Step 2: Create monthly archive pages
for month, days in sorted(monthly.items()):
    month_dir = os.path.join(VERDICTS, month)
    os.makedirs(month_dir, exist_ok=True)
    
    month_idx = os.path.join(month_dir, "index.html")
    day_list = "\n".join(
        f'      <li><a href="../{d}/" style="color:var(--accent)">{d}</a></li>'
        for d in sorted(days, reverse=True)
    )
    
    # Parse month name
    y, m = month.split("-")
    months = ["January", "February", "March", "April", "May", "June",
              "July", "August", "September", "October", "November", "December"]
    month_name = months[int(m) - 1]
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BTC Verdict Archive — {month_name} {y} | Pipeline Dashboard</title>
<meta name="description" content="Daily Bitcoin market verdict archive for {month_name} {y}. Gate0 risk synthesis, PFC-3L signals, and multi-layer analysis summaries.">
<link rel="canonical" href="https://aikeluargalee-tech.github.io/pipeline-dashboard-v3/verdicts/{month}/">
<meta property="og:title" content="BTC Verdict Archive — {month_name} {y}">
<meta property="og:type" content="website">
<link rel="stylesheet" href="../../assets/styles.css?v=12">
</head>
<body>
<div id="nav-placeholder"></div>
<main class="page-container">
  <nav class="breadcrumb" style="display:inline-flex;align-items:center;gap:6px;font-size:13px;color:var(--muted);margin-bottom:8px;padding:6px 14px;border:1px solid rgba(128,128,128,.15);border-radius:20px;background:rgba(128,128,128,.04);backdrop-filter:blur(10px)">
    <a href="../../" style="color:var(--accent);text-decoration:none">Home</a>
    <span style="opacity:0.6">›</span>
    <a href="../" style="color:var(--accent);text-decoration:none">Verdicts</a>
    <span style="opacity:0.6">›</span>
    <span>{month_name} {y}</span>
  </nav>

  <h1>BTC Verdict Archive — {month_name} {y}</h1>
  <p style="color:var(--muted);margin-bottom:20px">{len(days)} daily verdicts — each combines Gate0 risk synthesis, PFC-3L signal intelligence, and multi-layer market analysis into a single page.</p>
  
  <ul style="list-style:none;padding:0;display:grid;gap:6px">
{day_list}
  </ul>
  
  <p style="margin-top:24px;color:var(--muted);font-size:13px">
    ← <a href="../" style="color:var(--accent)">All verdicts</a> | 
    <a href="../../track-record/" style="color:var(--accent)">Track Record</a>
  </p>
</main>
<div id="footer-placeholder"></div>
<script src="../../assets/nav.js?v=13"></script>
</body>
</html>
"""
    with open(month_idx, "w") as f:
        f.write(html)

print(f"Created {len(monthly)} monthly archive pages: {sorted(monthly.keys())}")
print("Done — verdict consolidation complete.")
