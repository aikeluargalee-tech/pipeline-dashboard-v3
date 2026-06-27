// vp-card.js — Volume Profile V3.0 Card
// Reads vp_card.json, auto-computes shape/state, renders card

const VP_JSON_PATH = '../data/vp_card.json'; // adjust to your path

// ── Shape config ─────────────────────────────────
const SHAPE_CONFIG = {
  D: { cls: 'shape--D', label: 'Range (D)', desc: 'Sideways — buy low, sell high' },
  P: { cls: 'shape--P', label: 'P-Shape', desc: 'Bulls In Control — Follow' },
  b: { cls: 'shape--b', label: 'b-Shape', desc: 'Bears In Control — Follow' },
  B: { cls: 'shape--B', label: 'B-Shape', desc: 'Dual Auction — Respect Both POCs' },
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
  const map = {
    VERY_HIGH:  ['pill--very-high',  'VERY HIGH'],
    HIGH:       ['pill--high',       'HIGH'],
    REINFORCED: ['pill--reinforced', 'REINFORCED'],
    BASELINE:   ['pill--baseline',   'BASELINE'],
  };
  const [cls, label] = map[tier] || ['pill--baseline', tier];
  return `<span class="vp-pill ${cls}">${label}</span>`;
}

// ── Strategy bias pill ────────────────────────────
function biasPill(bias) {
  const map = {
    FADE:   ['pill--fade',   'FADE'],
    FOLLOW: ['pill--follow', 'FOLLOW'],
    WAIT:   ['pill--wait',   'WAIT'],
  };
  const [cls, label] = map[bias] || ['pill--wait', bias];
  return `<span class="vp-pill ${cls}">${label}</span>`;
}

// ── State pill ────────────────────────────────────
function statePill(state) {
  const map = {
    ACCEPTANCE:     ['pill--acceptance',     'ACCEPTANCE'],
    REJECTION_UP:   ['pill--rejection-up',   'REJECTION ↑'],
    REJECTION_DOWN: ['pill--rejection-down', 'REJECTION ↓'],
  };
  const [cls, label] = map[state] || ['pill--baseline', state];
  return `<span class="vp-pill ${cls}">${label}</span>`;
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
    ? `<span class="vp-pill pill--lockout">AMT LOCKOUT</span>`
    : `<span class="vp-pill pill--clear">AMT CLEAR</span>`;

  const html = `
<div class="vp-card">

  <div class="vp-card___header">
    <span class="vp-cardtitle">Volume Profile</span>
    <span class="vp-card___updated">Updated ${fmtTime(d.last_updated)}</span>
  </div>

  <div class="vp-shape-badge ${sc.cls}">
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
    <div class="vp-level-item level-poc">
      <div class="level-label">POC</div>
      <div class="level-value">${fmt(d.poc)}</div>
      <div class="level-sub">Primary magnet</div>
    </div>
    <div class="vp-level-item level-vah">
      <div class="level-label">VAH</div>
      <div class="level-value">${fmt(d.vah)}</div>
      <div class="level-sub">Touches: ${d.touch_count_vah}</div>
    </div>
    <div class="vp-level-item level-val">
      <div class="level-label">VAL</div>
      <div class="level-value">${fmt(d.val)}</div>
      <div class="level-sub">Touches: ${d.touch_count_val}</div>
    </div>
    <div class="vp-level-item level-hvn">
      <div class="level-label">HVN</div>
      <div class="level-value">${d.hvn_range ? '$' + String(d.hvn_range).replace('-', '–$') : '—'}</div>
      <div class="level-sub">Magnet zone</div>
    </div>
  </div>

  <div class="vp-trade-block">
    <div class="block-title">Trade Setup — ${d.session || 'N/A'} Session</div>
    <div class="vp-trade-row">
      <span class="trade-label">Entry</span>
      <span class="trade-value trade-entry">${fmt(d.entry_level)}</span>
    </div>
    <div class="vp-trade-row">
      <span class="trade-label">T1 — POC</span>
      <span class="trade-value trade-t1">
        ${fmt(d.t1)}
        ${d.rr_t1 ? `<span class="trade-rr">${d.rr_t1}:1</span>` : ''}
      </span>
    </div>
    <div class="vp-trade-row">
      <span class="trade-label">T2 — VAH</span>
      <span class="trade-value trade-t2">
        ${fmt(d.t2)}
        ${d.rr_t2 ? `<span class="trade-rr">${d.rr_t2}:1</span>` : ''}
      </span>
    </div>
    <div class="vp-trade-row">
      <span class="trade-label">Stop</span>
      <span class="trade-value trade-stop">${fmt(d.stop_loss)}</span>
    </div>
    <div class="vp-trade-row">
      <span class="trade-label">Size</span>
      <span class="trade-value trade-size">
        ${(d.size_recommendation || '—').replace('_', ' ')}
      </span>
    </div>
    <div class="vp-trade-row">
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

  // Render chart if chart_data present and renderVPChart is loaded
  if (raw.chart_data && raw.chart_data.bins && typeof renderVPChart === 'function') {
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
const _vpRefreshId = setInterval(() => loadVPCard(), 60_000);

document.addEventListener('visibilitychange', () => {
  if (document.hidden) clearInterval(_vpRefreshId);
});
window.addEventListener('beforeunload', () => {
  clearInterval(_vpRefreshId);
});
