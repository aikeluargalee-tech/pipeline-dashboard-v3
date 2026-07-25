// vp-card.js — Volume Profile V3.1 Sentinel
// Verdict-driven card with delta, OI, funding, confidence engine

const VP_JSON_PATH = './data/vp_card.json';

// ── Verdict config ──────────────────────────────
const VERDICT_CONFIG = {
  BULLISH_ACCEPTANCE:  { icon: '🟢', cls: 'verdict--bullish',  label: 'Bullish Acceptance' },
  BEARISH_ACCEPTANCE:  { icon: '🔴', cls: 'verdict--bearish',  label: 'Bearish Acceptance' },
  UPPER_REJECTION:     { icon: '🔻', cls: 'verdict--reject-up', label: 'Upper Rejection' },
  LOWER_REJECTION:     { icon: '🔺', cls: 'verdict--reject-dn', label: 'Lower Rejection' },
  BALANCED_ROTATION:   { icon: '⚖️', cls: 'verdict--balanced', label: 'Balanced Rotation' },
  NO_TRADE:            { icon: '⛔', cls: 'verdict--notrade',  label: 'No Trade' },
};

const CONFIDENCE_TIERS = [
  { min: 75, label: 'STRONG',  cls: 'conf--strong' },
  { min: 60, label: 'MODERATE', cls: 'conf--moderate' },
  { min: 50, label: 'DEVELOPING', cls: 'conf--developing' },
  { min: 1,  label: 'WEAK',   cls: 'conf--weak' },
  { min: 0,  label: 'NONE',   cls: 'conf--none' },
];

// ── Format helpers ───────────────────────────────
const fmt = (n) => n != null ? `$${Number(n).toLocaleString()}` : '—';
const fmtPct = (n) => n != null ? `${n >= 0 ? '+' : ''}${Number(n).toFixed(2)}%` : '—';
const fmtTime = (iso) => {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' +
           d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + ' UTC';
  } catch { return iso; }
};

// ── Confidence bar ───────────────────────────────
function renderConfidence(score) {
  const tier = CONFIDENCE_TIERS.find(t => score >= t.min) || CONFIDENCE_TIERS[CONFIDENCE_TIERS.length - 1];
  const pct = Math.max(0, Math.min(100, score));
  return `
  <div class="vp-conf-bar-wrap">
    <div class="vp-conf-header">
      <span class="vp-conf-label">Setup Confidence</span>
      <span class="vp-conf-score ${tier.cls}">${score}% · ${tier.label}</span>
    </div>
    <div class="vp-conf-track">
      <div class="vp-conf-fill ${tier.cls}" style="width:${pct}%"></div>
    </div>
  </div>`;
}

// ── Evidence list ─────────────────────────────────
function renderEvidence(items, type) {
  if (!items || items.length === 0) return '';
  const config = {
    evidence:            { icon: '✓', cls: 'ev--for' },
    warnings:            { icon: '⚠', cls: 'ev--warn' },
    confirmation_needed: { icon: '→', cls: 'ev--pending' },
  };
  const cfg = config[type] || { icon: '·', cls: '' };
  const label = type === 'evidence' ? 'Evidence' : type === 'warnings' ? 'Warnings' : 'Confirmation Needed';
  return `
  <div class="vp-evidence-block ${cfg.cls}">
    <div class="vp-evidence-title">${label}</div>
    ${items.map(e => `<div class="vp-evidence-row"><span class="ev-icon">${cfg.icon}</span> ${e}</div>`).join('')}
  </div>`;
}

