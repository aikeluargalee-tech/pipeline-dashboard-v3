// vp-chart.js — Volume Profile Histogram (HTML/CSS Div-based)
// Reads chart_data and vp_card from vp_card.json, renders as vertical column chart

const TYPE_PRIORITY = {
  poc: 5,
  vah: 4,
  val: 3,
  hvn: 2,
  normal: 1,
  lvn: 0
};

function renderVPChart(raw, containerId = 'vp-chart-container') {
  const container = document.getElementById(containerId);
  if (!container) return;

  const chartData = raw.chart_data;
  const vpCard = raw.vp_card;
  if (!chartData || !chartData.bins || chartData.bins.length === 0) {
    container.innerHTML = `<div style="padding: 12px; color: #6b7280;">No chart bins available</div>`;
    return;
  }

  const { bins, bin_size } = chartData;

  // Sort bins ascending by price (left = lowest price, right = highest price)
  const sortedBins = [...bins].sort((a, b) => Number(a.price) - Number(b.price));
  const minPrice = Number(sortedBins[0].price);
  const maxPrice = Number(sortedBins[sortedBins.length - 1].price);
  const range = (maxPrice - minPrice) || 1;

  // Compact — Group bins into a maximum number of bars (e.g., 35) to keep it clean
  const maxBars = 35;
  const step = Math.max(1, Math.ceil(sortedBins.length / maxBars));
  const groupedBars = [];

  for (let i = 0; i < sortedBins.length; i += step) {
    let stepVol = 0;
    let stepPrice = 0;
    let highestPriorityType = 'lvn';
    let highestPriority = -1;

    for (let j = 0; j < step && (i + j) < sortedBins.length; j++) {
      const bin = sortedBins[i + j];
      const vol = Number(bin.volume);
      if (vol > stepVol) {
        stepVol = vol;
        stepPrice = Number(bin.price);
      }
      
      const type = bin.type || 'normal';
      const priority = TYPE_PRIORITY[type] || 0;
      if (priority > highestPriority) {
        highestPriority = priority;
        highestPriorityType = type;
      }
    }

    groupedBars.push({
      volume: stepVol,
      price: stepPrice,
      type: highestPriorityType
    });
  }

  // Find max volume in grouped bars to normalize height
  const vols = groupedBars.map(b => b.volume).filter(v => Number.isFinite(v) && v > 0);
  const maxVol = vols.length ? Math.max(...vols) : 1;

  // Render NOW marker/pointer if btc_price is within range
  const btcNow = vpCard?.btc_price || null;
  const getBoundedPct = (price) => {
    const rawPct = ((Number(price) - minPrice) / range) * 100;
    return Math.max(3, Math.min(97, rawPct));
  };

  let nowHtml = '';
  if (btcNow && btcNow >= minPrice && btcNow <= maxPrice) {
    const nowPct = getBoundedPct(btcNow);
    nowHtml = `
      <div class="vp-now-marker" style="left: ${nowPct}%">
        ▼ NOW ($${Math.round(btcNow).toLocaleString()})
      </div>
    `;
  }

  let chartHtml = `
    <div class="vp-chart-container-horizontal">
      <div class="vp-now-track-horizontal">${nowHtml}</div>
      <div class="vp-chart-horizontal">
  `;

  // Draw vertical column bars
  for (const bar of groupedBars) {
    const pct = Math.max(2, (bar.volume / maxVol) * 100);
    const barClass = bar.type; // poc, vah, val, hvn, lvn, normal
    chartHtml += `
      <div class="vp-bar-horizontal ${barClass}" style="height: ${pct}%" title="$${bar.price.toLocaleString()} — Vol: ${bar.volume.toFixed(2)}"></div>
    `;
  }

  chartHtml += `
    </div>
  `;

  // Position levels: VAH, VAL, POC
  const labels = [];
  if (vpCard?.val != null) {
    labels.push({ name: 'VAL', pct: getBoundedPct(vpCard.val), colorClass: 'val', price: vpCard.val });
  }
  if (vpCard?.poc != null) {
    labels.push({ name: 'POC', pct: getBoundedPct(vpCard.poc), colorClass: 'poc', price: vpCard.poc });
  }
  if (vpCard?.vah != null) {
    labels.push({ name: 'VAH', pct: getBoundedPct(vpCard.vah), colorClass: 'vah', price: vpCard.vah });
  }

  // Sort labels left-to-right to staggered assignment
  labels.sort((a, b) => a.pct - b.pct);

  // Stagger overlapping labels horizontally (using vertical rows)
  const minPctGap = 16;
  const rows = [];
  let maxRow = 0;

  for (let i = 0; i < labels.length; i++) {
    const lbl = labels[i];
    let assignedRow = 0;
    while (true) {
      let overlap = false;
      const rowPcts = rows[assignedRow] || [];
      for (const pct of rowPcts) {
        if (Math.abs(lbl.pct - pct) < minPctGap) {
          overlap = true;
          break;
        }
      }
      if (!overlap) break;
      assignedRow++;
    }
    if (!rows[assignedRow]) rows[assignedRow] = [];
    rows[assignedRow].push(lbl.pct);
    lbl.row = assignedRow;
    if (assignedRow > maxRow) maxRow = assignedRow;
  }

  // Nudge: labels on lower rows offset right so text doesn't overlap row-0 labels on mobile
  for (const lbl of labels) {
    lbl.nudgeRight = 0;
    if (lbl.row > 0) {
      const row0Pcts = rows[0] || [];
      for (const pct of row0Pcts) {
        const gapPct = lbl.pct - pct;
        if (gapPct > 0 && gapPct < minPctGap + 6) {
          lbl.nudgeRight = Math.round((minPctGap + 6 - gapPct) * 3.5);
          break;
        }
      }
    }
  }

  // Render labels row
  chartHtml += `
    <div class="vp-labels-row-horizontal" style="height: ${38 + maxRow * 16}px">
  `;

  for (const lbl of labels) {
    const dashedLineHeight = 116 + lbl.row * 16;
    const nudgeStyle = lbl.nudgeRight ? `padding-left: ${lbl.nudgeRight}px` : '';
    chartHtml += `
      <div class="vp-x-label ${lbl.colorClass}" style="left: ${lbl.pct}%; top: ${lbl.row * 16}px; ${nudgeStyle}">
        <div class="vp-line-dashed ${lbl.colorClass}-line" style="height: ${dashedLineHeight}px"></div>
        <span class="vp-label-title">${lbl.name}</span><br>$${Number(lbl.price).toLocaleString()}
      </div>
    `;
  }

  chartHtml += `
      </div>
    </div>
  `;

  // Info label
  const totalVol = bins.reduce((sum, b) => sum + Number(b.volume), 0);
  chartHtml += `
    <div class="vp-chart-info-label">
      ${bins.length} bins · bin size $${bin_size} · ${(totalVol / 1000).toFixed(1)}K total volume
    </div>
  `;

  container.innerHTML = chartHtml;
}
