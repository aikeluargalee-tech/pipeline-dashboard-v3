#!/usr/bin/env python3
"""Rebuild sitemap.xml with research pages, verdict archives, and consolidated structure."""
import os, glob, datetime

BASE = "/home/susiwilee/projects/pipeline-dashboard-v3"
DOMAIN = "https://aikeluargalee-tech.github.io/pipeline-dashboard-v3"

# Tier 1: Core data pages (priority 0.9-1.0, hourly)
CORE = [
    ("", "1.0", "hourly"),  # homepage
    ("dashboard/", "0.9", "hourly"),
    ("packet/", "0.9", "hourly"),
    ("analysis/", "0.9", "hourly"),
    ("pfc3l/", "0.9", "hourly"),
    ("aegis/", "0.9", "hourly"),
    ("ai-factors/", "0.8", "hourly"),
    ("market-regime/", "0.8", "hourly"),
    ("psychological-levels/", "0.8", "hourly"),
    ("volume-profile/", "0.8", "hourly"),
    ("whale-wake/", "0.8", "hourly"),
]

# Tier 2: Supporting pages (priority 0.6-0.7)
SUPPORT = [
    ("about/", "0.7"),
    ("methodology/", "0.7"),
    ("glossary/", "0.6"),
    ("faq/", "0.6"),
    ("events-and-disruptions/", "0.6"),
    ("track-record/", "0.6"),
    ("research/", "0.6"),
]

# Tier 3: Legal (priority 0.3)
LEGAL = [
    ("privacy/", "0.3"),
    ("terms/", "0.3"),
    ("contact/", "0.5"),
]

# Tier 4: Research articles (priority 0.5, monthly)
research_dirs = sorted(glob.glob(os.path.join(BASE, "research", "*")))
RESEARCH = []
for d in research_dirs:
    if os.path.isdir(d) and os.path.exists(os.path.join(d, "index.html")):
        slug = os.path.basename(d) + "/"
        path = f"research/{slug}"
        RESEARCH.append((path, "0.5", "monthly"))

# Verdict monthly archives
verdict_dirs = sorted(glob.glob(os.path.join(BASE, "verdicts", "20*-*")))
VERDICTS = []
for d in verdict_dirs:
    if os.path.isdir(d) and os.path.exists(os.path.join(d, "index.html")):
        month_slug = os.path.basename(d) + "/"
        path = f"verdicts/{month_slug}"
        VERDICTS.append((path, "0.4", "monthly"))
# Also add verdicts index
VERDICTS.insert(0, ("verdicts/", "0.5", "weekly"))

# Compare
COMPARE = [
    ("compare/", "0.5", "monthly"),
    ("compare/gate0-vs-coinglass/", "0.4", "monthly"),
    ("compare/gate0-vs-cryptoquant/", "0.4", "monthly"),
    ("compare/gate0-vs-glassnode/", "0.4", "monthly"),
]

now = datetime.datetime.utcnow().strftime("%Y-%m-%d")
entries = []

def add_entry(path, priority, changefreq="monthly"):
    entries.append(f"""  <url>
    <loc>{DOMAIN}/{path}</loc>
    <lastmod>{now}</lastmod>
    <changefreq>{changefreq}</changefreq>
    <priority>{priority}</priority>
  </url>""")

for path, pri, freq in CORE:
    add_entry(path, pri, freq)

for path, pri in SUPPORT:
    add_entry(path, pri)

for path, pri in LEGAL:
    add_entry(path, pri)

for path, pri, freq in RESEARCH:
    add_entry(path, pri, freq)

for path, pri, freq in COMPARE:
    add_entry(path, pri, freq)

for path, pri, freq in VERDICTS:
    add_entry(path, pri, freq)

sitemap = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{"".join(entries)}
</urlset>
"""

with open(os.path.join(BASE, "sitemap.xml"), "w") as f:
    f.write(sitemap)

total = len(CORE) + len(SUPPORT) + len(LEGAL) + len(RESEARCH) + len(COMPARE) + len(VERDICTS)
print(f"Sitemap rebuilt: {total} URLs")
print(f"  Core: {len(CORE)} | Research: {len(RESEARCH)} | Verdicts: {len(VERDICTS)} | Other: {len(SUPPORT)+len(LEGAL)+len(COMPARE)}")
