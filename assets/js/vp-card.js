// vp-card.js — Volume Profile V3.0 Card
// Reads vp_card.json, auto-computes shape/state, renders card

const VP_JSON_PATH = '../data/vp_card.json'; // adjust to your path

// ── Shape config ─────────────────────────────────
const SHAPE_CONFIG = {
  D: { cls: 'shape--D', label: 'Range (D)',    desc: 'Sideways — buy low, sell high' },
  P: { cls: 'shape--P', label: 'Trend Up (P)',  desc: 'Bulls in control — follow the trend' },
  b: { cls: 'shape--b', label: 'Trend Down (b)', desc: 'Bears in control — don\'t fight it' },
  B: { cls: 'shape--B', label: 'Dual Zone (B)',  desc: 'Two trading zones — wait for direction' },
};

// ── Auto-compute shape from pipeline data ─────────
function computeShape(d) {
  const { btc_price, vah, val, consecutive_closes_outside_va: closes } = d;
  if (closes >= 2 && btc_price > vah) return 'P';
  if (closes >= 2 && btc_price < val) return 'b';
  if (btc_price >= val && btc_price <= vah && closes < 2) return 'D';
  return d.shape || 'D'; // fallback to pipeline value
}

// ── Auto-compute accept/reject state ──────────────
function computeState(d) {
  const closes = d.consecutive_closes_outside_va;
  if (closes >= 2 && d.btc_price > d.vah) return 'REJECTION_UP';
  if (closes >= 2 && d.btc_price < d.val) return 'REJECTION_DOWN';
  return 'ACCEPTANCE';
}

// ── Probability tier pill ─────────────────────────
function probPill(tier) {
  const tips = {
    VERY_HIGH:  'Very strong — multiple indicators aligned',
    HIGH:       'Strong signal confidence',
    REINFORCED: 'Reinforced by additional factors',
    BASELINE:   'Standard signal confidence',
  };
  const map = {
    VERY_HIGH:  ['pill--very-high',  'VERY HIGH'],
    HIGH:       ['pill--high',       'HIGH'],
    REINFORCED: ['pill--reinforced', 'REINFORCED'],
    BASELINE:   ['pill--baseline',   'BASELINE'],
  };
  const [cls, label] = map[tier] || ['pill--baseline', tier];
  const tip = tips[tier] || '';
  return `<span class="vp-pill ${cls}" title="${tip}">${label}</span>`;
}

// ── Strategy bias pill ────────────────────────────
function biasPill(bias) {
  const tips = {
    FADE:   'Fade the extremes — buy at VAL, sell at VAH (range strategy)',
    FOLLOW: 'Follow the trend — buy pullbacks in uptrend, sell bounces in downtrend',
    WAIT:   'No clear signal — wait for confirmation before entering',
  };
  const map = {
    FADE:   ['pill--fade',   'FADE'],
    FOLLOW: ['pill--follow', 'FOLLOW'],
    WAIT:   ['pill--wait',   'WAIT'],
  };
  const [cls, label] = map[bias] || ['pill--wait', bias];
  const tip = tips[bias] || '';
  return `<span class="vp-pill ${cls}" title="${tip}">${label}</span>`;
}

// ── State pill ────────────────────────────────────
function statePill(state) {
  const tips = {
    ACCEPTANCE:     'Price is inside Value Area — normal, no breakout',
    REJECTION_UP:   'Price broke above VAH and stayed there — bullish breakout',
    REJECTION_DOWN: 'Price broke below VAL and stayed there — bearish breakdown',
  };
  const map = {
    ACCEPTANCE:     ['pill--acceptance',     'ACCEPTANCE'],
    REJECTION_UP:   ['pill--rejection-up',   'REJECTION ↑'],
    REJECTION_DOWN: ['pill--rejection-down', 'REJECTION ↓'],
  };
  const [cls, label] = map[state] || ['pill--baseline', state];
  const tip = tips[state] || '';
  return `<span class="vp-pill ${cls}" title="${tip}">${label}</span>`;
}

// ── Format price ──────────────────────────────────
const fmt = (n) => n ? `$${Number(n).toLocaleString()}` : '—';
const fmtTime = (iso) => {
  try {
    return new Date(iso).toLocaleTimeString([], {
      hour: '2-digit', minute: '2-digit'
    }) + ' UTC';
  } catch { return iso; }
};

