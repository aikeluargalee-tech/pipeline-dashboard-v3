# Whale Bugfix Report — pipeline-dashboard-v3

**Date:** 2026-07-31 (UTC)
**Scope:** 101 HTML files (all of workspace, excluding `.venv`, `.git`, `.bugscan`)
**Rules honored:** No modifications to `data/` files (data.json & generated data untouched); `http://localhost:3000` Crucix link untouched; no commits made.

---

## STEP 1 — Scan results

### 1a. `<script type="application/ld+json">` blocks
- **Scanned:** all HTML files (regex extraction, `ld+json` typed blocks)
- **Invalid JSON: 0** ✅
- All blocks parse cleanly.

### 1b. Inline `<script>` blocks (node --check)
- **Extracted:** 27 inline JS blocks (excludes `src=` external scripts, `application/ld+json`, and `application/json` data blocks)
- **Syntax failures: 0** ✅
- One initial false positive: `dashboard/index.html` `<script type="application/json" id="dashboard-snapshot">` is a JSON data block, not JS — excluded from the check (valid JSON, confirmed).

### 1c. Local link check (`<a href>` / `<link href>` + all `src=`)
- **Checked:** 946 local href/src references
- Ignored per rules: external http(s) URLs, `mailto:`, `tel:`, `javascript:`, `data:`, `#`-fragments, protocol-relative, and `http://localhost:3000` (intentional).
- **Broken found: 55 files, 2 broken references each (110 refs) + 1 file with 16 broken nav links**
- JS template placeholders `${esc(safeUrl)}`, `${esc(String(v7.long.file))}`, `${esc(String(v7.short.file))}` (dashboard) and `${sdef.url}` (packet) are dynamic links built at runtime inside `<script>` blocks — **not bugs** (verified: valid JS, values substituted at runtime).

### 1d. Hardcoded fake stats / placeholder values presented as live data
- **None found** ✅
- All "placeholder" hits are legit DOM injection points (`id="nav-placeholder"` / `id="footer-placeholder"`) and one `<textarea placeholder=...>` attribute.
- "fake/fakeout" hits are prose about market behavior in research articles.
- Live pages (dashboard, whale-wake, aegis, market-regime, etc.) contain no hardcoded prices/stats; values are fetched from `data/*.json` at runtime (`meta.last_update` etc.).

---

## STEP 2 — Bugs fixed (56 files, 126 references)

### Bug 1 — Wrong relative asset depth in 2-level-deep pages (55 files)
Pages at `research/<slug>/`, `compare/gate0-*/`, and `verdicts/<date>/` referenced assets as `../assets/...` (correct only for 1-level-deep pages like `about/`). Resolved to `research/assets/` / `compare/assets/` / `verdicts/assets/` → **404**.

Fixed in all 55 files (both references each, 110 total):
- `href="../assets/styles.css?v=12"` → `href="../../assets/styles.css?v=12"`
- `src="../assets/nav.js?v=17"` → `src="../../assets/nav.js?v=17"`

Affected files:
- `compare/gate0-vs-coinglass/index.html`, `compare/gate0-vs-cryptoquant/index.html`, `compare/gate0-vs-glassnode/index.html` (3)
- `research/<slug>/index.html` for 39 slugs (atr-weighted-support-resistance … weekend-trading-noisier-signals)
- `verdicts/2026-06-19 … 2026-07-04/index.html` (13 dated pages)

### Bug 2 — Broken absolute-path nav in `<noscript>` fallback (whale-wake/index.html)
The unique `<noscript>` nav hardcoded 16 GitHub-Pages subpath URLs (`/pipeline-dashboard-v3/...`). These 404 locally, at any root-domain hosting, and contradict both the rest of the site (relative links) and `assets/nav.js` (which detects the mount point at runtime). The canonical URL and JSON-LD `url` fields (full `https://aikeluargalee-tech.github.io/...`) were left untouched.

Fixed: all 16 nav hrefs converted to relative (`/pipeline-dashboard-v3/dashboard/` → `../dashboard/`, `/pipeline-dashboard-v3/` → `../`, etc.), which resolve correctly both locally and under the subpath deployment.

---

## STEP 3 — Re-verification (all passed)

| Check | Before | After |
|---|---|---|
| ld+json invalid | 0 | 0 ✅ |
| inline JS syntax failures | 0 (of 27) | 0 ✅ |
| broken local links | 55 files + 1 nav | 0 ✅ (only dynamic `${...}` placeholders remain, not bugs) |
| fake stats/placeholders | none | none ✅ |

Spot-checked `whale-wake`, `research/bitcoin-cycle-phases`, `compare/gate0-vs-coinglass`, `verdicts/2026-07-04`: all hrefs resolve locally.

---

## Notes / intentionally untouched

- `data/` directory: **not modified** (per rules).
- `http://localhost:3000` Crucix link in dashboard: untouched.
- `${...}` template placeholders in dashboard/packet inline JS: dynamic runtime links, not static broken links.
- Canonical + JSON-LD full URLs (`https://aikeluargalee-tech.github.io/pipeline-dashboard-v3/...`): intentional SEO, untouched.
- No commits made. No data regeneration run.
- Leftover scan artifact: untracked `.bugscan/` scratch directory (scan scripts + extracted JS); safe to delete, not part of the site.
