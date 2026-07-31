# Pipeline Dashboard V3 — SEO/AEO/GEO Optimization Plan
## Goal: Google Search ranking + AI Overview citations + AdSense qualification

---

## Phase 1 — Technical Foundation (1-2 hours)

### 1.1 Remove `no-cache` everywhere
**Files:** All `index.html` pages, root + subpages
```html
<!-- REMOVE these three lines -->
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
```
**Why:** These tell Googlebot to NOT cache pages — the opposite of what we want. Google needs cached snapshots to index properly.

### 1.2 Add cache-friendly headers
Replace with versioned asset cache busting:
```html
<link rel="stylesheet" href="/assets/main.css?v=2">
<script src="/assets/nav.js?v=14"></script>
```

### 1.3 Verify sitemap.xml completeness
Ensure all 10+ subpages are listed with proper `lastmod` and `changefreq`:
- `/` (dashboard)
- `/packet/`
- `/analysis/`
- `/pfc3l/`
- `/aegis/`
- `/ai-factors/`
- `/psych-levels/`
- `/regime-compass/`
- `/volume-profile/`
- `/whale-wake/`

### 1.4 Add `priority` and `changefreq` to sitemap
```xml
<url>
  <loc>https://domain.com/pfc3l/</loc>
  <changefreq>hourly</changefreq>
  <priority>0.9</priority>
</url>
```

---

## Phase 2 — Per-Page Cold-DOM Metadata (2-3 hours) ⭐ CRITICAL

### 2.1 Unique `<title>` for every subpage
| Page | Title (50-60 chars) |
|---|---|
| Home | Bitcoin Market Intelligence — Free BTC Analysis & Setup Tracking |
| Packet | BTC Data Packet — Raw Pipeline Metrics & Enriched Fields |
| Analysis | BTC Live Analysis — Technicals, On-Chain & Derivatives Verdict |
| PFC-3L | PFC-3L Signal Intelligence — Positioning, Flow, Catalyst & Levels |
| AEGIS | BTC AEGIS — Trap Avoidance & Systemic Risk Control Centre |
| AI Factors | AI Factors Monitor — VIX, US10Y & Volume Anomaly Signals |
| Psych Levels | BTC Psychological Levels — Round-Number Support & Resistance |
| Regime Compass | BTC Market Regime Compass — Trend, Momentum & Volatility |
| Volume Profile | BTC Volume Profile — POC, VAL, VAH & HVN Zones |
| Whale Wake | BTC Whale Wake — Large-Order Footprint & CVD Divergence |

### 2.2 Unique `<meta name="description">` per page (140-155 chars)
Each subpage gets a specific description explaining what that page provides, with target keywords.

### 2.3 Unique `<link rel="canonical">` per page

### 2.4 Subpage-level Schema.org
```json
{
  "@context": "https://schema.org",
  "@type": "WebPage",
  "name": "PFC-3L Signal Intelligence",
  "description": "...",
  "isPartOf": {
    "@type": "WebSite",
    "name": "BTC Pipeline Dashboard"
  }
}
```

---

## Phase 3 — Structured Data & Rich Results (2-3 hours)

### 3.1 BreadcrumbList on every page
```json
{
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  "itemListElement": [
    {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://domain.com/"},
    {"@type": "ListItem", "position": 2, "name": "PFC-3L Signal", "item": "https://domain.com/pfc3l/"}
  ]
}
```
**Why:** Google replaces raw URLs with clean breadcrumb paths in SERP, increasing CTR.

### 3.2 Visual breadcrumb bar UI
Above `<h1>` on every subpage: `Home > PFC-3L Signal Intelligence`

### 3.3 FAQ accordions with FAQPage schema
Add 4-6 question/answer pairs per major subpage using native `<details>/<summary>`:
- PFC-3L: "What is the PFC-3L signal?", "How is confidence calculated?", "What does DATA_UNRELIABLE mean?"
- AEGIS: "What is a BTC trap?", "How are trap signals detected?", "What are the S1-S8 signals?"
- AI Factors: "How do AI factors affect BTC?", "What is the VIX ROC signal?"

**Why:** Google AI Overviews and ChatGPT Search pull directly from `<details>` blocks with FAQPage schema.

### 3.4 Named anchor IDs on all sections
```html
<section id="positioning-gate">
<h2 id="gate-scores">Five-Gate Scorecard</h2>
```
**Why:** Google generates "Jump to..." deep-link snippets.

---

## Phase 4 — E-E-A-T & Trust Signals (1-2 hours)

### 4.1 Data provenance card on every subpage
```
📊 Data Sources
• Real-time: Binance API (spot + derivatives)
• Macro: Yahoo Finance, FRED
• On-chain: Glassnode, CoinMetrics
• Pipeline refresh: Every 15 minutes
• Last updated: [dynamic timestamp]
```

### 4.2 Author/publisher metadata
```json
{
  "@type": "Organization",
  "name": "Pipeline Dashboard",
  "description": "Open-source Bitcoin market intelligence"
}
```

### 4.3 Financial disclaimer (YMYL requirement)
Already present on PFC-3L. Extend to all subpages:
> "Educational decision-support only. Not financial advice. No exchange accounts, wallets, or private APIs accessed."

---

## Phase 5 — Core Web Vitals & Performance (1 hour)

### 5.1 Run Lighthouse audit on all major pages
Target: Performance ≥ 90, Accessibility ≥ 90, Best Practices ≥ 90, SEO ≥ 90

### 5.2 Image optimization
- Verify `social-card.png` exists at `/assets/`
- Add `width`/`height` attributes to all `<img>` tags (prevents CLS)
- Add `loading="lazy"` to below-fold images
- Add descriptive `alt` text to all images

### 5.3 Mobile responsive audit
Verify all subpages render correctly at 375px width (iPhone SE).

---

## Phase 6 — Internal Linking & Content Strategy (1 hour)

### 6.1 Cross-link subpages in content
Example on PFC-3L: "Signal uses data from the [AI Factors Monitor](/ai-factors/) for VIX and US10Y inputs."

### 6.2 Add a "Related Pages" footer section
At the bottom of each page, link to 2-3 related subpages.

### 6.3 Ensure every page is reachable within 3 clicks from homepage

---

## Phase 7 — AdSense Preparation (Future — post-VPS migration)

### 7.1 Custom domain on VPS (prerequisite for AdSense)
### 7.2 Privacy Policy page (AdSense requirement)
### 7.3 About/Contact pages (AdSense E-E-A-T requirement)
### 7.4 Ad placement strategy without hurting UX

---

## Implementation Order
1. **Phase 1** — Foundation (remove no-cache, fix sitemap)
2. **Phase 2** — Per-page metadata (unique titles, descriptions, schema)
3. **Phase 3** — Structured data (breadcrumbs, FAQ, anchors)
4. **Phase 4** — Trust signals (provenance, disclaimers)
5. **Phase 5** — Performance audit
6. **Phase 6** — Internal linking
7. **Phase 7** — AdSense (future)

**Estimated total: 9-12 hours**