// ── Trade setup ──────────────────────────────────
function renderTradeSetup(setup, label, session) {
  const dir = setup.direction || 'LONG';
  const t2Label = dir === 'SHORT' ? 'VAL' : 'VAH';
  const rrClass1 = setup.rr_t1 != null ? `<span class="trade-rr">${setup.rr_t1}:1</span>` : '';
  const rrClass2 = setup.rr_t2 != null ? `<span class="trade-rr">${setup.rr_t2}:1</span>` : '';
  const isPending = setup.status === 'PENDING';
  const dimClass = isPending ? ' style="opacity:0.5"' : '';

  return `
  <div class="vp-trade-setup"${dimClass}>
    <div class="block-title">${label} — ${session || ''} Session</div>
    <div class="vp-trade-row" title="Suggested entry price">
      <span class="trade-label">Entry</span>
      <span class="trade-value trade-entry">${fmt(setup.entry)}</span>
    </div>
    <div class="vp-trade-row" title="First profit target — POC">
      <span class="trade-label">T1 — POC</span>
      <span class="trade-value trade-t1">${fmt(setup.t1)} ${rrClass1}</span>
    </div>
    <div class="vp-trade-row" title="Second profit target">
      <span class="trade-label">T2 — ${t2Label}</span>
      <span class="trade-value trade-t2">${fmt(setup.t2)} ${rrClass2}</span>
    </div>
    <div class="vp-trade-row" title="Stop loss">
      <span class="trade-label">Stop</span>
      <span class="trade-value trade-stop">${fmt(setup.stop_loss)}</span>
    </div>
    ${setup.invalidation != null ? `
    <div class="vp-trade-row" title="Invalidation level">
      <span class="trade-label">Invalidation</span>
      <span class="trade-value" style="color:#6b7280">${fmt(setup.invalidation)}</span>
    </div>` : ''}
  </div>`;
}

// ── Metrics bar ───────────────────────────────────
function renderMetricsBar(d) {
  return `
  <div class="vp-metrics-bar">
    <div class="vp-metric" title="Spot buy/sell delta from recent trades">
      <span class="met-label">Spot Δ</span>
      <span class="met-value ${d.spot_delta_pct >= 0 ? 't-green' : 't-red'}">${fmtPct(d.spot_delta_pct)}</span>
    </div>
    <div class="vp-metric" title="Perpetual futures taker buy/sell delta">
      <span class="met-label">Perp Δ</span>
      <span class="met-value ${d.perp_delta_pct >= 0 ? 't-green' : 't-red'}">${fmtPct(d.perp_delta_pct)}</span>
    </div>
    <div class="vp-metric" title="1-hour open interest change">
      <span class="met-label">OI Δ</span>
      <span class="met-value ${d.oi_change_pct >= 0 ? 't-green' : 't-red'}">${fmtPct(d.oi_change_pct)}</span>
    </div>
    <div class="vp-metric" title="Current funding rate">
      <span class="met-label">Funding</span>
      <span class="met-value">${fmtPct(d.funding_rate)}</span>
    </div>
    <div class="vp-metric" title="POC migration direction (15min)">
      <span class="met-label">POC</span>
      <span class="met-value ${d.developing_poc === 'rising' ? 't-green' : d.developing_poc === 'falling' ? 't-red' : ''}">${d.developing_poc || 'flat'}</span>
    </div>
  </div>`;
}

// ── Invalidation / Target bar ─────────────────────
function renderInvTarget(verdict) {
  if (!verdict || verdict.verdict === 'NO_TRADE' || verdict.verdict === 'BALANCED_ROTATION') return '';
  return `
  <div class="vp-inv-target">
    <div class="vp-it-row">
      <span class="it-label">Invalidation</span>
      <span class="it-value">${verdict.invalidation || '—'}</span>
    </div>
    ${verdict.target ? `
    <div class="vp-it-row">
      <span class="it-label">Target</span>
      <span class="it-value t-green">${verdict.target}</span>
    </div>` : ''}
  </div>`;
}