// ── Render card ───────────────────────────────────
function renderVPCard(raw, mountId = 'vp-card-mount') {
  const d = raw.vp_card;
  const shape = computeShape(d);
  const state = computeState(d);
  const sc = SHAPE_CONFIG[shape];
  const lockoutPill = d.amt_lockout
    ? `<span class="vp-pill pill--lockout" title="Aggressive Market Tape bot active — trade with caution">AMT LOCKOUT</span>`
    : `<span class="vp-pill pill--clear" title="AMT bot not active — normal trading">AMT CLEAR</span>`;

  const html = `
<div class="vp-card">

  <div class="vp-card___header">
    <span class="vp-cardtitle">Volume Profile</span>
    <span class="vp-card___updated">Updated ${fmtTime(d.last_updated)}</span>
  </div>

  <div class="vp-shape-badge ${sc.cls}" title="Market structure: ${sc.label} — ${sc.desc}">
    <span class="shape-label">${sc.label}</span>
    <span class="shape-desc">${sc.desc}</span>
  </div>

  <div class="vp-state-row">
    ${statePill(state)}
    ${biasPill(d.strategy_bias)}
    ${probPill(d.probability_tier)}
    ${lockoutPill}
  </div>

  <div class="vp-levels">
    <div class="vp-level-item level-poc"
         title="Point of Control: the busiest price. Acts as a magnet — price often returns here.">
      <div class="level-label">POC</div>
      <div class="level-value">${fmt(d.poc)}</div>
      <div class="level-sub">Primary magnet</div>
    </div>
    <div class="vp-level-item level-vah"
         title="Value Area High: ceiling of fair value. Resistance and bullish breakout point.">
      <div class="level-label">VAH</div>
      <div class="level-value">${fmt(d.vah)}</div>
      <div class="level-sub">Touches: ${d.touch_count_vah}</div>
    </div>
    <div class="vp-level-item level-val"
         title="Value Area Low: floor of fair value. Support and bearish breakdown point.">
      <div class="level-label">VAL</div>
      <div class="level-value">${fmt(d.val)}</div>
      <div class="level-sub">Touches: ${d.touch_count_val}</div>
    </div>
    <div class="vp-level-item level-hvn"
         title="High Volume Node: thick trading zone. Strong support or resistance.">
      <div class="level-label">HVN</div>
      <div class="level-value">${d.hvn_range ? '$' + d.hvn_range.replace('-', '–$') : '—'}</div>
      <div class="level-sub">Magnet zone</div>
    </div>
  </div>

  <div class="vp-trade-block">
    <div class="block-title">Trade Setup — ${d.session || ''} Session</div>
    <div class="vp-trade-row" title="Suggested entry price for the current strategy">
      <span class="trade-label">Entry</span>
      <span class="trade-value trade-entry">${fmt(d.entry_level)}</span>
    </div>
    <div class="vp-trade-row" title="First profit target — POC level (primary magnet)">
      <span class="trade-label">T1 — POC</span>
      <span class="trade-value trade-t1">
        ${fmt(d.t1)}
        ${d.rr_t1 ? `<span class="trade-rr">${d.rr_t1}:1</span>` : ''}
      </span>
    </div>
    <div class="vp-trade-row" title="Second profit target — VAH level (value area ceiling)">
      <span class="trade-label">T2 — VAH</span>
      <span class="trade-value trade-t2">
        ${fmt(d.t2)}
        ${d.rr_t2 ? `<span class="trade-rr">${d.rr_t2}:1</span>` : ''}
      </span>
    </div>
    <div class="vp-trade-row" title="Stop loss — exit trade if price reaches this level">
      <span class="trade-label">Stop</span>
      <span class="trade-value trade-stop">${fmt(d.stop_loss)}</span>
    </div>
    <div class="vp-trade-row" title="Recommended position size for this setup">
      <span class="trade-label">Size</span>
      <span class="trade-value trade-size">
        ${(d.size_recommendation || '—').replace('_', ' ')}
      </span>
    </div>
    <div class="vp-trade-row" title="If price reaches this level, the trade thesis is invalid">
      <span class="trade-label">Invalidation</span>
      <span class="trade-value" style="color:#6b7280">${fmt(d.invalidation)}</span>
    </div>
  </div>

  <div class="vp-links">
    <a class="vp-link-btn" href="#amt-status-card">↗ AMT Status + VP×AMT Table</a>
    <a class="vp-link-btn" href="#liquidity-card">↗ Liquidity — CVD/Absorption</a>
  </div>

  <canvas id="vp-chart-canvas" class="vp-chart" width="600" height="400"></canvas>

</div>`;

  const mount = document.getElementById(mountId);
  if (mount) mount.innerHTML = html;

  // Render chart if chart_data present
  if (raw.chart_data && raw.chart_data.bins) {
    renderVPChart(raw.chart_data, 'vp-chart-canvas');
  }
}

// ── Fetch + render ────────────────────────────────
async function loadVPCard(mountId = 'vp-card-mount') {
  try {
    const res = await fetch(`${VP_JSON_PATH}?t=${Date.now()}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderVPCard(data, mountId);
  } catch (err) {
    const mount = document.getElementById(mountId);
    if (mount) mount.innerHTML =
      `<div class="vp-card" style="color:#f87171">VP card load failed: ${err.message}</div>`;
  }
}

// ── Auto-refresh every 60s ────────────────────────
loadVPCard();
setInterval(() => loadVPCard(), 60_000);
