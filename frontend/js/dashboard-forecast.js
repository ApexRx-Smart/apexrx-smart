'use strict';
/* Forecasting screen for both dashboards: a control-room view of stock and demand.
 * Everything here is example data generated in the browser. Nothing reads or sends
 * the signed-in organization's data, and the page says so. A real forecast needs
 * order history collected during the pilot: replace build() and the sample helpers
 * with an API call, and the charts keep working.
 *
 *   DashForecast.mount(root, { role, t, locale })
 *
 * Charts are plain SVG. The site's Content-Security-Policy forbids inline handlers,
 * so hover and controls use delegated listeners on root. */
(function (global) {
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmt = n => Math.round(n).toLocaleString('en-US');
  const short = n => n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : n >= 1e4 ? Math.round(n / 1e3) + 'k' : n >= 1e3 ? (n / 1e3).toFixed(1) + 'k' : String(Math.round(n));

  /* Sample catalogue: name, class, monthly boxes at a pharmacy, months of stock on hand. */
  const ITEMS = [
    ['Amoxicillin 500mg B/20 Capsules', 'Antibiotic', 142, 1.5],
    ['Paracetamol 500mg B/30 Tablets', 'Analgesic', 236, 3.4],
    ['Artemether/Lumefantrine 20/120mg B/24', 'Antimalarial', 118, 0.8],
    ['Metformin 500mg B/60 Tablets', 'Antidiabetic', 64, 2.2],
    ['Amlodipine 5mg B/30 Tablets', 'Antihypertensive', 72, 4.6],
    ['ORS B/25 Sachets', 'Rehydration', 96, 7.5],
    ['Ibuprofen 400mg B/30 Tablets', 'Analgesic', 88, 2.8],
    ['Ciprofloxacin 500mg B/10 Tablets', 'Antibiotic', 54, 1.2],
    ['Salbutamol 100mcg B/1 Inhaler', 'Respiratory', 31, 5.1],
    ['Insulin Glargine 100IU/ml B/1 Pen', 'Antidiabetic', 18, 1.9],
    ['Enalapril 10mg B/30 Tablets', 'Antihypertensive', 46, 3.1],
    ['Albendazole 400mg B/2 Tablets', 'Anthelmintic', 39, 6.4]
  ];
  // Colour follows the class, never its rank (validated against the panel surface).
  const CLASS_ORDER = ['Antibiotic', 'Analgesic', 'Antimalarial', 'Antidiabetic', 'Antihypertensive'];
  const SEASON = {
    Antimalarial: [.9, 1, 1.25, 1.4, 1.3, 1, .75, .7, .8, 1.05, 1.3, 1.2],
    Antibiotic: [1.05, 1, 1.05, 1.15, 1.1, .95, .85, .85, .95, 1.05, 1.1, 1.1],
    Respiratory: [1, 1, 1.1, 1.2, 1.15, 1, .9, .85, .9, 1.05, 1.15, 1.1],
    Rehydration: [.95, 1, 1.1, 1.2, 1.1, .9, .85, .9, .95, 1.05, 1.1, 1.05]
  };
  const flat = new Array(12).fill(1);
  const hash = s => { let h = 7; for (const c of s) h = (h * 31 + c.charCodeAt(0)) % 9973; return h; };
  const noise = (seed, i) => { const x = Math.sin(seed * 12.9898 + i * 78.233) * 43758.5453; return x - Math.floor(x); };
  const monthAt = offset => { const d = new Date(); d.setDate(1); d.setMonth(d.getMonth() + offset); return d; };

  /* Status of a month from its stock coverage. Colour always comes with a label. */
  const coverStatus = months => months < 1 ? 'critical' : months < 2 ? 'alert' : months <= 6 ? 'good' : 'over';
  const STATUS_LABEL = { critical: 'Critical', alert: 'Alert', good: 'Good', over: 'Overstock' };
  const STATUS_ICON = { critical: '!', alert: '▲', good: '✓', over: '＋' };

  function build(role, index, horizon) {
    const [name, cls, base0, cover0] = ITEMS[index];
    const scale = role === 'supplier' ? 16 : 1, base = base0 * scale, seed = hash(name);
    const season = SEASON[cls] || flat;
    const at = (offset, jitter) => {
      const d = monthAt(offset), m = d.getMonth();
      const trend = 1 + .006 * (offset + 11);
      return Math.round(base * season[m] * trend * (1 + jitter * (noise(seed, offset + 40) - .5)));
    };
    const hist = []; for (let i = -11; i <= 0; i++) hist.push({ d: monthAt(i), v: at(i, .22) });
    const amc = hist.slice(-6).reduce((t, x) => t + x.v, 0) / 6;
    const fc = []; for (let i = 1; i <= 12; i++) { const v = at(i, 0), spread = .1 + .018 * i; fc.push({ d: monthAt(i), v, lo: v * (1 - spread), hi: v * (1 + spread) }); }
    const stock = Math.round(base * cover0);
    // Planned deliveries every two months, a little above or below what is needed.
    const refill = 1.75 + noise(seed, 5) * .65;
    const shipments = [1, 3, 5, 7, 9, 11].map((m, i) => ({ m, qty: Math.round(amc * refill), late: i === 0 && noise(seed, 3) > .55, po: 'PO-' + (2300 + seed % 600 + i * 7) }));
    const expiries = [
      { m: 2, qty: Math.round(base * .22), batch: name.slice(0, 3).toUpperCase() + '-' + (2401 + seed % 90) },
      { m: 5, qty: Math.round(base * .35), batch: name.slice(0, 3).toUpperCase() + '-' + (2510 + seed % 80) }
    ];
    // Project stock forward: demand and expiries take away, shipments add.
    const proj = []; let level = stock;
    fc.forEach((f, i) => {
      const m = i + 1;
      shipments.filter(s => s.m === m).forEach(s => { level += s.qty; });
      expiries.filter(e => e.m === m).forEach(e => { level -= e.qty; });
      level = Math.max(0, level - f.v);
      proj.push({ d: f.d, v: level, stock: level, cover: amc ? level / amc : 0 });
    });
    const past = []; for (let i = -5; i <= 0; i++) past.push({ d: monthAt(i), v: Math.round(stock * (1 + (-i) * .13 + (noise(seed, i + 9) - .5) * .16)) });
    past[past.length - 1].v = stock;
    const statusFirst = proj.findIndex(p => p.cover < 2);
    return { name, cls, hist, fc, amc, stock, cover: amc ? stock / amc : 0, shipments, expiries, proj, past, reorderAt: statusFirst, minLevel: amc * 2, horizon };
  }

  function portfolio(role) {
    return ITEMS.map((_, i) => build(role, i, 12)).map(b => {
      const next = b.fc[0].v, gap = Math.max(0, Math.round(next * 2 - b.stock));
      return { ...b, next, gap, st: coverStatus(b.cover) };
    });
  }

  /* District demand for the supplier view: approximate positions on a tile grid,
   * one tile per district, so the country reads at a glance without map files. */
  const DISTRICTS = [
    ['Rubavu', 0, 0, 'West'], ['Nyabihu', 1, 0, 'West'], ['Musanze', 2, 0, 'North'], ['Burera', 3, 0, 'North'], ['Gicumbi', 4, 0, 'North'], ['Nyagatare', 5, 0, 'East'],
    ['Rutsiro', 0, 1, 'West'], ['Ngororero', 1, 1, 'West'], ['Gakenke', 2, 1, 'North'], ['Rulindo', 3, 1, 'North'], ['Gasabo', 4, 1, 'Kigali'], ['Gatsibo', 5, 1, 'East'],
    ['Karongi', 0, 2, 'West'], ['Muhanga', 1, 2, 'South'], ['Kamonyi', 2, 2, 'South'], ['Nyarugenge', 3, 2, 'Kigali'], ['Kicukiro', 4, 2, 'Kigali'], ['Rwamagana', 5, 2, 'East'], ['Kayonza', 6, 2, 'East'],
    ['Nyamasheke', 0, 3, 'West'], ['Ruhango', 1, 3, 'South'], ['Nyanza', 2, 3, 'South'], ['Bugesera', 4, 3, 'East'], ['Ngoma', 5, 3, 'East'], ['Kirehe', 6, 3, 'East'],
    ['Rusizi', 0, 4, 'West'], ['Nyamagabe', 1, 4, 'South'], ['Huye', 2, 4, 'South'], ['Gisagara', 3, 4, 'South'], ['Nyaruguru', 2, 5, 'South']
  ];
  const districtDemand = () => DISTRICTS.map(([n, x, y, p]) => {
    const urban = p === 'Kigali' ? 3.1 : ['Huye', 'Musanze', 'Rubavu', 'Rwamagana'].includes(n) ? 1.7 : 1;
    return { n, x, y, p, v: Math.round((180 + noise(hash(n), 2) * 320) * urban) };
  });

  /* ------------------------------------------------------------------ charts */
  function niceMax(v) { const p = 10 ** Math.floor(Math.log10(v || 1)), n = v / p; return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p; }

  function lineChart(b, horizon, c) {
    const W = 760, H = 290, L = 46, R = 14, T = 16, B = 30;
    const future = b.proj.slice(0, horizon), all = [...b.past, ...future];
    const max = niceMax(Math.max(...all.map(p => p.v), b.minLevel) * 1.1);
    const x = i => L + i * (W - L - R) / (all.length - 1), y = v => T + (1 - v / max) * (H - T - B);
    const line = (pts, off) => pts.map((p, i) => `${i ? 'L' : 'M'}${x(i + off).toFixed(1)} ${y(p.v).toFixed(1)}`).join('');
    const nowI = b.past.length - 1;
    const fut = [b.past[nowI], ...future];
    const up = v => v * 1.12, dn = v => v * .88;
    const band = fut.map((p, i) => `${i ? 'L' : 'M'}${x(i + nowI).toFixed(1)} ${y(Math.min(max, up(p.v))).toFixed(1)}`).join('') +
      fut.slice().reverse().map((p, i) => `L${x(nowI + fut.length - 1 - i).toFixed(1)} ${y(dn(p.v)).toFixed(1)}`).join('') + 'Z';
    const grid = [0, .25, .5, .75, 1].map(f => `<line x1="${L}" x2="${W - R}" y1="${y(max * f)}" y2="${y(max * f)}" class="g"/><text x="${L - 8}" y="${y(max * f) + 4}" text-anchor="end" class="ax">${short(max * f)}</text>`).join('');
    const ticks = all.map((p, i) => i % (all.length > 12 ? 2 : 1) ? '' : `<text x="${x(i)}" y="${H - 9}" text-anchor="middle" class="ax">${esc(p.d.toLocaleDateString(c.locale, { month: 'short' }))}</text>`).join('');
    const ships = b.shipments.filter(s => s.m <= horizon).map(s => `<circle cx="${x(nowI + s.m)}" cy="${y(future[s.m - 1].v)}" r="5.5" class="ship" data-tip="${esc(c.t('Incoming shipment'))}: ${fmt(s.qty)} ${esc(c.t('boxes'))}"/>`).join('');
    const hits = all.map((p, i) => {
      const w = (W - L - R) / (all.length - 1);
      const state = i <= nowI ? c.t('Stock on hand') : c.t('Projected stock');
      return `<rect class="hit" x="${x(i) - w / 2}" y="${T}" width="${w}" height="${H - T - B}" data-tip="${esc(p.d.toLocaleDateString(c.locale, { month: 'long', year: 'numeric' }))} · ${esc(state)}: ${fmt(p.v)} ${esc(c.t('boxes'))}"/>`;
    }).join('');
    return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(c.t('Stock projection'))}: ${esc(b.name)}">
${grid}<path d="${band}" class="band"/>
<line x1="${L}" x2="${W - R}" y1="${y(b.minLevel)}" y2="${y(b.minLevel)}" class="min"/><text x="${W - R}" y="${y(b.minLevel) - 6}" text-anchor="end" class="ax">${esc(c.t('Safety level (2 months)'))}</text>
<line x1="${x(nowI)}" x2="${x(nowI)}" y1="${T}" y2="${H - B}" class="today"/><text x="${x(nowI) + 6}" y="${T + 10}" class="ax">${esc(c.t('Today'))}</text>
<path d="${line(b.past, 0)}" class="hist"/><path d="${line(fut, nowI)}" class="proj"/>${ships}${ticks}${hits}</svg>`;
  }

  function demandBars(b, horizon, c) {
    const W = 760, H = 230, L = 46, R = 8, T = 22, B = 28;
    const rows = [...b.hist.map(h => ({ ...h, f: false })), ...b.fc.slice(0, horizon).map(f => ({ ...f, f: true }))];
    const max = niceMax(Math.max(...rows.map(r => r.hi || r.v)) * 1.05), n = rows.length;
    const step = (W - L - R) / n, w = Math.max(6, step - 4), y = v => T + (1 - v / max) * (H - T - B), base = H - B;
    const peak = rows.reduce((a, r, i) => r.v > rows[a].v ? i : a, 0);
    const grid = [0, .5, 1].map(f => `<line x1="${L}" x2="${W - R}" y1="${y(max * f)}" y2="${y(max * f)}" class="g"/><text x="${L - 8}" y="${y(max * f) + 4}" text-anchor="end" class="ax">${short(max * f)}</text>`).join('');
    const bars = rows.map((r, i) => {
      const bx = L + i * step + 2, by = y(r.v), h = base - by, label = i === peak || i === n - 1 ? `<text x="${bx + w / 2}" y="${by - 6}" text-anchor="middle" class="val">${short(r.v)}</text>` : '';
      return `<path d="M${bx} ${base}V${by + 4}Q${bx} ${by} ${bx + 4} ${by}H${bx + w - 4}Q${bx + w} ${by} ${bx + w} ${by + 4}V${base}Z" class="${r.f ? 'bar-f' : 'bar'}"/>${label}<rect class="hit" x="${L + i * step}" y="${T}" width="${step}" height="${base - T}" data-tip="${esc(r.d.toLocaleDateString(c.locale, { month: 'long', year: 'numeric' }))} · ${esc(c.t(r.f ? 'Forecast' : 'Demand'))}: ${fmt(r.v)} ${esc(c.t('boxes'))}"/>${i % 2 ? '' : `<text x="${bx + w / 2}" y="${H - 9}" text-anchor="middle" class="ax">${esc(r.d.toLocaleDateString(c.locale, { month: 'short' }))}</text>`}`;
    }).join('');
    return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(c.t('Monthly demand'))}: ${esc(b.name)}"><defs><pattern id="fc-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" class="hatch-a"/><rect width="2.4" height="6" class="hatch-b"/></pattern></defs>${grid}${bars}</svg>`;
  }

  function donut(list, c) {
    const groups = {};
    list.forEach(i => { const k = CLASS_ORDER.includes(i.cls) ? i.cls : 'Other'; groups[k] = (groups[k] || 0) + i.next; });
    const keys = [...CLASS_ORDER, 'Other'].filter(k => groups[k]), total = keys.reduce((t, k) => t + groups[k], 0);
    const R = 62, S = 2 * Math.PI * R; let off = 0;
    const arcs = keys.map(k => {
      const len = groups[k] / total * S, slot = k === 'Other' ? 6 : CLASS_ORDER.indexOf(k) + 1;
      const seg = `<circle cx="90" cy="90" r="${R}" class="s${slot}" stroke-dasharray="${Math.max(0, len - 3)} ${S}" stroke-dashoffset="${-off}" data-tip="${esc(c.t(k))}: ${fmt(groups[k])} ${esc(c.t('boxes'))} (${Math.round(groups[k] / total * 100)}%)"/>`;
      off += len; return seg;
    }).join('');
    const legend = keys.map(k => `<li><i class="s${k === 'Other' ? 6 : CLASS_ORDER.indexOf(k) + 1}"></i><span>${esc(c.t(k))}</span><b>${Math.round(groups[k] / total * 100)}%</b></li>`).join('');
    return `<div class="fc-donut"><svg viewBox="0 0 180 180" role="img" aria-label="${esc(c.t('Demand by class'))}"><g transform="rotate(-90 90 90)">${arcs}</g><text x="90" y="86" text-anchor="middle" class="big">${short(total)}</text><text x="90" y="104" text-anchor="middle" class="ax">${esc(c.t('boxes'))}</text></svg><ul>${legend}</ul></div>`;
  }

  function topTable(list, c) {
    const top = [...list].sort((a, b) => b.next - a.next).slice(0, 8), max = top[0].next;
    return `<table class="fc-top"><thead><tr><th>${esc(c.t('Medicine'))}</th><th>${esc(c.t('Forecast, next month'))}</th></tr></thead><tbody>${top.map(i => `<tr><td>${esc(i.name)}</td><td class="n"><span class="dbar" style="width:${Math.round(i.next / max * 100)}%"></span><b>${fmt(i.next)}</b></td></tr>`).join('')}</tbody></table>`;
  }

  function strip(b, c) {
    const cells = b.proj.map(p => {
      const st = coverStatus(p.cover);
      return `<li class="${st}" data-tip="${esc(p.d.toLocaleDateString(c.locale, { month: 'long', year: 'numeric' }))} · ${esc(c.t(STATUS_LABEL[st]))}: ${p.cover.toFixed(1)} ${esc(c.t('months'))}"><i aria-hidden="true">${STATUS_ICON[st]}</i><span>${esc(p.d.toLocaleDateString(c.locale, { month: 'short' }))}</span></li>`;
    }).join('');
    return `<ol class="fc-strip" aria-label="${esc(c.t('Coverage, next 12 months'))}">${cells}</ol>`;
  }

  function timeline(b, c) {
    const rows = [
      ...b.shipments.slice(0, 2).map(s => ({ m: s.m, kind: 'ship', title: c.t('Incoming shipment'), sub: `${c.t('Quantity')}: ${fmt(s.qty)} · ${s.po}`, tag: s.late ? `<span class="fc-tag late">⏱ ${esc(c.t('Delayed'))}</span>` : `<span class="fc-tag ok">✓ ${esc(c.t('On time'))}</span>` })),
      ...b.expiries.map(e => ({ m: e.m, kind: 'exp', title: c.t('Batch expiring'), sub: `${c.t('Batch number')} ${e.batch} · ${c.t('Quantity')}: ${fmt(e.qty)}`, tag: `<span class="fc-tag warn">${esc(c.t('Use first'))}</span>` }))
    ].sort((x, y) => x.m - y.m);
    return `<ul class="fc-time">${rows.map(r => `<li class="${r.kind}"><time>${esc(monthAt(r.m).toLocaleDateString(c.locale, { month: 'short', year: 'numeric' }))}</time><div><strong>${esc(r.title)}</strong> ${r.tag}<small>${esc(r.sub)}</small></div></li>`).join('')}</ul>`;
  }

  function adviceTable(list, c) {
    const rows = [...list].sort((a, b) => a.cover - b.cover);
    return `<div class="fc-scroll"><table class="fc-adv"><thead><tr><th>${esc(c.t('Medicine'))}</th><th>${esc(c.t('Forecast, next month'))}</th><th>${esc(c.t('Stock on hand'))}</th><th>${esc(c.t('Coverage'))}</th><th>${esc(c.t('Advice'))}</th></tr></thead><tbody>${rows.map(i => `<tr><td>${esc(i.name)}</td><td class="n">${fmt(i.next)}</td><td class="n">${fmt(i.stock)}</td><td><span class="fc-st ${i.st}"><i aria-hidden="true">${STATUS_ICON[i.st]}</i>${i.cover.toFixed(1)} ${esc(c.t('months'))}</span></td><td>${esc(i.gap ? c.t('Restock about {n} boxes', { n: fmt(i.gap) }) : i.st === 'over' ? c.t('Hold new orders') : c.t('Stock covers demand'))}</td></tr>`).join('')}</tbody></table></div>`;
  }

  function seasonality(list, c) {
    const classes = ['Antimalarial', 'Antibiotic', 'Rehydration', 'Respiratory'];
    const head = new Array(12).fill(0).map((_, i) => new Date(2026, i, 1).toLocaleDateString(c.locale, { month: 'narrow' }));
    const shade = v => v >= 1.25 ? 5 : v >= 1.1 ? 4 : v >= 1 ? 3 : v >= .9 ? 2 : 1;
    return `<div class="fc-scroll"><table class="fc-heat"><thead><tr><th></th>${head.map(m => `<th>${esc(m)}</th>`).join('')}</tr></thead><tbody>${classes.map(k => `<tr><th>${esc(c.t(k))}</th>${SEASON[k].map((v, i) => `<td class="h${shade(v)}" data-tip="${esc(c.t(k))} · ${esc(new Date(2026, i, 1).toLocaleDateString(c.locale, { month: 'long' }))}: ${v > 1 ? '+' : ''}${Math.round((v - 1) * 100)}%"></td>`).join('')}</tr>`).join('')}</tbody></table></div><div class="fc-scale"><span>${esc(c.t('Lower demand'))}</span><i class="h1"></i><i class="h2"></i><i class="h3"></i><i class="h4"></i><i class="h5"></i><span>${esc(c.t('Higher demand'))}</span></div>`;
  }

  function tileMap(c) {
    const data = districtDemand(), max = Math.max(...data.map(d => d.v));
    const shade = v => { const f = v / max; return f > .7 ? 5 : f > .45 ? 4 : f > .3 ? 3 : f > .2 ? 2 : 1; };
    const top = [...data].sort((a, b) => b.v - a.v).slice(0, 6);
    return `<div class="fc-geo"><div class="fc-tiles" role="img" aria-label="${esc(c.t('Demand by district'))}">${data.map(d => `<span class="h${shade(d.v)}" style="grid-column:${d.x + 1};grid-row:${d.y + 1}" data-tip="${esc(d.n)}: ${fmt(d.v)} ${esc(c.t('boxes'))}">${esc(d.n.slice(0, 3))}</span>`).join('')}</div><ol class="fc-rank">${top.map(d => `<li><span>${esc(d.n)}</span><i style="width:${Math.round(d.v / max * 100)}%"></i><b>${fmt(d.v)}</b></li>`).join('')}</ol></div><p class="fc-note">${esc(c.t('Grid of the 30 districts, placed approximately. Not a map to scale.'))}</p>`;
  }

  /* -------------------------------------------------------------------- page */
  function page(state, c) {
    const pharmacy = c.role === 'pharmacy', b = build(c.role, state.item, state.h), list = portfolio(c.role);
    const nextVal = b.fc[0].v, prev = b.hist[b.hist.length - 1].v, change = Math.round((nextVal - prev) / prev * 100);
    const reorder = b.reorderAt < 0 ? c.t('Not needed yet') : b.reorderAt === 0 ? c.t('Now') : b.proj[b.reorderAt].d.toLocaleDateString(c.locale, { month: 'long', year: 'numeric' });
    const atRisk = list.filter(i => i.st === 'critical' || i.st === 'alert').length;
    const tiles = [
      ['s1', fmt(b.stock), 'Stock on hand', c.t('boxes')],
      ['s2', fmt(b.amc), 'Average monthly demand', c.t('last 6 months')],
      ['st-' + coverStatus(b.cover), b.cover.toFixed(1), 'Months of coverage', c.t(STATUS_LABEL[coverStatus(b.cover)])],
      ['s3', fmt(nextVal), 'Forecast, next month', (change > 0 ? '+' : '') + change + '% ' + c.t('vs this month')],
      ['s5', pharmacy ? String(atRisk) : short(list.reduce((t, i) => t + i.next, 0)), pharmacy ? 'Medicines at risk' : 'Network demand, next month', pharmacy ? c.t('of {n} tracked', { n: list.length }) : c.t('boxes')]
    ];
    return `<div class="fc-demo"><strong>${esc(c.t('Example data'))}</strong> ${esc(c.t(pharmacy ? 'These numbers are examples, not your sales. A real forecast needs your order history.' : 'These numbers are examples. Real demand is shown only when at least 5 pharmacies contribute, and you never see the data of a single pharmacy.'))}</div>
<section class="fc" aria-label="${esc(c.t(pharmacy ? 'Forecasting' : 'Demand forecast'))}">
<header class="fc-head"><div><span class="fc-eyebrow">${esc(c.t(pharmacy ? 'STOCK INTELLIGENCE' : 'DEMAND INTELLIGENCE'))}</span><h2>${esc(c.t(pharmacy ? 'What your pharmacy will need' : 'What pharmacies will ask for'))}</h2></div>
<div class="fc-filters"><label>${esc(c.t('Medicine'))}<select id="fc-item">${ITEMS.map((x, i) => `<option value="${i}"${i === state.item ? ' selected' : ''}>${esc(x[0])}</option>`).join('')}</select></label>
<div class="fc-seg" role="group" aria-label="${esc(c.t('Horizon'))}">${[3, 6, 12].map(h => `<button type="button" data-h="${h}"${h === state.h ? ' aria-pressed="true"' : ' aria-pressed="false"'}>${esc(c.t('{n} months', { n: h }))}</button>`).join('')}</div></div></header>
<div class="fc-kpis">${tiles.map(([cls, v, l, s]) => `<div class="fc-kpi ${cls}"><b>${esc(v)}</b><span>${esc(c.t(l))}</span><small>${esc(s)}</small></div>`).join('')}</div>
<div class="fc-grid g-main">
<article class="fc-p"><div class="fc-ph"><h3>${esc(c.t('Stock projection'))}</h3><p>${esc(b.name)}</p></div>
<ul class="fc-leg"><li><i class="l-hist"></i>${esc(c.t('Stock on hand'))}</li><li><i class="l-proj"></i>${esc(c.t('Projected stock'))}</li><li><i class="l-band"></i>${esc(c.t('Likely range'))}</li><li><i class="l-ship"></i>${esc(c.t('Incoming shipment'))}</li></ul>
<div class="fc-chart">${lineChart(b, state.h, c)}</div>
<details class="fc-tbl"><summary>${esc(c.t('View as a table'))}</summary><div class="fc-scroll"><table><thead><tr><th>${esc(c.t('Month'))}</th><th>${esc(c.t('Forecast'))}</th><th>${esc(c.t('Projected stock'))}</th><th>${esc(c.t('Coverage'))}</th></tr></thead><tbody>${b.proj.slice(0, state.h).map((p, i) => `<tr><td>${esc(p.d.toLocaleDateString(c.locale, { month: 'long', year: 'numeric' }))}</td><td class="n">${fmt(b.fc[i].v)}</td><td class="n">${fmt(p.v)}</td><td>${p.cover.toFixed(1)} ${esc(c.t('months'))} · ${esc(c.t(STATUS_LABEL[coverStatus(p.cover)]))}</td></tr>`).join('')}</tbody></table></div></details>
</article>
<article class="fc-p"><div class="fc-ph"><h3>${esc(c.t('Expiries and shipments'))}</h3><p>${esc(c.t('Reorder by'))}: <strong>${esc(reorder)}</strong></p></div>${timeline(b, c)}</article>
</div>
<article class="fc-p fc-cov"><div class="fc-ph"><h3>${esc(c.t('Coverage, next 12 months'))}</h3><ul class="fc-key">${['critical', 'alert', 'good', 'over'].map(s => `<li class="${s}"><i aria-hidden="true">${STATUS_ICON[s]}</i>${esc(c.t(STATUS_LABEL[s]))}</li>`).join('')}</ul></div>${strip(b, c)}</article>
<div class="fc-grid g-three">
<article class="fc-p span2"><div class="fc-ph"><h3>${esc(c.t('Monthly demand'))}</h3><p>${esc(c.t('Solid bars are past demand. Striped bars are the forecast.'))}</p></div><div class="fc-chart">${demandBars(b, state.h, c)}</div></article>
<article class="fc-p"><div class="fc-ph"><h3>${esc(c.t('Demand by class'))}</h3><p>${esc(c.t('Next month'))}</p></div>${donut(list, c)}</article>
</div>
<div class="fc-grid g-two">
<article class="fc-p"><div class="fc-ph"><h3>${esc(c.t('Top medicines, next month'))}</h3></div>${topTable(list, c)}</article>
${pharmacy
    ? `<article class="fc-p"><div class="fc-ph"><h3>${esc(c.t('Seasonal pattern'))}</h3><p>${esc(c.t('Plan ahead of the months that usually peak.'))}</p></div>${seasonality(list, c)}</article>`
    : `<article class="fc-p"><div class="fc-ph"><h3>${esc(c.t('Demand by district'))}</h3><p>${esc(c.t('Next month, across verified pharmacies.'))}</p></div>${tileMap(c)}</article>`}
</div>
<article class="fc-p"><div class="fc-ph"><h3>${esc(c.t(pharmacy ? 'What to reorder' : 'Your stock against next month’s demand'))}</h3><p>${esc(c.t('Lowest coverage first.'))}</p></div>${adviceTable(list, c)}</article>
</section><div class="fc-tip" id="fc-tip" role="status" hidden></div>`;
  }

  function mount(root, c) {
    const state = { item: 0, h: 12 };
    const draw = () => { root.innerHTML = page(state, c); };
    draw();
    root.onchange = null;
    const onChange = e => { if (e.target.id === 'fc-item') { state.item = +e.target.value; draw(); const s = root.querySelector('#fc-item'); if (s) s.focus(); } };
    const onClick = e => { const b = e.target.closest('[data-h]'); if (b) { state.h = +b.dataset.h; draw(); const again = root.querySelector(`[data-h="${state.h}"]`); if (again) again.focus(); } };
    const onMove = e => {
      const tip = root.querySelector('#fc-tip'); if (!tip) return;
      const hit = e.target.closest && e.target.closest('[data-tip]');
      if (!hit) { tip.hidden = true; return; }
      tip.textContent = hit.dataset.tip; tip.hidden = false;
      const left = Math.min(e.clientX + 14, innerWidth - tip.offsetWidth - 10);
      tip.style.left = Math.max(8, left) + 'px';
      tip.style.top = Math.max(8, e.clientY - tip.offsetHeight - 12) + 'px';
    };
    const onLeave = () => { const tip = root.querySelector('#fc-tip'); if (tip) tip.hidden = true; };
    root.addEventListener('change', onChange);
    root.addEventListener('click', onClick);
    root.addEventListener('pointermove', onMove);
    root.addEventListener('pointerleave', onLeave);
    return () => {
      root.removeEventListener('change', onChange); root.removeEventListener('click', onClick);
      root.removeEventListener('pointermove', onMove); root.removeEventListener('pointerleave', onLeave);
    };
  }

  global.DashForecast = { mount };
})(window);