// ── Main render ──────────────────────────────────
function renderVPCard(raw, mountId = 'vp-card-mount') {
  const d = raw.vp_card;
  const verdict = d.verdict || {};
  const verdictKey = verdict.verdict || 'NO_TRADE';
  const vc = VERDICT_CONFIG[verdictKey] || VERDICT_CONFIG.NO_TRADE;
  const setups = d.trade_setups || [];
  const direction = d.direction || 'NEUTRAL';

  // Trade block — hidden on NO_TRADE / BALANCED_ROTATION
  let tradeBlock = '';
  const showTrade = verdictKey !== 'NO_TRADE' && verdictKey !== 'BALANCED_ROTATION';
  if (showTrade && setups.length === 2) {
    tradeBlock = `
  <div class="vp-trade-block">
    ${renderTradeSetup(setups[0], '🔵 LONG Setup', d.session)}
    ${renderTradeSetup(setups[1], '🔴 SHORT Setup', d.session)}
  </div>`;
  } else if (showTrade && setups.length > 0) {
    tradeBlock = `
  <div class="vp-trade-block">
    ${renderTradeSetup(setups[0], `${direction} Setup`, d.session)}
  </div>`;
  }

  const html = `
<div class="vp-card">

  <div class="vp-card___header">
    <span class="vp-cardtitle">Volume Profile Sentinel</span>
    <span class="vp-card___updated">Updated ${fmtTime(d.last_updated)}</span>
  </div>

  <!-- VERDICT BANNER -->
  <div class="vp-verdict-banner ${vc.cls}">
    <span class="verdict-icon">${vc.icon}</span>
    <div class="verdict-main">
      <span class="verdict-label">${vc.label}</span>
      <span class="verdict-status">${verdict.status || ''}</span>
    </div>
  </div>

  <div class="vp-verdict-summary">${verdict.summary || ''}</div>

  ${renderConfidence(verdict.confidence || 0)}

  <!-- EVIDENCE / WARNINGS -->
  ${renderEvidence(verdict.evidence, 'evidence')}
  ${renderEvidence(verdict.warnings, 'warnings')}
  ${renderEvidence(verdict.confirmation_needed, 'confirmation_needed')}

  ${renderInvTarget(verdict)}

  <!-- LEVELS GRID -->
  <div class="vp-levels">
    <div class="vp-level-item level-poc" title="Point of Control: busiest price, acts as magnet">
      <div class="level-label">POC</div>
      <div class="level-value">${fmt(d.poc)}</div>
      <div class="level-sub">Primary magnet</div>
    </div>
    <div class="vp-level-item level-vah" title="Value Area High: ceiling of fair value">
      <div class="level-label">VAH</div>
      <div class="level-value">${fmt(d.vah)}</div>
      <div class="level-sub">Touches: ${d.touch_count_vah || 0}</div>
    </div>
    <div class="vp-level-item level-val" title="Value Area Low: floor of fair value">
      <div class="level-label">VAL</div>
      <div class="level-value">${fmt(d.val)}</div>
      <div class="level-sub">Touches: ${d.touch_count_val || 0}</div>
    </div>
    <div class="vp-level-item level-hvn" title="High Volume Node: thick trading zone">
      <div class="level-label">HVN</div>
      <div class="level-value">${d.hvn_range ? '$' + d.hvn_range.replace('-', '–$') : '—'}</div>
      <div class="level-sub">Magnet zone</div>
    </div>
  </div>

  <!-- METRICS BAR -->
  ${renderMetricsBar(d)}

  ${tradeBlock}

  ${verdictKey === 'NO_TRADE' ? `
  <div class="vp-notrade-note">
    ⛔ <strong>NO TRADE</strong> — The system is withholding a trade recommendation because evidence is conflicting or insufficient. This is a feature, not a failure. Not trading is often the best trade.
  </div>` : ''}

  <div class="vp-links">
    <a class="vp-link-btn" href="https://aikeluargalee-tech.github.io/pipeline-dashboard-v3/market-regime/" target="_blank">↗ Market Regime</a>
  </div>

  <div id="vp-chart-container" class="vp-chart"></div>

</div>`;

  const mount = document.getElementById(mountId);
  if (mount) mount.innerHTML = html;

  if (raw.chart_data && raw.chart_data.bins) {
    renderVPChart(raw, 'vp-chart-container');
  }
}

// ── Fetch + render ───────────────────────────────
async function loadVPCard(mountId = 'vp-card-mount') {
  try {
    const res = await fetch(`${VP_JSON_PATH}?t=${Date.now()}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderVPCard(data, mountId);
  } catch (err) {
    const mount = document.getElementById(mountId);
    if (mount) mount.innerHTML =
      `<div class="vp-card" style="color:#f87171;padding:20px">VP card load failed: ${err.message}</div>`;
  }
}

loadVPCard();
setInterval(() => loadVPCard(), 60_000);
