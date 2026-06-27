// vp-chart.js — Volume Profile Histogram (Canvas)
// Reads chart_data from vp_card.json, renders as horizontal bar chart

const VP_CHART_COLORS = {
  poc:    { bar: '#facc15', text: '#facc15', alpha: 0.9 },
  vah:    { bar: '#f87171', text: '#f87171', alpha: 0.7 },
  val:    { bar: '#34d399', text: '#34d399', alpha: 0.7 },
  hvn:    { bar: '#a78bfa', text: '#a78bfa', alpha: 0.6 },
  lvn:    { bar: '#374151', text: '#6b7280', alpha: 0.3 },
  normal: { bar: '#4b5563', text: '#9ca3af', alpha: 0.4 },
};

function renderVPChart(chartData, canvasId = 'vp-chart-canvas') {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;

  if (canvas.clientWidth < 1) {
    requestAnimationFrame(() => renderVPChart(chartData, canvasId));
    return;
  }

  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;

  const { bins, bin_size, max_volume } = chartData;
  const n = bins.length;
  if (n === 0) return;

  // Layout — generous right padding for reference labels
  const W = canvas.clientWidth;
  const pad = { top: 12, right: 130, bottom: 12, left: 8 };
  const chartW = W - pad.left - pad.right;
  const gap = 2;
  const barH = Math.max(3, Math.floor((280 / n)) - gap); // cap chart ~280px tall
  const chartH = n * (barH + gap);
  const H = chartH + pad.top + pad.bottom;

  // Resize for HiDPI
  canvas.width = W * dpr;
  canvas.height = H * dpr;
  canvas.style.width = W + 'px';
  canvas.style.height = H + 'px';
  ctx.scale(dpr, dpr);

  // Clear
  ctx.fillStyle = '#111827';
  ctx.fillRect(0, 0, W, H);

  // Helper: price → y position
  const yForPrice = (p) => {
    if (n === 0) return pad.top;
    const topPrice = bins[0].price + bin_size / 2;
    const botPrice = bins[n - 1].price - bin_size / 2;
    const frac = (topPrice - p) / (topPrice - botPrice);
    return pad.top + frac * chartH;
  };

  // Collect reference lines (VAH/VAL/POC)
  const refLines = [];
  for (const bin of bins) {
    if (bin.type === 'vah' || bin.type === 'val' || bin.type === 'poc') {
      if (bin.price == null) continue;
      const y = yForPrice(bin.price + bin_size / 2);
      refLines.push({ y, type: bin.type, price: bin.price });
    }
  }

  // Dedupe and draw reference lines with staggered labels
  const seen = {};
  const labelSlots = []; // track used y-positions for labels
  for (const r of refLines) {
    if (seen[r.type]) continue;
    seen[r.type] = true;
    const c = VP_CHART_COLORS[r.type];

    // Dashed line across chart area
    ctx.strokeStyle = c.text;
    ctx.globalAlpha = 0.35;
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 5]);
    ctx.beginPath();
    ctx.moveTo(pad.left, r.y);
    ctx.lineTo(pad.left + chartW, r.y);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.globalAlpha = 1;

    // Label position — stagger if too close to another label
    let labelY = r.y - 2;
    const minGap = 13;
    let overlaps = true;
    while (overlaps) {
      overlaps = false;
      for (const slot of labelSlots) {
        if (Math.abs(labelY - slot) < minGap) {
          labelY = slot + minGap;
          overlaps = true;
          break;
        }
      }
    }
    labelSlots.push(labelY);

    // Label background
    const label = r.type.toUpperCase() + ' $' + (r.price != null ? r.price.toLocaleString() : '—');
    ctx.font = 'bold 10px monospace';
    const tw = ctx.measureText(label).width;
    const lx = W - tw - 10;
    ctx.fillStyle = '#111827';
    ctx.globalAlpha = 0.85;
    ctx.fillRect(lx - 3, labelY - 9, tw + 6, 13);
    ctx.globalAlpha = 1;

    // Label text
    ctx.fillStyle = c.text;
    ctx.textAlign = 'left';
    ctx.fillText(label, lx, labelY + 1);
  }

  // Draw bars
  for (let i = 0; i < n; i++) {
    const bin = bins[i];
    const c = VP_CHART_COLORS[bin.type] || VP_CHART_COLORS.normal;
    const barW = Math.max(2, (bin.volume / max_volume) * chartW);
    const x = pad.left;
    const y = pad.top + i * (barH + gap);

    // Bar
    ctx.fillStyle = c.bar;
    ctx.globalAlpha = c.alpha;
    ctx.fillRect(x, y, barW, barH);
    ctx.globalAlpha = 1;

    // Volume text on wide bars only
    if (barW > 55) {
      ctx.fillStyle = '#fff';
      ctx.font = '9px monospace';
      ctx.textAlign = 'left';
      ctx.fillText(bin.volume.toLocaleString(), x + 4, y + barH - 2);
    }
  }

  // Price labels on left — only every 5th + key levels
  ctx.textAlign = 'left';
  ctx.font = '8px monospace';
  for (let i = 0; i < n; i++) {
    const isKey = bins[i].type !== 'normal' && bins[i].type !== 'lvn';
    if (i % 5 === 0 || isKey) {
      const y = pad.top + i * (barH + gap) + barH / 2 + 3;
      ctx.fillStyle = isKey
        ? (VP_CHART_COLORS[bins[i].type] || VP_CHART_COLORS.normal).text
        : '#6b7280';
      ctx.fillText('$' + (bins[i].price != null ? bins[i].price.toLocaleString() : '—'), 4, y);
    }
  }
}
