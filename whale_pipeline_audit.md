# Pipeline Audit — btc_data_packet.sh (Milo direct review, 2026-07-31)

**File:** `~/.hermes/scripts/btc_data_packet.sh` (42 lines, runs every 15 min via cron)
**Method:** Direct read + cross-reference with Whale's PFC-3L/AEGIS audit findings.

---

## Findings

### 🔴 HIGH

**P1 — AEGIS pipeline runs the LEGACY generator, not the full engine**
- Line 35: `$PY .../src/aegis_gen.py` (75-line partial generator, 3 sections)
- The full 7-section engine `src/aegis_engine.py` (written 2026-07-31, produces `data/aegis_state.json` with overview/trap/crash/cycle/breakout/approved/ledger) is **never invoked** by the pipeline.
- Consequence: `aegis_state.json` is stale (12+ hours old per Whale) or only partially regenerated; the AEGIS page shows zeros for most sections.
- **Fix:** replace line 35 with `$PY .../src/aegis_engine.py`.

**P2 — No error guards anywhere**
- Every producer step is `$PY script.py >&2` with exit code ignored.
- If any producer crashes (network down, bad API response), the run continues silently; `build_packet.py` may assemble a packet with stale/missing sections, which then gets committed and deployed as if fresh.
- No `set -e`, no `|| exit 1`, no per-step status capture.
- **Fix:** add `set -u` + per-step `|| { echo "STEP FAILED: $step"; exit 1; }` or at minimum a failure log + don't-deploy guard.

**P3 — Silent git failures**
- Line 42: `git push origin main >/dev/null 2>&1` — if push fails (auth, network), the commit exists locally but the deployed site stays stale with NO alert.
- **Fix:** capture push result; on failure, keep the commit, log a warning, and surface in next run.

### 🟠 MEDIUM

**P4 — Hardcoded absolute paths everywhere**
- `/home/susiwilee/...` on lines 2, 4-18, 28-37. The VPS migration plan (documented in Obsidian) will require sed-ing every path — same class of issue that bit the old laptop migration.
- **Fix:** `PROJ=~/projects` variable at top; derive all paths from it.

**P5 — No retries on network fetches**
- AMT collector, AI factors, regime classifier all hit external APIs. A single transient failure = missing section for that cycle. 15-min cadence means 4 retry chances/hour — cheap to add 1-2 retries.
- **Fix:** wrap the 3 most failure-prone fetchers in a small retry loop (2 attempts, 5s apart).

**P6 — Stale-file risk when a producer fails**
- Line 20: `cat /tmp/btc_data_packet.txt` — if `build_packet.py` failed, this emits yesterday's (or older) packet content into the cron output, which the operator may read as today's data.
- The 15-min auto-commit (P2/P3) compounds this: stale data gets committed as "auto: update packet data" without freshness verification.
- **Fix:** timestamp check — if `/tmp/btc_data_packet.txt` older than 30 min, emit "STALE PACKET — pipeline failed" instead of the old content.

### 🟢 LOW

**P7 — Duplicate step numbering** (two #3, two #6, #10 before #9) — cosmetic drift from incremental edits; makes the script harder to audit.
**P8 — Disabled GetClaw send block left as comment** (lines 22-25) — fine, but consider removing for cleanliness.

---

## What's Correct

- Correlation + LIQ clusters producers run first (fast, cheap).
- BRK collector has a 6-hour cache guard (line 8) — good pattern, the only caching in the script.
- PFC-3L signal engine + enrich wired in (lines 30-33) — working.
- Conditional git commit (`git diff --cached --quiet ||`) avoids empty commits.

---

## Recommended Fix Order

1. **P1** — swap `aegis_gen.py` → `aegis_engine.py` (5 min, restores AEGIS page)
2. **P2/P3** — add step guards + push-failure visibility (30 min, prevents silent stale deploys)
3. **P6** — stale-packet detection (15 min)
4. **P4** — path variables (15 min, VPS-prep)
5. **P5** — retries (20 min)
