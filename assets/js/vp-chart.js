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

  // Layout
  const W = canvas.clientWidth;
  const H = Math.max(300, n * 16); // dynamic height per bin count
  const pad = { top: 12, right: 70, bottom: 12, left: 8 };
  const chartW = W - pad.left - pad.right;
  const chartH = H - pad.top - pad.bottom;
  const barH = Math.max(6, Math.floor(chartH / n) - 1);

  // Resize for HiDPI
  canvas.width = W * dpr;
  canvas.height = H * dpr;
  canvas.style.width = W + 'px';
  canvas.style.height = H + 'px';
  ctx.scale(dpr, dpr);

  // Clear
  ctx.fillStyle = '#111827';
  ctx.fillRect(0, 0, W, H);

  // VAH/VAL/POC horizontal reference lines
  const yForPrice = (p) => {
    if (n === 0) return pad.top;
    const topPrice = bins[0].price + bin_size / 2;
    const botPrice = bins[n - 1].price - bin_size / 2;
    const frac = (topPrice - p) / (topPrice - botPrice);
    return pad.top + frac * chartH;
  };

  // Draw reference lines
  const refLines = [];
  for (const bin of bins) {
    if (bin.type === 'vah' || bin.type === 'val' || bin.type === 'poc') {
      if (bin.price == null) continue;
      const y = yForPrice(bin.price + bin_size / 2);
      refLines.push({ y, type: bin.type, price: bin.price });
    }
  }

  // Dedupe (multiple bins may have same type)
  const seen = {};
  for (const r of refLines) {
    if (seen[r.type]) continue;
    seen[r.type] = true;
    const c = VP_CHART_COLORS[r.type];
    ctx.strokeStyle = c.text;
    ctx.globalAlpha = 0.5;
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(pad.left, r.y);
    ctx.lineTo(pad.left + chartW, r.y);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.globalAlpha = 1;

    // Label
    ctx.fillStyle = c.text;
    ctx.font = '10px monospace';
    ctx.textAlign = 'right';
    ctx.fillText(
      r.type.toUpperCase() + ' $' + (r.price != null ? r.price.toLocaleString() : '—'),
      W - 4, r.y - 3
    );
  }

  // Draw bars
  for (let i = 0; i < n; i++) {
    const bin = bins[i];
    const c = VP_CHART_COLORS[bin.type] || VP_CHART_COLORS.normal;
    const barW = Math.max(2, (bin.volume / max_volume) * chartW);
    const x = pad.left;
    const y = pad.top + i * (barH + 1);

    // Bar
    ctx.fillStyle = c.bar;
    ctx.globalAlpha = c.alpha;
    ctx.fillRect(x, y, barW, barH);
    ctx.globalAlpha = 1;

    // Volume text on bar
    if (barW > 40) {
      ctx.fillStyle = '#fff';
      ctx.font = '9px monospace';
      ctx.textAlign = 'left';
      ctx.fillText(bin.volume.toLocaleString(), x + 4, y + barH - 3);
    }
  }

  // Price labels on Y axis
  ctx.textAlign = 'left';
  ctx.font = '9px monospace';
  for (let i = 0; i < n; i++) {
    if (i % 3 === 0 || bins[i].type !== 'normal') {
      const y = pad.top + i * (barH + 1) + barH / 2 + 3;
      ctx.fillStyle = bins[i].type !== 'normal'
        ? (VP_CHART_COLORS[bins[i].type] || VP_CHART_COLORS.normal).text
        : '#6b7280';
      ctx.fillText('$' + (bins[i].price != null ? bins[i].price.toLocaleString() : '—'), 4, y);
    }
  }
}
