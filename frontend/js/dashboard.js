'use strict';
/* Pharmacy and supplier dashboards. <body data-role> picks the role.
 * Data comes from js/dashboard-data.js: the live API, or sample data with ?preview=1.
 * The site's Content-Security-Policy forbids inline scripts and handlers, so every
 * control is wired through the delegated listeners at the bottom of this file. */
(function () {
  const ROLE = document.body.dataset.role;
  const IS_PH = ROLE === 'pharmacy';
  const ONBOARD = IS_PH ? 'pharmacies.html' : 'suppliers.html';
  const params = new URLSearchParams(location.search);

  /* ---------------------------------------------------------------- text */
  let lang = 'en';
  try { lang = params.get('lang') || localStorage.getItem('apexrx_lang') || 'en'; } catch (e) { /* ignore */ }
  if (!['en', 'fr', 'rw'].includes(lang)) lang = 'en';
  const t = (s, v) => {
    let out = (window.DASH_T[lang] && window.DASH_T[lang][s]) || s;
    if (v) Object.keys(v).forEach(k => { out = out.split('{' + k + '}').join(v[k]); });
    return out;
  };
  const pl = (n, one, many) => t(n === 1 ? one : many, { n });
  const LOCALE = { en: 'en-GB', fr: 'fr-FR', rw: 'en-GB' }[lang];

  /* ------------------------------------------------------------- helpers */
  const $ = s => document.querySelector(s);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const money = (n, cur) => Math.round(Number(n)).toLocaleString('en-US') + ' ' + (cur || 'RWF');
  const num = n => Number(n).toLocaleString('en-US');
  const money2 = n => Number(n).toLocaleString('en-US', { maximumFractionDigits: 2 }) + ' RWF';
  const initials = s => String(s || '?').split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join('');
  const label = o => { const n = o.product_name || o.drug_name || ''; return o.strength && !n.toLowerCase().includes(String(o.strength).toLowerCase()) ? n + ' ' + o.strength : n; };
  const fullLabel = o => [label(o), o.pack_size].filter(Boolean).join(' ');
  const fmtDate = d => new Date(d).toLocaleDateString(LOCALE, { day: 'numeric', month: 'short' });
  const fmtTime = d => new Date(d).toLocaleString(LOCALE, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  function ago(d) {
    const m = Math.round((Date.now() - new Date(d)) / 6e4);
    if (m < 2) return t('just now');
    if (m < 60) return t('{n} min ago', { n: m });
    if (m < 1440) return pl(Math.round(m / 60), '{n} hour ago', '{n} hours ago');
    return pl(Math.round(m / 1440), '{n} day ago', '{n} days ago');
  }
  const debounce = (fn, ms) => { let id; return (...a) => { clearTimeout(id); id = setTimeout(() => fn(...a), ms); }; };
  const wa = (phone, text) => { const d = String(phone || '').replace(/\D/g, ''); return d ? `https://wa.me/${d}${text ? '?text=' + encodeURIComponent(text) : ''}` : null; };
  const maps = l => l && l.latitude != null ? `https://www.google.com/maps/dir/?api=1&destination=${l.latitude},${l.longitude}` : null;
  let toastTimer;
  // In the preview every confirmation says that nothing was saved or sent.
  function toast(text) {
    const el = $('#toast');
    el.textContent = isPreview && text ? text + ' ' + t('(Preview: nothing was saved or sent.)') : text;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { el.textContent = ''; }, 6000);
  }
  const errorText = err => err && err.status === 0 ? t('Cannot reach ApexRX right now. Please try again in a minute.') : (err && err.status >= 500) || !(err && err.message) ? t('Something went wrong. Please try again.') : err.message;
  const fail = err => toast(errorText(err));

  /* --------------------------------------------------------------- state */
  const D = params.get('preview') === '1' || !(window.ApexAPI && ApexAPI.session.isSignedIn()) ? null : window.DashData.live(ROLE);
  const isPreview = !D;
  if (isPreview && params.get('preview') !== '1') { location.replace(ONBOARD + '?lang=' + lang + '#signin'); return; }
  const data = D || window.DashData.preview(ROLE);
  const S = { view: 'home', loc: null, stock: [], orders: [], full: new Map(), drugs: [], q: '', cat: '', sort: 'price', sf: '', ovq: '', party: null, newParty: null, listOpen: false, listRows: [], imp: null, offers: [], por: isPreview && IS_PH ? samplePatientOrders() : [] };
  let ctx = null; // { user, org, myRole, locations }

  function samplePatientOrders() {
    return [{ id: 'P-1041', who: 'Aline', m: 'Amlodipine 5mg B/30 Tablets', n: 2, st: 'New', pid: 7 }, { id: 'P-1042', who: 'Jean', m: 'Amoxicillin 500mg B/20 Capsules', n: 1, st: 'New', pid: 1 }];
  }
  const approved = () => ctx.org.status === 'approved';
  const canManage = () => ctx.myRole === 'owner' || ctx.myRole === 'manager';
  // Batch numbers and expiry dates: only the preview has them until the API stores batches.
  const hasBatches = () => !!data.batches;
  const ROLE_NAMES = { owner: 'Owner', manager: 'Manager', staff: 'Staff' };
  const activeLocations = () => (ctx.locations || []).filter(l => l.is_active);
  const curLoc = () => (ctx.locations || []).find(l => l.location_id === S.loc) || null;
  const partyOf = o => IS_PH ? o.supplier : o.pharmacy;
  const needsMe = o => IS_PH ? o.status === 'countered' : o.status === 'submitted';
  const waiting = () => S.orders.filter(needsMe);
  const toConfirm = () => S.orders.filter(o => ['accepted', 'processing'].includes(o.status));
  const threshold = x => x.offer ? x.offer.low_stock_threshold : 5;
  // What can still be sold: stock on hand without its expired batches.
  const sellable = x => Math.max(0, x.quantity - (x.expired_quantity || 0));
  const lowItems = () => S.stock.filter(x => sellable(x) <= threshold(x));
  const daysLeft = d => Math.ceil((new Date(d + 'T00:00:00') - new Date(new Date().toDateString())) / 864e5);
  const batchRows = () => S.stock.flatMap(x => (x.batches || []).map(b => ({ ...b, item: x, left: daysLeft(b.expiry_date) })));
  const expiringSoon = () => batchRows().filter(b => b.left >= 0 && b.left <= 90 && b.quantity > 0).sort((a, b) => a.left - b.left);
  const expiredBatches = () => batchRows().filter(b => b.left < 0 && b.quantity > 0);
  const packCount = pack => { const m = /(\d+)/.exec(pack || ''); return m ? +m[1] : 0; };
  const sid = () => 'SUP-' + String(ctx.org.organization_id).padStart(5, '0');
  const listedCount = () => S.stock.filter(x => x.offer && x.offer.is_listed).length;
  const seesLabel = x => {
    if (!x.offer || !x.offer.is_listed) return ['', t('Not listed')];
    if (sellable(x) <= 0) return x.quantity > 0 ? ['out', t('Hidden: expired')] : ['out', t('Out of stock')];
    return sellable(x) <= threshold(x) ? ['low', t('Low stock')] : ['in', t('In stock')];
  };

  const STATUS = {
    draft: ['', 'Draft'], submitted: ['low', IS_PH ? 'Waiting for the supplier' : 'New request'], countered: ['low', IS_PH ? 'Offer received' : 'Offer sent'],
    accepted: ['good', 'Accepted'], rejected: ['out', 'Declined'], processing: ['good', 'Being prepared'], dispatched: ['good', 'Dispatched'], delivered: ['good', 'Delivered'], cancelled: ['out', 'Cancelled']
  };
  const statusTag = s => { const x = STATUS[s] || ['', s]; return `<span class="tag ${x[0]}">${esc(t(x[1]))}</span>`; };
  const ACTIONS = { submit: 'Send order', accept: 'Accept as requested', counter: 'Write offer', reject: 'Decline', 'accept-counter': 'Accept offer', 'start-processing': 'Start preparing', dispatch: 'Mark as dispatched', 'mark-delivered': 'Mark as delivered', cancel: 'Cancel order', delete: 'Delete draft' };
  const PRIMARY = new Set(['submit', 'accept', 'counter', 'accept-counter', 'start-processing', 'dispatch', 'mark-delivered']);
  const actionButtons = o => (o.allowed_actions || []).filter(a => ACTIONS[a])
    .map(a => `<button class="${PRIMARY.has(a) ? 'solid' : 'ghost'}" data-a="order" data-o="${o.purchase_order_id}" data-x="${a}">${esc(t(ACTIONS[a]))}</button>`).join('');

  /* ---------------------------------------------------------- navigation */
  const NAV = IS_PH
    ? [['home', 'Overview'], ['cmp', 'Compare prices'], ['msg', 'Messages'], ['ord', 'Supplier orders'], ['stk', 'My stock'], ['por', 'Patient orders'], ['prem', 'Forecasting'], ['set', 'Branches and team']]
    : [['home', 'Overview'], ['msg', 'Requests and chat'], ['ord', 'Orders'], ['stk', 'My catalogue'], ['prem', 'Demand forecast'], ['set', 'Depots and team']];
  const TITLES = { home: 'Overview', cmp: 'Compare prices', msg: IS_PH ? 'Messages' : 'Requests and chat', ord: IS_PH ? 'Supplier orders' : 'Orders', stk: IS_PH ? 'My stock' : 'My catalogue', por: 'Patient orders', set: IS_PH ? 'Branches and team' : 'Depots and team', prem: IS_PH ? 'Forecasting' : 'Demand forecast' };

  function chrome() {
    document.documentElement.lang = lang;
    document.title = t(IS_PH ? 'Pharmacy dashboard' : 'Supplier dashboard') + ' — ApexRX Smart';
    $('#nav').innerHTML = NAV.map(([v, l]) => `<button class="nav" data-a="nav" data-v="${v}">${esc(t(l))}${v === 'prem' ? ` <span class="tag">${esc(t('Premium'))}</span>` : `<span class="badge" id="b-${v}" hidden></span>`}</button>`).join('');
    $('#nav').setAttribute('aria-label', t(IS_PH ? 'Pharmacy workspace' : 'Supplier workspace'));
    $('#p-t').textContent = t('Premium');
    $('#p-d').textContent = t(IS_PH ? 'Demand forecast and more tools, coming with Premium.' : 'Demand forecast for your catalogue.');
    $('#p-b').textContent = t('See the preview'); $('#p-b').dataset.v = 'prem';
    $('#br-l').textContent = t(IS_PH ? 'Branch' : 'Depot');
    $('#out').textContent = isPreview ? t('Exit preview') : t('Sign out');
    $('#lang').value = lang;
    paintTheme();
    if (ctx) {
      $('#me-name').textContent = ctx.org.name;
      $('#dash-user').textContent = isPreview ? t('Sample data') : `${ctx.user.email} · ${t(ROLE_NAMES[ctx.myRole] || ctx.myRole)}`;
      // Users in several organizations pick one; the other dashboard opens for the other type.
      const orgs = ctx.memberships || [];
      $('#org-l').textContent = t('Organization');
      $('#org').hidden = orgs.length < 2;
      $('#org').innerHTML = orgs.map(m => `<option value="${m.organization_type}:${m.organization_id}"${m.organization_id === ctx.org.organization_id ? ' selected' : ''}>${esc(m.organization_name)} (${esc(t(m.organization_type === 'pharmacy' ? 'Pharmacy' : 'Supplier'))}, ${esc(t(ROLE_NAMES[m.role] || m.role))})</option>`).join('');
      $('#br').innerHTML = activeLocations().map(l => `<option value="${l.location_id}">${esc(l.name)}</option>`).join('');
      $('#br').hidden = activeLocations().length < 2;
      $('#br').value = S.loc ?? '';
      const st = ctx.org.status, ver = $('#ver');
      ver.className = 'ver' + (st === 'approved' ? '' : st === 'pending' ? ' wait' : ' bad');
      ver.textContent = st === 'approved' ? '✓ ' + t(IS_PH ? 'NPC verified' : 'Licence verified') : t({ pending: 'Pending verification', rejected: 'Not approved', suspended: 'Suspended' }[st] || st);
    }
  }
  function paintTheme() {
    const dark = ApexTheme.get() === 'dark', b = $('#theme');
    b.innerHTML = dark
      ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5 19 19M19 5l-1.5 1.5M6.5 17.5 5 19"/></svg>'
      : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 13A9 9 0 1 1 11 3a7 7 0 0 0 10 10Z"/></svg>';
    const label2 = t(dark ? 'Switch to light mode' : 'Switch to dark mode');
    b.title = label2; b.setAttribute('aria-label', label2);
  }
  function badges() {
    const set = (id, n) => { const b = $('#b-' + id); if (b) { b.hidden = !n; b.textContent = n; } };
    set('msg', waiting().length);
    set('ord', IS_PH ? 0 : toConfirm().length);
    set('por', S.por.filter(o => o.st === 'New').length);
  }
  function go(v) {
    S.view = v;
    if (unmountForecast) { unmountForecast(); unmountForecast = null; }
    document.querySelectorAll('.nav').forEach(b => b.dataset.v === v ? b.setAttribute('aria-current', 'page') : b.removeAttribute('aria-current'));
    $('#title').textContent = t(TITLES[v]);
    $('#view').innerHTML = shell(VIEWS[v]());
    if (AFTER[v]) AFTER[v]();
    badges();
    // Orders change on the other side (offers, dispatches): opening a screen that
    // shows them fetches the latest list, and repaints only if something changed.
    if (ORDER_VIEWS.includes(v)) poll(true);
  }
  const ORDER_VIEWS = ['home', 'msg', 'ord'];
  function shell(html) {
    const strip = isPreview ? `<div class="demo-strip">${esc(t('Preview with sample data. Nothing you do here is saved or sent to anyone.'))}</div>` : '';
    const st = ctx.org.status;
    const note = { pending: IS_PH ? 'Your pharmacy is awaiting verification by ApexRX. Supplier prices, orders and stock changes open once it is approved.' : 'Your business is awaiting verification by ApexRX. Your catalogue and orders open once it is approved.', rejected: 'Your registration was not approved. Update your documents, then send it for review again.', suspended: 'Your account is suspended. Contact ApexRX for help.' }[st];
    const banner = note ? `<div class="banner${st === 'pending' ? '' : ' bad'}"><span>${esc(t(note))}${ctx.org.review_notes ? ' ' + esc(ctx.org.review_notes) : ''}</span>${st === 'rejected' && ctx.myRole === 'owner' ? `<button class="ghost" data-a="resubmit">${esc(t('Send for review again'))}</button>` : ''}</div>` : '';
    return strip + banner + html;
  }

  /* --------------------------------------------------------------- views */
  function hero() {
    const h = new Date().getHours();
    const hello = t(h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening');
    const n = waiting().length, low = lowItems().length, listed = listedCount();
    const img = IS_PH ? 'audience-pharmacies.webp' : 'audience-suppliers.webp';
    const alt = t(IS_PH ? 'A pharmacist scans a box of medicine at the counter' : 'A supplier scans a carton in a medical warehouse');
    const scanStyle = IS_PH ? '--sx:57%;--sy:49%;--sw:12%;--sh:13%' : '--sx:53%;--sy:64%;--sw:15%;--sh:9%';
    const cta = IS_PH ? ['cmp', 'Find a medicine source →'] : ['msg', 'Open requests →'];
    const copy = `<div class="hero-copy"><span class="ov-eyebrow">${esc(t(IS_PH ? 'YOUR NETWORK, WITHIN REACH' : 'YOUR DEMAND, WITHIN REACH'))}</span>
<h2>${esc(hello)}, ${esc(ctx.org.name)}.</h2>
<p>${esc(t(IS_PH ? 'The next step in better care starts with a connection.' : 'Verified pharmacies ask you for prices here, instead of by phone.'))}</p>
<div class="hero-cta"><button class="solid" data-a="nav" data-v="${cta[0]}">${esc(t(cta[1]))}</button><button class="ghost" data-a="nav" data-v="${IS_PH ? 'stk' : 'ord'}">${esc(t(IS_PH ? 'My stock' : 'Orders'))}</button></div></div>`;
    const art = `<figure class="hero-art">
<div class="capsule"><div class="capsule-in"><img src="assets/images/${img}" alt="${esc(alt)}"><span class="scan" style="${scanStyle}" aria-hidden="true"></span></div></div>
<i class="mini m1" aria-hidden="true"></i><i class="mini m2" aria-hidden="true"></i><span class="plus" aria-hidden="true">+</span>
<button class="chipf c1" data-a="nav" data-v="msg"><span><b>${n}</b><small>${esc(t(IS_PH ? 'offers waiting' : 'requests waiting'))}</small></span></button>
<button class="chipf c2" data-a="nav" data-v="${IS_PH ? 'stk' : 'ord'}"><span><b>${IS_PH ? low : toConfirm().length}</b><small>${esc(t(IS_PH ? 'running low' : 'to prepare'))}</small></span></button>
<button class="chipf c3" data-a="nav" data-v="stk"><span><b>${IS_PH ? listed : hasBatches() ? expiringSoon().length : '—'}</b><small>${esc(t(IS_PH ? 'listed' : 'expiring soon'))}</small></span></button>
</figure>`;
    return IS_PH ? `<section class="hero">${copy}${art}</section>` : `<section class="hero sup">${art}${copy}</section>`;
  }
  const actRow = (count, title, text, btn) => `<div class="ov-act${count ? '' : ' mute'}"><div class="ov-n">${count}</div><div><strong>${esc(title)}</strong><p>${esc(text)}</p></div>${btn}</div>`;
  const navBtn = (v, l, ghost) => `<button class="${ghost ? 'ghost' : 'solid'}" data-a="nav" data-v="${v}">${esc(t(l))}</button>`;

  const todayText = () => new Date().toLocaleDateString(LOCALE, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
  const batchLine = b => `<div class="ov-row exp"><span class="exp-d${b.left <= 30 ? ' soon' : ''}"><b>${b.left}</b><small>${esc(t('days'))}</small></span><div><strong>${esc(label(b.item))}</strong><small>${esc(t('Batch number'))} ${esc(b.batch_number)} · ${esc(pl(b.quantity, '{n} box', '{n} boxes'))} · ${esc(fmtDate(b.expiry_date))}</small></div></div>`;
  const BATCHES_OFF = 'Batch numbers and expiry dates are not connected yet. ApexRX cannot store them, so no expiry alerts are shown.';
  const expiryPanel = () => {
    const head = `<section class="ov-panel" id="shelf-life"><div class="ov-ph"><div><span class="ov-eyebrow">${esc(t('SHELF LIFE'))}</span><h3>${esc(t('Batches to use first'))}</h3></div>${navBtn('stk', IS_PH ? 'My stock' : 'My catalogue', true)}</div>`;
    if (!hasBatches()) return `${head}<p class="empty"><span class="tag">${esc(t('Not connected yet'))}</span><br>${esc(t(BATCHES_OFF))}</p></section>`;
    const list = expiringSoon().slice(0, 4), gone = expiredBatches();
    return `${head}
${gone.length ? `<p class="lock">${esc(pl(gone.length, '{n} batch has expired and is hidden.', '{n} batches have expired and are hidden.'))}</p>` : ''}${list.map(batchLine).join('') || `<p class="empty">${esc(t('No batch expires within 90 days.'))}</p>`}</section>`;
  };
  const conversationsPanel = () => `<section class="ov-panel"><div class="ov-ph"><div><span class="ov-eyebrow">${esc(t('BUILD YOUR CONNECTIONS'))}</span><h3>${esc(t(IS_PH ? 'Recent supplier conversations' : 'Recent pharmacy conversations'))}</h3></div><label><span class="sr">${esc(t('Search conversations'))}</span><input id="ovq" type="search" value="${esc(S.ovq)}" placeholder="${esc(t('Search conversations'))}" autocomplete="off"></label></div><div id="ovlist"></div></section>`;

  /* Pharmacy overview: the counter's day. Patients, stock health and reorders. */
  function homePharmacy() {
    const n = waiting().length, low = lowItems(), loc = curLoc(), bn = loc ? loc.name : ctx.org.name;
    const convs = threads().length, lowNames = low.slice(0, 4).map(label).join(', '), newPor = S.por.filter(o => o.st === 'New').length;
    const counts = { in: 0, low: 0, out: 0 };
    S.stock.forEach(x => { const q = sellable(x); counts[q <= 0 ? 'out' : q <= threshold(x) ? 'low' : 'in']++; });
    const total = S.stock.length || 1;
    const seg = (k, l) => counts[k] ? `<span class="h-${k}" style="flex:${counts[k]}" title="${esc(t(l))}: ${counts[k]}"></span>` : '';
    const legend = (k, l) => `<li><i class="h-${k}"></i><span>${esc(t(l))}</span><b>${counts[k]}</b><small>${Math.round(counts[k] / total * 100)}%</small></li>`;
    const att = [
      actRow(newPor, isPreview ? pl(newPor, '{n} new patient order', '{n} new patient orders') : t('No new patient orders'), isPreview ? t('Patients order from your stock at {b}.', { b: bn }) : t('Patient ordering is coming soon.'), navBtn('por', 'View patient orders')),
      actRow(n, n ? pl(n, '{n} price offer waiting for your answer', '{n} price offers waiting for your answer') : t('No offers waiting'), n ? t('Accept or decline the offer from the supplier.') : t('Ask a supplier for a quote from Compare prices.'), navBtn('msg', 'Open messages')),
      actRow(low.length, low.length ? pl(low.length, '{n} item is running low', '{n} items are running low') : t('Your stock looks healthy'), low.length ? lowNames : t('Nothing to reorder right now.'), low.length ? `<button class="solid" data-a="compare" data-m="${esc(low[0].drug_name)}">${esc(t('Compare prices'))}</button>` : navBtn('cmp', 'Compare prices', true)),
      actRow(S.orders.length, S.orders.length ? pl(S.orders.length, '{n} order sent to suppliers', '{n} orders sent to suppliers') : t('No supplier orders yet'), t('Follow each order from request to delivery.'), navBtn('ord', 'View orders'))
    ];
    return `<div class="ov-top"><span class="ov-eyebrow">${esc(t('PHARMACY OVERVIEW'))}</span><p>${esc(todayText())}</p></div>${hero()}
<div class="ov-cards"><button class="ov-card" data-a="nav" data-v="msg"><span class="ov-i">↗</span><strong>${esc(pl(convs, '{n} supplier conversation', '{n} supplier conversations'))}</strong><small>${esc(t('Explore your conversations →'))}</small></button>
<button class="ov-card" data-a="nav" data-v="set"><span class="ov-i">◎</span><strong>${esc(t('Your pharmacy profile'))}</strong><small>${esc((loc && loc.address) || t('Review your location and details'))} →</small></button>
<div class="ov-card" id="plan-card"><span class="ov-i">✓</span><strong>${esc(t('Plans and payments'))}</strong><small><span class="tag">${esc(t('Not live yet'))}</span> ${esc(t('ApexRX takes no payments and has no paid plans yet.'))}</small></div></div>
<h3 class="ov-h">${esc(t('What needs your attention'))}</h3><div class="ov-actions">${att.join('')}</div>
<div class="ov-two"><section class="ov-panel"><div class="ov-ph"><div><span class="ov-eyebrow">${esc(t('STOCK HEALTH'))}</span><h3>${esc(t('Stock at {b}', { b: bn }))}</h3></div></div>
<div class="health" aria-hidden="true">${seg('in', 'In stock')}${seg('low', 'Low stock')}${seg('out', 'Out of stock')}</div><ul class="health-l">${legend('in', 'In stock')}${legend('low', 'Low stock')}${legend('out', 'Out of stock')}</ul></section>${expiryPanel()}</div>
${conversationsPanel()}
<section class="ov-premium"><div><span>${esc(t('MORE POSSIBILITIES'))}</span><h3>${esc(t('Think ahead.'))}<br>${esc(t('Grow with confidence.'))}</h3><p>${esc(t('AI forecasting and insurance tools.'))}</p></div>${navBtn('prem', 'Explore Premium →')}</section>`;
  }

  /* Supplier overview: the depot's sales desk. Requests moving through to delivery. */
  function homeSupplier() {
    const n = waiting().length, prep = toConfirm(), low = lowItems(), soon = expiringSoon(), loc = curLoc();
    const convs = threads().length, count = st => S.orders.filter(o => st.includes(o.status)).length;
    const STAGES = [['submitted', 'New requests'], ['countered', 'Offers sent'], ['accepted,processing', 'To prepare'], ['dispatched', 'Dispatched'], ['delivered', 'Delivered']];
    const open = S.orders.filter(o => ['submitted', 'countered', 'accepted', 'processing', 'dispatched'].includes(o.status));
    const openValue = open.reduce((v, o) => v + Number(o.confirmed_total ?? o.requested_total ?? 0), 0);
    const att = [
      actRow(n, n ? pl(n, '{n} request waiting for your offer', '{n} requests waiting for your offer') : t('No requests waiting'), t('Verified pharmacies asked for prices. Reply with an offer.'), navBtn('msg', 'Open requests')),
      actRow(prep.length, prep.length ? pl(prep.length, '{n} order to prepare', '{n} orders to prepare') : t('No orders to prepare'), t('Orders start when a pharmacy accepts your offer.'), navBtn('ord', 'View orders')),
      actRow(low.length, low.length ? pl(low.length, '{n} item is running low', '{n} items are running low') : t('Your catalogue looks healthy'), low.length ? low.slice(0, 4).map(label).join(', ') : t('Pharmacies can order everything you list.'), navBtn('stk', 'Update catalogue')),
      hasBatches()
        ? actRow(soon.length, soon.length ? pl(soon.length, '{n} batch expires within 90 days', '{n} batches expire within 90 days') : t('No batch expiring soon'), soon.length ? soon.slice(0, 3).map(b => `${label(b.item)} (${b.batch_number})`).join(', ') : t('Your batches have a comfortable shelf life.'), navBtn('stk', 'Check batches', true))
        : actRow(0, t('Expiry tracking is not connected yet'), t(BATCHES_OFF), `<button class="ghost" disabled>${esc(t('Not connected yet'))}</button>`)
    ];
    return `<div class="ov-top"><span class="ov-eyebrow">${esc(t('SUPPLIER OVERVIEW'))}</span><p>${esc(todayText())}</p></div>${hero()}
<section class="pipe" aria-label="${esc(t('Order pipeline'))}">${STAGES.map(([st, l], i) => `<button class="pipe-s" data-a="nav" data-v="${i < 2 ? 'msg' : 'ord'}"><b>${count(st.split(','))}</b><span>${esc(t(l))}</span></button>`).join('')}<div class="pipe-v"><small>${esc(t('Open order value'))}</small><b>${money(openValue)}</b></div></section>
<div class="sup-grid"><div><h3 class="ov-h">${esc(t('What needs your attention'))}</h3><div class="ov-stack">${att.join('')}</div></div>
<div><section class="ov-panel"><div class="ov-ph"><div><span class="ov-eyebrow">${esc(t('WHAT PHARMACIES WANT'))}</span><h3>${esc(t('Most requested medicines'))}</h3></div></div><div id="toprq"><p class="empty">${esc(t('Loading…'))}</p></div></section>${expiryPanel()}</div></div>
<div class="ov-cards two"><button class="ov-card" data-a="nav" data-v="set"><span class="ov-i">◎</span><strong>${esc(t('Your supplier profile'))}</strong><small>${esc(t('Supplier ID'))} ${esc(sid())}. ${esc((loc && loc.address) || t('Review your location and details'))} →</small></button>
<div class="ov-card" id="plan-card"><span class="ov-i">✓</span><strong>${esc(t('Plans and payments'))}</strong><small><span class="tag">${esc(t('Not live yet'))}</span> ${esc(t('ApexRX takes no payments and has no paid plans yet.'))}</small></div></div>
${conversationsPanel()}
<section class="ov-premium"><div><span>${esc(t('MORE POSSIBILITIES'))}</span><h3>${esc(t('Think ahead.'))}<br>${esc(t('Grow with confidence.'))}</h3><p>${esc(t('Demand forecasting for your catalogue.'))}</p></div>${navBtn('prem', 'Explore Premium →')}</section>`;
  }
  async function topRequested() {
    const el = $('#toprq'); if (!el) return;
    const recent = S.orders.filter(o => o.status !== 'draft').slice(0, 15);
    const full = await Promise.all(recent.map(async o => {
      const c = S.full.get(o.purchase_order_id);
      if (c && c.updated_at === o.updated_at) return c;
      try { const f = await data.order(o.purchase_order_id); S.full.set(o.purchase_order_id, f); return f; } catch (e) { return null; }
    }));
    const by = new Map();
    full.filter(Boolean).forEach(o => o.items.forEach(i => { const k = fullLabel(i); by.set(k, (by.get(k) || 0) + (i.confirmed_quantity ?? i.requested_quantity)); }));
    const top = [...by.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5), max = top.length ? top[0][1] : 1;
    if (!$('#toprq')) return;
    $('#toprq').innerHTML = top.map(([k, v]) => `<div class="rq"><span>${esc(k)}</span><i><b style="width:${Math.round(v / max * 100)}%"></b></i><strong>${esc(pl(v, '{n} box', '{n} boxes'))}</strong></div>`).join('') || `<p class="empty">${esc(t('No requests yet. They appear here when a pharmacy asks you for prices.'))}</p>`;
  }

  const VIEWS = {
    home() { return IS_PH ? homePharmacy() : homeSupplier(); },
    cmp() {
      const cats = [...new Set(S.drugs.map(d => d.therapeutic_class).filter(Boolean))].sort();
      const hasGeo = curLoc() && curLoc().latitude != null;
      return `<div class="bar"><label class="grow"><span class="sr">${esc(t('Search a medicine'))}</span><input id="q" type="search" value="${esc(S.q)}" placeholder="${esc(t('Search a medicine, e.g. Paracetamol'))}" autocomplete="off"></label>
<label><span class="sr">${esc(t('Sort'))}</span><select id="sort"><option value="price"${S.sort === 'price' ? ' selected' : ''}>${esc(t('Lowest price first'))}</option><option value="distance"${S.sort === 'distance' ? ' selected' : ''}${hasGeo ? '' : ' disabled'}>${esc(t('Nearest first'))}</option></select></label></div>
<div class="chips"><button class="chip${S.cat ? '' : ' on'}" data-a="cat" data-c="">${esc(t('All categories'))}</button>${cats.map(x => `<button class="chip${S.cat === x ? ' on' : ''}" data-a="cat" data-c="${esc(x)}">${esc(x)}</button>`).join('')}</div>
<div class="tbl"><table><thead><tr><th>${esc(t('Item'))}</th><th>${esc(t('Supplier and location'))}</th><th>${esc(t('Distance'))}</th><th>${esc(t('Price per box'))}</th><th>${esc(t('In stock'))}</th><th></th></tr></thead><tbody id="rows"><tr><td colspan="6" class="empty">${esc(t('Loading…'))}</td></tr></tbody></table></div>
<p class="note">${esc(t('Supplier prices are visible only to verified pharmacies. Suppliers never see each other.'))}${hasGeo ? '' : ' ' + esc(t('Add your location to see distances.'))}</p>`;
    },
    msg() { return `<div class="mail"><div class="clist" id="clist"></div><div class="thread" id="thread"></div></div>`; },
    ord() {
      return `<div class="tbl"><table><thead><tr><th>${esc(t('Order'))}</th><th>${esc(t(IS_PH ? 'Supplier' : 'Pharmacy'))}</th><th>${esc(t('Items'))}</th><th>${esc(t('Total'))}</th><th>${esc(t('Status'))}</th><th></th></tr></thead><tbody id="orows"><tr><td colspan="6" class="empty">${esc(t('Loading…'))}</td></tr></tbody></table></div>
<p class="note">${esc(t('Payment is not handled by the platform.'))}</p>`;
    },
    stk() {
      const loc = curLoc(), writable = approved(), b = hasBatches();
      // Without batch storage the fields stay visible (the design) but disabled and labelled.
      const off = b ? ' required' : ` disabled placeholder="${esc(t('Not connected yet'))}" title="${esc(t(BATCHES_OFF))}"`;
      if (!loc) return `<div class="panel"><h2>${esc(t(IS_PH ? 'Add a branch first' : 'Add a depot first'))}</h2><p class="muted" style="margin:0">${esc(t(IS_PH ? 'Stock is kept per branch. Add one in Branches and team.' : 'Stock is kept per depot. Add one in Depots and team.'))}</p></div>`;
      return `<h2 style="margin-top:0">${esc(t(IS_PH ? 'Stock of {b}' : 'Catalogue and stock of {b}', { b: loc.name }))}</h2>
<p class="muted">${esc(t(IS_PH ? 'Each branch has its own stock. Change the branch at the top of the page.' : 'Each depot has its own stock. Change the depot at the top of the page.'))}</p>
${writable ? '' : `<p class="lock">${esc(t(IS_PH ? 'Stock and prices can be recorded once ApexRX approves your pharmacy.' : 'Your catalogue can be edited once ApexRX approves your business.'))}</p>`}
${writable && !canManage() ? `<p class="note" style="margin:0 0 12px">${esc(t('As staff you can update quantities. Prices and listing are managed by owners and managers.'))}</p>` : ''}
${b ? '' : `<p class="note" id="batches-off" style="margin:0 0 12px"><span class="tag">${esc(t('Not connected yet'))}</span> ${esc(t(BATCHES_OFF))}</p>`}
${writable && canManage() ? `<div class="up"><div class="row"><strong>${esc(t('Upload your stock'))}</strong><label class="ghost" style="cursor:pointer">${esc(t('Choose a CSV file'))}<input id="csv" type="file" accept=".csv,text/csv" hidden></label><button class="ghost" data-a="tpl">${esc(t('Download the CSV template'))}</button></div>
<p class="note" style="margin:8px 0 0">${esc(t('Columns: Item description, Pack size, Batch number, Unit price, Total price, Expiry date (YYYY-MM-DD), Quantity. Total price is the price of one box. Quantity is the number of boxes. Each row must match a medicine in the ApexRX catalogue.'))}${b ? '' : ' ' + esc(t('Batch number and expiry date are optional for now and are not saved.'))}</p><div id="imp"></div></div>
<form id="addf" class="up"><div class="addf"><label>${esc(t('Item description'))}<input id="a-s" type="search" placeholder="${esc(t('Type to search'))}" autocomplete="off"><select id="a-p" aria-label="${esc(t('Choose the medicine'))}" required><option value="">${esc(t('Choose the medicine'))}</option></select></label><label>${esc(t('Batch number'))}<input id="a-b" maxlength="60"${off}></label><label>${esc(t('Unit price'))}<input id="a-unit" type="number" min="0" step="any"></label><label>${esc(t('Total price'))}<input id="a-u" type="number" min="0" step="any"></label><label>${esc(t('Expiry date'))}<input id="a-e" type="date"${off}></label><label>${esc(t('Quantity'))}<input id="a-q" type="number" min="0" step="1" required></label><label>${esc(t('Low stock alert'))}<input id="a-t" type="number" min="0" step="1" value="${IS_PH ? 10 : 100}" required></label><button class="solid">${esc(t('Add item'))}</button></div></form>` : ''}
<div class="bar"><label class="grow"><span class="sr">${esc(t('Filter your stock'))}</span><input id="sf" type="search" value="${esc(S.sf)}" placeholder="${esc(t('Filter by item or batch number'))}" autocomplete="off"></label>${writable ? `<button class="solid" data-a="conf">${esc(t('Confirm all as still correct'))}</button>` : ''}</div>
<div class="tbl"><table class="stock"><thead><tr><th>${esc(t('Item description'))}</th><th>${esc(t('Pack size'))}</th><th>${esc(t('Batch number'))}</th><th>${esc(t('Unit price'))}</th><th>${esc(t('Total price'))}</th><th>${esc(t('Expiry date'))}</th><th>${esc(t('Quantity'))}</th><th>${esc(t('Low stock alert'))}</th><th>${esc(t('Listed'))}</th><th>${esc(t(IS_PH ? 'What patients see' : 'What pharmacies see'))}<small>${esc(t('Last confirmed'))}</small></th><th></th></tr></thead><tbody id="srows"></tbody></table></div>
<p class="note">${esc(t(IS_PH ? 'Patients see availability and price, never exact quantities. Expired batches are hidden from patients.' : 'Verified pharmacies see your price and quantity. Other suppliers never do. Expired batches are hidden.'))}</p>`;
    },
    por() {
      if (!isPreview) return `<div class="panel"><h2>${esc(t('Patient ordering is coming soon'))}</h2><p class="muted" style="margin:0">${esc(t('Patients can already find the medicines you list, with their availability and price. Ordering from the app is not live yet, so no patient orders can arrive here.'))}</p></div>`;
      return `<p class="muted">${esc(t('Sample orders. Accept an order to prepare it for pickup, or decline it.'))}</p><div class="tbl"><table><thead><tr><th>${esc(t('Order'))}</th><th>${esc(t('Item'))}</th><th>${esc(t('Boxes'))}</th><th>${esc(t('Status'))}</th><th></th></tr></thead><tbody>${S.por.map((o, i) => `<tr><td><strong>${esc(o.id)}</strong><small>${esc(o.who)}</small></td><td>${esc(o.m)}</td><td>${o.n}</td><td><span class="tag ${o.st === 'New' ? 'low' : o.st === 'Declined' ? 'out' : 'good'}">${esc(t(o.st))}</span></td><td class="act">${o.st === 'New' ? `<button class="solid" data-a="pya" data-i="${i}">${esc(t('Accept'))}</button><button class="ghost" data-a="pno" data-i="${i}">${esc(t('Decline'))}</button>` : o.st === 'Ready for pickup' ? `<button class="solid" data-a="pdone" data-i="${i}">${esc(t('Mark as collected'))}</button>` : ''}</td></tr>`).join('')}</tbody></table></div>`;
    },
    set() {
      const ids = licenceRows();
      const rows = [[t('Name'), ctx.org.name], ...(IS_PH ? [] : [[t('Supplier ID'), sid()]]), [t('Phone'), ctx.org.phone], [t('Email'), ctx.org.email], ...ids];
      const mgr = canManage(), owner = ctx.myRole === 'owner';
      const branches = [...(ctx.locations || [])].sort((a, b) => (b.is_active - a.is_active) || a.name.localeCompare(b.name));
      const place = l => [l.address, l.village, l.cell, l.sector].filter(Boolean).join(', ');
      return `<h2 style="margin-top:0">${esc(t(IS_PH ? 'Your pharmacy profile' : 'Your supplier profile'))}</h2><div class="panel"><dl class="kv">${rows.filter(r => r[1]).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl>${isPreview ? '' : `<p style="margin:12px 0 0"><a class="ghost" id="open-registration" href="${ONBOARD}?lang=${lang}#review">${esc(t('Registration details and review →'))}</a></p>`}</div>
<h2>${esc(t(IS_PH ? 'Branches' : 'Depots'))}</h2><div class="tbl"><table><thead><tr><th>${esc(t(IS_PH ? 'Branch' : 'Depot'))}</th><th>${esc(t('District'))}</th><th>${esc(t('Address'))}</th><th>${esc(t('Phone'))}</th><th>${esc(t('Status'))}</th><th></th></tr></thead><tbody>${branches.map(l => `<tr data-branch="${l.location_id}"><td><strong>${esc(l.name)}</strong>${l.region ? `<small>${esc(l.region)}</small>` : ''}</td><td>${esc(l.city || '—')}</td><td>${esc(place(l) || '—')}</td><td>${esc(l.phone || '—')}</td><td><span class="tag ${l.is_active ? 'good' : ''}">${esc(t(l.is_active ? 'Active' : 'Inactive'))}</span></td><td class="act">${mgr && !isPreview ? `<button class="ghost" data-a="editloc" data-l="${l.location_id}">${esc(t('Edit'))}</button><button class="ghost" data-a="${l.is_active ? 'offloc' : 'onloc'}" data-l="${l.location_id}">${esc(t(l.is_active ? 'Deactivate' : 'Reactivate'))}</button>` : ''}</td></tr>`).join('') || `<tr><td colspan="6" class="empty">${esc(t('No location yet.'))}</td></tr>`}</tbody></table></div>
${mgr ? `<p><button class="ghost" data-a="addloc">${esc(t(IS_PH ? 'Add a branch' : 'Add a depot'))}</button></p>` : `<p class="note">${esc(t(IS_PH ? 'Only owners and managers can add or change branches.' : 'Only owners and managers can add or change depots.'))}</p>`}
<h2>${esc(t('Team and permissions'))}</h2><div class="tbl"><table><thead><tr><th>${esc(t('Name'))}</th><th>${esc(t('Role'))}</th><th>${esc(t('Can do'))}</th><th>${esc(t('Status'))}</th><th></th></tr></thead><tbody id="team"><tr><td colspan="5" class="empty">${esc(t('Loading…'))}</td></tr></tbody></table></div>
${!mgr ? `<p class="note">${esc(t('Only owners and managers can invite or change team members.'))}</p>`
    : isPreview ? `<p class="note">${esc(t('Invitations are not available in the preview.'))}</p>`
    : `<form id="invite-form" class="up" style="margin-top:12px" novalidate><strong>${esc(t('Invite a team member'))}</strong><p class="note" id="invite-help" style="margin:4px 0 10px"></p><div class="row"><label class="grow" style="flex:1;min-width:200px"><span class="sr">${esc(t('Email'))}</span><input name="email" type="email" required autocomplete="off" placeholder="${esc(t('Their email address'))}"></label><label><span class="sr">${esc(t('Role'))}</span><select name="role" style="width:auto">${(owner ? ['staff', 'manager', 'owner'] : ['staff']).map(r => `<option value="${r}">${esc(t(ROLE_NAMES[r]))}</option>`).join('')}</select></label><button class="solid" id="invite-submit">${esc(t('Create invitation link'))}</button></div><div id="invite-status" aria-live="polite"></div></form>
<div class="tbl"><table><thead><tr><th>${esc(t('Email'))}</th><th>${esc(t('Role'))}</th><th>${esc(t('Status'))}</th><th>${esc(t('Delivery'))}</th><th></th></tr></thead><tbody id="invites"><tr><td colspan="5" class="empty">${esc(t('Loading…'))}</td></tr></tbody></table></div>`}
<h2>${esc(t('Licensing documents'))}</h2><div class="tbl"><table><thead><tr><th>${esc(t('Document'))}</th><th>${esc(t('File'))}</th><th>${esc(t('Status'))}</th></tr></thead><tbody id="docs"><tr><td colspan="3" class="empty">${esc(t('Loading…'))}</td></tr></tbody></table></div>
${canManage() ? `<div class="up" style="margin-top:12px"><div class="row"><label><span class="sr">${esc(t('Document'))}</span><select id="doc-t" style="width:auto">${DOCS().map(([k, l]) => `<option value="${k}">${esc(t(l))}</option>`).join('')}</select></label><label class="ghost" style="cursor:pointer">${esc(t('Upload a file'))}<input id="doc-f" type="file" accept=".pdf,.png,.jpg,.jpeg" hidden></label></div></div>` : ''}`;
    },
    prem() { return `<div id="fc-root"></div>`; }
  };

  // The document types registration uses (js/registration.js).
  const DOCS = () => IS_PH
    ? [['pharmacy_license', 'Pharmacy license'], ['business_license', 'Business license'], ['owner_id', 'Owner ID']]
    : [['business_license', 'Business license'], ['owner_id', 'Owner ID']];
  function licenceRows() {
    const o = ctx.org;
    const rows = IS_PH
      ? [[t('NPC Number'), o.npc_number], [t('Pharmacy license'), o.license_number]]
      : [[t('TIN'), o.tin], [t('Rwanda FDA licence'), o.fda_license_number]];
    return rows.filter(row => row[1]);
  }

  /* ---------------------------------------------------------- conversations */
  function threads() {
    const by = new Map();
    S.orders.forEach(o => {
      const p = partyOf(o), k = p.organization_id;
      if (!by.has(k)) by.set(k, { party: p, orders: [] });
      by.get(k).orders.push(o);
    });
    if (S.newParty && !by.has(S.newParty.organization_id)) by.set(S.newParty.organization_id, { party: S.newParty, orders: [] });
    return [...by.values()];
  }
  const threadPreview = c => {
    const o = c.orders[0];
    return o ? t('Order #{id}', { id: o.purchase_order_id }) + ' · ' + t((STATUS[o.status] || ['', o.status])[1]) : t('New conversation');
  };
  function ovList() {
    const el = $('#ovlist'); if (!el) return;
    const q = S.ovq.toLowerCase();
    el.innerHTML = threads().filter(c => !q || c.party.name.toLowerCase().includes(q)).slice(0, 6).map(c => `<div class="ov-row"><span class="av">${esc(initials(c.party.name))}</span><div><strong>${esc(c.party.name)}</strong><small>${esc(threadPreview(c))}</small></div><button class="ghost" data-a="conv" data-c="${c.party.organization_id}">${esc(t('Open chat ↗'))}</button></div>`).join('')
      || `<p class="empty">${esc(t(S.ovq ? 'No conversation matches your search.' : IS_PH ? 'No conversations yet. Ask a supplier for a quote to start one.' : 'No requests yet. They appear here when a pharmacy asks you for prices.'))}</p>`;
  }
  function clist() {
    const list = threads();
    if (!S.party && list.length) S.party = list[0].party.organization_id;
    $('#clist').innerHTML = list.map(c => `<button class="citem" data-a="conv" data-c="${c.party.organization_id}"${c.party.organization_id === S.party ? ' aria-current="true"' : ''}><strong>${esc(c.party.name)}</strong><span>${esc(threadPreview(c))}</span>${c.orders.some(needsMe) ? `<i class="dot" title="${esc(t('Waiting for your answer'))}"></i>` : ''}</button>`).join('') || `<p class="empty">${esc(t('No conversations yet.'))}</p>`;
  }
  const itemTable = (o, confirmed) => `<table class="lt"><thead><tr><th>${esc(t('Item'))}</th><th>${esc(t('Boxes'))}</th><th>${esc(t('Per box'))}</th></tr></thead><tbody>${o.items.map(i => `<tr><td>${esc(fullLabel(i))}</td><td>${confirmed ? i.confirmed_quantity ?? i.requested_quantity : i.requested_quantity}</td><td>${money(confirmed ? i.confirmed_unit_price ?? i.requested_unit_price : i.requested_unit_price, o.currency)}</td></tr>`).join('')}</tbody></table>`;
  function orderBubbles(o) {
    const fromPh = IS_PH ? 'out' : 'in', fromSup = IS_PH ? 'in' : 'out';
    const parts = [`<div class="b ${fromPh}"><strong>${esc(t('Order list #{id}', { id: o.purchase_order_id }))}</strong>${itemTable(o, false)}<div class="tot">${esc(t('Total'))} ${money(o.requested_total, o.currency)}</div>${o.notes ? `<p style="margin:6px 0">${esc(o.notes)}</p>` : ''}<span class="tm">${esc(fmtTime(o.submitted_at || o.created_at))}</span></div>`];
    (o.history || []).forEach(h => {
      if (h.to_status === 'submitted') return;
      if (h.to_status === 'countered') {
        parts.push(`<div class="b ${fromSup}"><strong>${esc(t('Price offer'))}</strong>${itemTable(o, true)}<div class="tot">${esc(t('Total'))} ${money(o.confirmed_total ?? o.requested_total, o.currency)}</div>${h.note ? `<p style="margin:6px 0">${esc(h.note)}</p>` : ''}<span class="tm">${esc(fmtTime(h.changed_at))}</span></div>`);
      } else {
        parts.push(`<div class="sysm">${esc(t('Order #{id}', { id: o.purchase_order_id }))}: ${esc(t((STATUS[h.to_status] || ['', h.to_status])[1]))}${h.note ? ' · ' + esc(h.note) : ''} · ${esc(fmtTime(h.changed_at))}</div>`);
      }
    });
    const btns = actionButtons(o);
    if (btns) parts.push(`<div class="qa" style="align-self:center">${btns}</div>`);
    return parts.join('');
  }
  async function thread() {
    const el = $('#thread'); if (!el) return;
    clist();
    const c = threads().find(x => x.party.organization_id === S.party);
    if (!c) { el.innerHTML = `<p class="empty">${esc(t(IS_PH ? 'Pick a supplier in Compare prices to start a conversation.' : 'No requests yet.'))}</p>`; return; }
    const p = c.party, hasWa = !!wa(p.whatsapp_phone || p.phone);
    el.innerHTML = `<div class="th"><span class="av">${esc(initials(p.name))}</span><div><strong>${esc(p.name)}</strong><small>${esc(p.location_name || '')}</small></div>${p.phone ? `<a class="ghost" href="tel:${esc(String(p.phone).replace(/[^\d+]/g, ''))}">${esc(t('Call'))}</a>` : ''}</div>
<div class="msgs" id="msgs"><p class="empty">${esc(t('Loading…'))}</p></div>
${S.listOpen ? `<div class="lb"><strong>${esc(t('Order list'))}</strong><p class="note" style="margin:2px 0">${esc(t('One item per line, with the number of boxes. Example: Paracetamol 500mg x 20'))}</p><textarea id="lt" rows="5" placeholder="Paracetamol 500mg x 20&#10;Amoxicillin 500mg x 10"></textarea><div id="lp"></div><div class="qa"><button class="solid" data-a="lsend">${esc(t('Send list'))}</button><button class="ghost" data-a="lclose">${esc(t('Cancel'))}</button></div></div>` : ''}
<form class="composer" id="sendf">${IS_PH && approved() ? `<button type="button" class="ic" data-a="lopen" title="${esc(t('Write an order list'))}" aria-label="${esc(t('Write an order list'))}">📋</button>` : ''}<textarea id="msg" rows="1" aria-label="${esc(t('Type a message'))}" placeholder="${esc(t(hasWa ? 'Type a message' : 'This contact has no WhatsApp number'))}"${hasWa ? '' : ' disabled'}></textarea><button class="solid"${hasWa ? '' : ' disabled'}>${esc(t('Send on WhatsApp'))}</button></form>`;
    const party = S.party;
    try {
      const full = await Promise.all(c.orders.slice(0, 8).map(o => data.order(o.purchase_order_id)));
      if (party !== S.party || !$('#msgs')) return;
      full.forEach(o => S.full.set(o.purchase_order_id, o));
      const box = $('#msgs');
      box.innerHTML = full.reverse().map(orderBubbles).join('') || `<p class="empty">${esc(t(IS_PH ? 'Send an order list to ask this supplier for prices.' : 'No orders yet.'))}</p>`;
      box.scrollTop = box.scrollHeight;
    } catch (err) { $('#msgs').innerHTML = `<p class="empty">${esc(err.message)}</p>`; }
    if (S.listOpen) $('#lt').focus();
  }

  function parseList(txt) {
    return txt.split('\n').map(x => x.trim()).filter(Boolean).map(raw => {
      let q = 0, s = raw, m = s.match(/(?:x|×|\*|:|=)\s*(\d+)\s*$/i) || s.match(/\s-\s*(\d+)\s*$/);
      if (m) { q = +m[1]; s = s.slice(0, m.index).trim(); } else { m = s.match(/^(\d+)\s*(?:x|×|\*)?\s+/i); if (m) { q = +m[1]; s = s.slice(m[0].length).trim(); } }
      return { raw, term: s, qty: q || 1, offer: null };
    });
  }
  const matchesWords = (term, text) => term.toLowerCase().replace(/[^a-z0-9./ ]/g, ' ').split(/\s+/).filter(Boolean).every(w => text.toLowerCase().includes(w));
  let listRun = 0;
  const previewList = debounce(async () => {
    const box = $('#lt'); if (!box) return;
    const run = ++listRun, rows = parseList(box.value);
    await Promise.all(rows.map(async r => {
      const first = r.term.split(/\s+/)[0];
      if (first.length < 2) return;
      try {
        const hits = await data.offers({ q: first, supplier_organization_id: S.party });
        r.offer = hits.find(o => matchesWords(r.term, fullLabel(o) + ' ' + o.drug_name)) || null;
      } catch (e) { r.offer = null; }
    }));
    if (run !== listRun || !$('#lp')) return;
    S.listRows = rows;
    const ok = rows.filter(r => r.offer).length;
    $('#lp').innerHTML = rows.length ? `<p class="note">${esc(t('{a} of {b} lines found in this supplier’s list. The others will not be sent.', { a: ok, b: rows.length }))}</p><table class="lt"><tbody>${rows.map(r => `<tr><td>${esc(r.offer ? fullLabel(r.offer) : r.raw)}</td><td>${r.qty}</td><td>${r.offer ? `<span class="tag good">${money(r.offer.unit_price, r.offer.currency)}</span>` : `<span class="tag low">${esc(t('not found'))}</span>`}</td></tr>`).join('')}</tbody></table>` : '';
  }, 300);

  /* --------------------------------------------------------------- compare */
  let cmpRun = 0;
  async function loadOffers() {
    const body = $('#rows'); if (!body) return;
    if (!approved()) { body.innerHTML = `<tr><td colspan="6" class="empty">${esc(t('Supplier prices open once your pharmacy is approved.'))}</td></tr>`; return; }
    const run = ++cmpRun, loc = curLoc(), geo = loc && loc.latitude != null ? { lat: loc.latitude, lng: loc.longitude } : {};
    const sort = S.sort === 'distance' && geo.lat != null ? 'distance' : 'price';
    const q = S.q.trim();
    try {
      let res;
      if (q.length >= 2) res = await data.offers({ q, sort, ...geo });
      else {
        // The API searches by medicine, so browsing asks for one medicine at a time.
        const drugs = S.drugs.filter(d => !S.cat || d.therapeutic_class === S.cat).slice(0, 12);
        const pages = await Promise.all(drugs.map(d => data.offers({ drug_id: d.drug_id, sort, ...geo })));
        res = [...new Map(pages.flat().map(o => [o.offer_id, o])).values()];
      }
      if (run !== cmpRun || !$('#rows')) return;
      S.offers = res; renderOffers();
    } catch (err) { if (run === cmpRun && $('#rows')) $('#rows').innerHTML = `<tr><td colspan="6" class="empty">${esc(err.message)}</td></tr>`; }
  }
  function renderOffers() {
    const cls = id => (S.drugs.find(d => d.drug_id === id) || {}).therapeutic_class || t('Other');
    const r = S.offers.filter(o => !S.cat || cls(o.drug_id) === S.cat);
    const min = {}, count = {}, groups = {};
    r.forEach(o => {
      min[o.product_id] = Math.min(min[o.product_id] ?? Infinity, Number(o.unit_price));
      count[o.product_id] = (count[o.product_id] || 0) + 1;
      const c = cls(o.drug_id); (groups[c] = groups[c] || { m: new Set(), n: 0 }).m.add(o.product_id); groups[c].n++;
    });
    r.sort((a, b) => cls(a.drug_id).localeCompare(cls(b.drug_id)) || (S.sort === 'distance' ? (a.distance_km ?? 1e9) - (b.distance_km ?? 1e9) : a.product_name.localeCompare(b.product_name) || a.unit_price - b.unit_price));
    let last = '';
    $('#rows').innerHTML = r.map(o => {
      const c = cls(o.drug_id), best = Number(o.unit_price) === min[o.product_id] && count[o.product_id] > 1;
      const head = c !== last ? `<tr class="grp"><td colspan="6">${esc(c)}<small>${esc(pl(groups[c].n, '{n} offer', '{n} offers'))}</small></td></tr>` : ''; last = c;
      const dir = maps(o);
      return head + `<tr class="${best ? 'best' : ''}"><td><strong>${esc(fullLabel(o))}</strong></td><td><strong>${esc(o.supplier_name)}</strong><small>${esc([o.location_name, o.city].filter(Boolean).join(', '))}</small>${dir ? `<small><a href="${dir}" target="_blank" rel="noopener">${esc(t('Directions'))}</a></small>` : ''}</td><td>${o.distance_km != null ? o.distance_km.toFixed(1) + ' km' : '—'}</td><td><strong>${money(o.unit_price, o.currency)}</strong>${best ? ` <span class="tag good">${esc(t('Best price'))}</span>` : ''}</td><td>${esc(pl(o.quantity, '{n} box', '{n} boxes'))}</td><td class="act"><button class="ghost" data-a="chat" data-i="${o.offer_id}">${esc(t('Message'))}</button><button class="solid" data-a="quote" data-i="${o.offer_id}">${esc(t('Ask for quote'))}</button></td></tr>`;
    }).join('') || `<tr><td colspan="6" class="empty">${esc(t(S.q ? 'No supplier lists this medicine. Try another name.' : 'No supplier offers yet.'))}</td></tr>`;
  }

  /* ----------------------------------------------------------------- stock */
  function stockRows() {
    const el = $('#srows'); if (!el) return;
    const f = S.sf.toLowerCase(), edit = approved(), mgr = edit && canManage();
    const match = x => (fullLabel(x) + ' ' + (x.batches || []).map(b => b.batch_number).join(' ')).toLowerCase().includes(f);
    el.innerHTML = S.stock.filter(match).map(x => {
      const [cls, text] = seesLabel(x), id = x.product_id, price = x.offer ? Number(x.offer.unit_price) : '', pack = packCount(x.pack_size);
      const unit = price !== '' && pack ? money2(price / pack) : '—';
      const rows = (x.batches && x.batches.length ? x.batches : [null]);
      const span = rows.length > 1 ? ` rowspan="${rows.length}"` : '';
      const lead = `<td${span}><strong>${esc(label(x))}</strong><small>${esc(x.drug_name)}</small></td><td${span}>${esc(x.pack_size)}</td>`;
      const priceCells = `<td${span}>${unit}</td><td${span}><input class="qty" type="number" min="0" step="any" value="${price}" data-f="price" data-p="${id}" aria-label="${esc(t('Total price'))}: ${esc(label(x))}"${mgr ? '' : ' disabled'}></td>`;
      const tail = `<td${span}><input class="qty" type="number" min="0" step="1" value="${threshold(x)}" data-f="thr" data-p="${id}" aria-label="${esc(t('Low stock alert'))}: ${esc(label(x))}"${mgr && x.offer ? '' : ' disabled'}></td>
<td${span}><input type="checkbox" data-f="listed" data-p="${id}" aria-label="${esc(t('Listed'))}: ${esc(label(x))}"${x.offer && x.offer.is_listed ? ' checked' : ''}${mgr && x.offer ? '' : ' disabled'}></td>
<td${span}><span class="tag ${cls}">${esc(text)}</span><small>${esc(ago(x.last_updated))}</small></td>
<td${span} class="act">${edit && hasBatches() ? `<button class="ghost" data-a="addbatch" data-p="${id}">${esc(t('Add batch'))}</button>` : ''}${mgr ? `<button class="ghost" data-a="rmstock" data-p="${id}">${esc(t('Remove'))}</button>` : ''}</td>`;
      return rows.map((b, i) => {
        const left = b ? daysLeft(b.expiry_date) : null;
        const flag = !b ? '' : left < 0 ? ` <span class="tag out">${esc(t('Expired'))}</span>` : left <= 90 ? ` <span class="tag low">${esc(t('{n} days left', { n: left }))}</span>` : '';
        const num_ = b ? `<td><strong>${esc(b.batch_number)}</strong></td>` : `<td class="muted-c">${esc(t(hasBatches() ? 'No batch yet' : 'Not connected yet'))}</td>`;
        const exp = b ? `<td class="exp-c"><input type="date" value="${esc(b.expiry_date)}" data-f="bexp" data-p="${id}" data-b="${b.batch_id}" aria-label="${esc(t('Expiry date'))}: ${esc(b.batch_number)}"${edit ? '' : ' disabled'}>${flag}</td>` : '<td>—</td>';
        const qty = b
          ? `<td><div class="qty-c"><input class="qty" type="number" min="0" step="1" value="${b.quantity}" data-f="bqty" data-p="${id}" data-b="${b.batch_id}" aria-label="${esc(t('Quantity'))}: ${esc(b.batch_number)}"${edit ? '' : ' disabled'}>${edit ? `<button class="x" data-a="rmbatch" data-p="${id}" data-b="${b.batch_id}" title="${esc(t('Remove batch'))}" aria-label="${esc(t('Remove batch'))}: ${esc(b.batch_number)}">×</button>` : ''}</div></td>`
          : `<td><input class="qty" type="number" min="0" step="1" value="${x.quantity}" data-f="qty" data-p="${id}" aria-label="${esc(t('Quantity'))}: ${esc(label(x))}"${edit ? '' : ' disabled'}></td>`;
        return i === 0 ? `<tr data-product="${id}">${lead}${num_}${priceCells}${exp}${qty}${tail}</tr>` : `<tr class="more">${num_}${exp}${qty}</tr>`;
      }).join('');
    }).join('') || `<tr><td colspan="11" class="empty">${esc(t(S.stock.length ? 'No item matches.' : 'No stock yet. Add your first item above.'))}</td></tr>`;
  }
  async function saveField(input) {
    const pid = +input.dataset.p, x = S.stock.find(s => s.product_id === pid), f = input.dataset.f;
    if (!x) return;
    try {
      if (f === 'bqty' || f === 'bexp') {
        const body = f === 'bqty' ? { quantity: Math.max(0, parseInt(input.value, 10) || 0) } : { expiry_date: input.value };
        if (f === 'bexp' && !input.value) { stockRows(); return; }
        const next = await data.updateBatch(S.loc, pid, +input.dataset.b, body);
        Object.assign(x, next);
      } else if (f === 'qty') {
        const q = Math.max(0, parseInt(input.value, 10) || 0);
        await data.setQuantity(S.loc, pid, q); x.quantity = q;
      } else {
        const o = x.offer || { unit_price: 0, low_stock_threshold: 5, is_listed: true };
        const next = { unit_price: Number(o.unit_price), low_stock_threshold: o.low_stock_threshold, is_listed: o.is_listed };
        if (f === 'price') {
          if (input.value === '') { await data.removeOffer(S.loc, pid); x.offer = null; stockRows(); return; }
          next.unit_price = Number(input.value);
        }
        if (f === 'thr') next.low_stock_threshold = Math.max(0, parseInt(input.value, 10) || 0);
        if (f === 'listed') next.is_listed = input.checked;
        await data.setOffer(S.loc, pid, next); x.offer = { ...o, ...next };
      }
      x.last_updated = new Date().toISOString();
      toast(t(IS_PH ? 'Saved. Patients now see: {s}.' : 'Saved. Pharmacies now see: {s}.', { s: seesLabel(x)[1] }));
    } catch (err) { fail(err); }
    stockRows(); badges();
  }
  const searchProducts = debounce(async q => {
    const sel = $('#a-p'); if (!sel) return;
    if (q.trim().length < 2) return;
    try {
      const items = await data.products(q.trim());
      sel.innerHTML = `<option value="">${esc(t(items.length ? 'Choose the medicine' : 'Not in the catalogue. Ask ApexRX to add it.'))}</option>` + items.map(p => `<option value="${p.product_id}" data-pack="${packCount(p.pack_size)}">${esc(fullLabel(p))}</option>`).join('');
      if (items.length === 1) sel.value = items[0].product_id;
    } catch (err) { fail(err); }
  }, 250);
  // Either price is enough: the total price of a box is what the platform stores.
  function boxPrice(unit, total, pack) {
    if (total !== '' && total != null) return Number(total);
    return unit !== '' && unit != null && pack ? Number(unit) * pack : null;
  }
  const savedText = () => t('Item saved.');
  async function addItem(form) {
    const pid = +$('#a-p').value, qty = parseInt($('#a-q').value, 10), thr = parseInt($('#a-t').value, 10);
    if (!pid) { toast(t('Choose the medicine')); return; }
    const opt = $('#a-p').selectedOptions[0], price = boxPrice($('#a-unit').value, $('#a-u').value, +(opt.dataset.pack || 0));
    if (price == null) { toast(t('Enter the unit price or the total price.')); return; }
    const btn = form.querySelector('button'); btn.disabled = true;
    try {
      if (hasBatches()) await data.setBatch(S.loc, pid, { batch_number: $('#a-b').value.trim(), expiry_date: $('#a-e').value, quantity: qty });
      else await data.setQuantity(S.loc, pid, qty);
      await data.setOffer(S.loc, pid, { unit_price: price, low_stock_threshold: thr, is_listed: true });
      S.stock = await data.stock(S.loc);
      toast(savedText()); stay('stk');
    } catch (err) { fail(err); btn.disabled = false; }
  }
  async function addBatch(x) {
    const first = !(x.batches && x.batches.length);
    const fd = await ask(t('Add batch'), `<p class="muted" style="margin:0">${esc(fullLabel(x))}</p>${first && x.quantity ? `<p class="note">${esc(t('This item has {n} boxes without a batch. The batches you add replace that number.', { n: x.quantity }))}</p>` : ''}<label>${esc(t('Batch number'))}<input name="n" maxlength="60" required></label><label>${esc(t('Expiry date'))}<input name="e" type="date" required></label><label>${esc(t('Quantity'))}<input name="q" type="number" min="0" step="1" value="${first ? x.quantity : ''}" required></label>`, t('Save'));
    if (!fd) return;
    try {
      Object.assign(x, await data.setBatch(S.loc, x.product_id, { batch_number: fd.get('n').trim(), expiry_date: fd.get('e'), quantity: +fd.get('q') }));
      toast(savedText()); stockRows(); badges();
    } catch (err) { fail(err); }
  }

  /* CSV import: one row per batch. */
  const COLS = { itemdescription: 'd', description: 'd', item: 'd', medicine: 'd', packsize: 'pk', batchnumber: 'b', batch: 'b', unitprice: 'unit', totalprice: 'p', pricebox: 'p', priceperbox: 'p', price: 'p', expirydate: 'exp', expiry: 'exp', expireddate: 'exp', quantity: 'qty', qty: 'qty', lowstockalert: 'thr', threshold: 'thr' };
  function parseCSV(s) {
    const rows = []; let r = [], f = '', q = false;
    for (let i = 0; i < s.length; i++) {
      const c = s[i];
      if (q) { if (c === '"') { if (s[i + 1] === '"') { f += '"'; i++; } else q = false; } else f += c; }
      else if (c === '"') q = true;
      else if (c === ',' || c === ';') { r.push(f); f = ''; }
      else if (c === '\n') { r.push(f); rows.push(r); r = []; f = ''; }
      else if (c !== '\r') f += c;
    }
    if (f || r.length) { r.push(f); rows.push(r); }
    return rows.filter(x => x.some(v => v.trim()));
  }
  async function readCSV(file) {
    if (!file) return;
    const rows = parseCSV((await file.text()).replace(/^﻿/, ''));
    if (rows.length < 2) { toast(t('The file has no data rows.')); return; }
    const map = rows[0].map(h => COLS[h.toLowerCase().replace(/[^a-z]/g, '')] || null);
    const needed = hasBatches() ? ['d', 'b', 'exp', 'qty'] : ['d', 'qty'];
    if (!needed.every(k => map.includes(k)) || !(map.includes('p') || map.includes('unit'))) { toast(t('Missing columns. Download the template to see the expected columns.')); return; }
    toast(t('Checking your file…'));
    const checked = await Promise.all(rows.slice(1, 301).map(async (cells, i) => {
      const o = {}; map.forEach((k, j) => { if (k) o[k] = (cells[j] || '').trim(); });
      const row = { n: i + 2, d: o.d, pk: o.pk, batch: o.b, exp: o.exp, price: null, qty: parseInt(o.qty, 10), thr: o.thr === undefined || o.thr === '' ? (IS_PH ? 10 : 100) : parseInt(o.thr, 10), e: '', warn: '', product: null };
      const pack = packCount(o.pk);
      if (!o.d) row.e = t('item description missing');
      else if (hasBatches() && !o.b) row.e = t('batch number missing');
      else if (hasBatches() && (!/^\d{4}-\d{2}-\d{2}$/.test(o.exp || '') || Number.isNaN(+new Date(o.exp)))) row.e = t('expiry date must be YYYY-MM-DD');
      else if (!((row.price = boxPrice(o.unit, o.p, pack)) >= 0) || row.price == null) row.e = t('unit price or total price missing');
      else if (!(row.qty >= 0)) row.e = t('quantity missing');
      else {
        if (o.unit && o.p && pack && Math.abs(Number(o.p) - Number(o.unit) * pack) > 1) row.warn = t('total price differs from unit price times pack size');
        try {
          const hits = await data.products(o.d.split(/\s+/)[0]);
          row.product = hits.find(p => matchesWords(o.d, fullLabel(p) + ' ' + p.drug_name) && (!o.pk || matchesWords(o.pk, p.pack_size || ''))) || hits.find(p => matchesWords(o.d, fullLabel(p) + ' ' + p.drug_name)) || null;
          if (!row.product) row.e = t('not in the catalogue');
        } catch (err) { row.e = err.message; }
      }
      return row;
    }));
    S.imp = { rows: checked }; renderImp();
  }
  function renderImp() {
    const el = $('#imp'); if (!el) return;
    if (!S.imp) { el.innerHTML = ''; return; }
    const ok = S.imp.rows.filter(r => !r.e);
    el.innerHTML = `<div class="tbl" style="margin-top:12px"><table style="min-width:520px"><thead><tr><th>${esc(t('Row'))}</th><th>${esc(t('Item'))}</th><th>${esc(t('Batch number'))}</th><th>${esc(t('Check'))}</th></tr></thead><tbody>${S.imp.rows.slice(0, 50).map(r => `<tr><td>${r.n}</td><td>${esc(r.product ? fullLabel(r.product) : r.d)}</td><td>${esc(r.batch || '')}</td><td>${r.e ? `<span class="tag out">${esc(r.e)}</span>` : r.warn ? `<span class="tag low">${esc(r.warn)}</span>` : '<span class="tag good">OK</span>'}</td></tr>`).join('')}</tbody></table></div>
<div class="qa"><button class="solid" data-a="doimp"${ok.length ? '' : ' disabled'}>${esc(pl(ok.length, 'Import {n} valid row', 'Import {n} valid rows'))}</button><button class="ghost" data-a="noimp">${esc(t('Cancel'))}</button><span class="note" style="margin:0">${esc(t('{n} row(s) with errors will be skipped.', { n: S.imp.rows.length - ok.length }))}</span></div>`;
  }
  async function doImport(btn) {
    btn.disabled = true;
    let done = 0;
    try {
      for (const r of S.imp.rows.filter(row => !row.e)) {
        if (hasBatches()) await data.setBatch(S.loc, r.product.product_id, { batch_number: r.batch, expiry_date: r.exp, quantity: r.qty });
        else await data.setQuantity(S.loc, r.product.product_id, r.qty);
        await data.setOffer(S.loc, r.product.product_id, { unit_price: r.price, low_stock_threshold: r.thr, is_listed: true });
        done++;
      }
      toast(pl(done, '{n} item imported.', '{n} items imported.'));
    } catch (err) { toast(t('{n} saved, then an error stopped the import:', { n: done }) + ' ' + err.message); }
    S.imp = null; S.stock = await data.stock(S.loc); stay('stk');
  }

  /* ---------------------------------------------------------------- orders */
  async function orderRows() {
    const el = $('#orows'); if (!el) return;
    if (!S.orders.length) { el.innerHTML = `<tr><td colspan="6" class="empty">${esc(t(IS_PH ? 'No orders yet. Ask a supplier for a quote in Compare prices.' : 'No orders yet. They appear here when a pharmacy sends a request.'))}</td></tr>`; return; }
    const rows = await Promise.all(S.orders.slice(0, 30).map(async o => {
      const c = S.full.get(o.purchase_order_id);
      if (c && c.updated_at === o.updated_at) return c;
      try { const f = await data.order(o.purchase_order_id); S.full.set(o.purchase_order_id, f); return f; } catch (e) { return o; }
    }));
    if (!$('#orows')) return;
    el.innerHTML = rows.map(o => {
      const p = partyOf(o), total = o.confirmed_total ?? o.requested_total;
      return `<tr data-order="${o.purchase_order_id}"><td><strong>#${o.purchase_order_id}</strong><small>${esc(fmtDate(o.created_at))}${o.pharmacy.location_name ? ', ' + esc(o.pharmacy.location_name) : ''}</small></td><td><strong>${esc(p.name)}</strong><small>${esc(p.location_name || '')}</small></td><td>${o.items ? `<details><summary>${esc(pl(o.items.length, '{n} item', '{n} items'))}</summary>${o.items.map(i => `<small>${esc(fullLabel(i))} x ${i.confirmed_quantity ?? i.requested_quantity}</small>`).join('')}</details>` : esc(pl(o.item_count, '{n} item', '{n} items'))}</td><td>${money(total, o.currency)}</td><td>${statusTag(o.status)}</td><td class="act"><button class="ghost" data-a="conv" data-c="${p.organization_id}">${esc(t('Open chat ↗'))}</button> ${actionButtons(o)}</td></tr>`;
    }).join('');
  }

  /* --------------------------------------------------------------- dialogs */
  function ask(title, bodyHtml, submit) {
    const d = $('#dlg');
    d.innerHTML = `<form method="dialog" id="dlgf"><h2>${esc(title)}</h2>${bodyHtml}<div class="dlg-a"><button type="button" class="ghost" id="dlg-x">${esc(t('Cancel'))}</button><button class="solid">${esc(submit)}</button></div></form>`;
    return new Promise(res => {
      const form = $('#dlgf');
      const finish = v => { d.close(); res(v); };
      form.addEventListener('submit', e => { e.preventDefault(); finish(new FormData(form)); });
      $('#dlg-x').addEventListener('click', () => finish(null));
      d.addEventListener('cancel', () => res(null), { once: true });
      d.showModal();
    });
  }
  async function reload(view) {
    S.orders = await data.orders();
    go(view || S.view);
  }
  // After background work: refresh the screen, unless the user has moved on.
  const stay = v => { if (S.view === v) go(v); else badges(); };
  async function runAction(id, action) {
    const o = S.full.get(id) || await data.order(id);
    let body;
    if (action === 'delete') {
      if (!await ask(t('Delete draft'), `<p>${esc(t('Delete draft order #{id}? It was never sent to the supplier.', { id }))}</p>`, t('Delete draft'))) return;
    } else if (action === 'reject' || action === 'cancel') {
      const fd = await ask(t(ACTIONS[action]), `<label>${esc(t('Reason'))}<textarea name="reason" rows="3" required maxlength="1000"></textarea></label>`, t(ACTIONS[action]));
      if (!fd) return;
      body = { reason: fd.get('reason').trim() };
    } else if (action === 'counter') {
      const fd = await ask(t('Write your offer'), `<p class="note">${esc(t('Change the quantity or price you can offer.'))}</p><table><thead><tr><th>${esc(t('Item'))}</th><th>${esc(t('Boxes'))}</th><th>${esc(t('Per box'))}</th></tr></thead><tbody>${o.items.map(i => `<tr><td>${esc(fullLabel(i))}</td><td><input class="qty" type="number" min="1" step="1" required name="q${i.purchase_order_item_id}" value="${i.requested_quantity}"></td><td><input class="qty" type="number" min="0" step="any" required name="p${i.purchase_order_item_id}" value="${Number(i.requested_unit_price)}"></td></tr>`).join('')}</tbody></table><label>${esc(t('Note (optional)'))}<textarea name="note" rows="2" maxlength="1000"></textarea></label>`, t('Send offer'));
      if (!fd) return;
      body = { items: o.items.map(i => ({ purchase_order_item_id: i.purchase_order_item_id, confirmed_quantity: +fd.get('q' + i.purchase_order_item_id), confirmed_unit_price: +fd.get('p' + i.purchase_order_item_id) })), note: fd.get('note').trim() || null };
    }
    try {
      await data.act(id, action, body);
      toast(action === 'delete' ? t('Draft #{id} deleted.', { id }) : t('Done. Order #{id} is updated.', { id }));
    } catch (err) {
      if (err.status === 409 && err.data && err.data.price_changes) {
        await data.reprice(id);
        toast(t('The supplier changed a price. Check the new total, then send again.'));
      } else fail(err);
    }
    await reload();
  }
  function offerById(id) { return S.offers.find(o => o.offer_id === +id); }
  // Staff prepare orders; an owner or manager sends them. Nothing was sent to the supplier.
  const draftText = o => t('Saved as draft #{id}. It was not sent: an owner or manager must send it from Supplier orders.', { id: o.purchase_order_id });
  async function requestQuote(offer) {
    const fd = await ask(t('Ask for quote'), `<p class="muted" style="margin:0">${esc(fullLabel(offer))}<br>${esc(offer.supplier_name)} · ${money(offer.unit_price, offer.currency)}</p><label>${esc(t('Boxes'))}<input name="qty" type="number" min="1" step="1" value="20" required></label><label>${esc(t('Note (optional)'))}<textarea name="note" rows="2" maxlength="1000"></textarea></label>`, t('Send request'));
    if (!fd) return;
    try {
      const o = await data.sendOrder({ supplierId: offer.supplier_organization_id, supplierLocationId: offer.supplier_location_id, locationId: S.loc, items: [{ product_id: offer.product_id, quantity: +fd.get('qty') }], notes: fd.get('note').trim() });
      toast(o.draft ? draftText(o) : t('Request sent to {s}.', { s: offer.supplier_name }));
      S.party = offer.supplier_organization_id; S.newParty = null;
      await reload('msg');
    } catch (err) { fail(err); }
  }

  /* ----------------------------------------------------------- after render */
  const INVITE_STATUS = { pending: ['low', 'Pending'], accepted: ['good', 'Accepted'], expired: ['', 'Expired'], revoked: ['out', 'Revoked'] };
  let members = [];
  async function loadTeam() {
    const ROLES = { owner: 'Everything, including team and branches', manager: 'Stock, prices and orders', staff: 'Update stock quantities and handle orders' };
    try {
      const [list, docs] = await Promise.all([data.members(), data.documents()]);
      if (!$('#team')) return;
      members = list;
      // Mirrors the backend: owners manage everyone else; managers manage staff only.
      const owner = ctx.myRole === 'owner', me = ctx.user.user_id;
      const editable = m => canManage() && m.user_id !== me && (owner || m.role === 'staff');
      $('#team').innerHTML = list.map(m => {
        const can = editable(m);
        const role = can && owner
          ? `<select data-member="${m.membership_id}" aria-label="${esc(t('Role'))}: ${esc(m.email)}">${['owner', 'manager', 'staff'].map(r => `<option value="${r}"${m.role === r ? ' selected' : ''}>${esc(t(ROLE_NAMES[r]))}</option>`).join('')}</select>`
          : esc(t(ROLE_NAMES[m.role] || m.role));
        return `<tr data-member="${esc(m.email)}"><td><strong>${esc(m.name)}</strong>${m.user_id === me ? ` <small style="display:inline">${esc(t('(you)'))}</small>` : ''}<small>${esc(m.email)}</small></td><td>${role}</td><td>${esc(t(ROLES[m.role]))}</td><td><span class="tag ${m.is_active ? 'good' : ''}">${esc(t(m.is_active ? 'Active' : 'Deactivated'))}</span></td><td class="act">${can ? `<button class="ghost" data-a="tglmem" data-m="${m.membership_id}">${esc(t(m.is_active ? 'Deactivate' : 'Reactivate'))}</button><button class="ghost" data-a="rmmem" data-m="${m.membership_id}">${esc(t('Remove'))}</button>` : ''}</td></tr>`;
      }).join('') || `<tr><td colspan="5" class="empty">${esc(t('No members.'))}</td></tr>`;
      if ($('#invites')) loadInvites();
      const names = Object.fromEntries(DOCS());
      $('#docs').innerHTML = docs.map(d => `<tr><td>${esc(t(names[d.document_type] || d.document_type))}</td><td>${esc(d.file_name)}</td><td><span class="tag ${d.verification_status === 'approved' ? 'good' : d.verification_status === 'rejected' ? 'out' : 'low'}">${esc(t({ approved: 'Approved', rejected: 'Declined', pending: 'Pending verification' }[d.verification_status] || d.verification_status))}</span></td></tr>`).join('') || `<tr><td colspan="3" class="empty">${esc(t('No documents uploaded yet.'))}</td></tr>`;
    } catch (err) { fail(err); }
  }
  /* Invitations: the employee sets up (or signs in to) their own account from a
   * single-use link and joins with the chosen role. Email is temporarily
   * disabled, so the inviter is shown the link once and gives it to them. */
  let invites = [];
  async function loadInvites() {
    try {
      const [list, caps] = await Promise.all([data.invitations(), data.capabilities()]);
      if (!$('#invites')) return;
      invites = list;
      const emailing = !!caps.invitation_emails;
      $('#invite-help').textContent = t(emailing
        ? 'They receive an email to set up their own account (or sign in) and join. Accounts are never shared.'
        : 'Email is temporarily unavailable, so ApexRX cannot email invitations. You get a single-use link to give the employee yourself (for example by WhatsApp). They use it to set up their own account and join. Accounts are never shared.');
      $('#invite-submit').textContent = t(emailing ? 'Send invitation' : 'Create invitation link');
      const owner = ctx.myRole === 'owner';
      $('#invites').innerHTML = list.map(inv => {
        const st = INVITE_STATUS[inv.status] || ['', inv.status];
        const delivery = inv.status === 'accepted' ? t('Accepted {d}', { d: fmtTime(inv.accepted_at) }) + ' ' + t(inv.account_created ? '(new account)' : '(existing account)')
          : inv.delivery === 'sent' ? t('Email sent') : inv.delivery === 'failed' ? t('Email not sent')
            : inv.delivery === 'link' ? t('Link given by you (no email)') : t('Not sent yet');
        const manageable = owner || inv.role === 'staff';
        const btns = manageable && ['pending', 'expired'].includes(inv.status)
          ? `<button class="ghost" data-a="reinvite" data-i="${inv.invitation_id}">${esc(t(inv.delivery === 'link' ? 'New link' : 'Resend'))}</button>${inv.status === 'pending' ? `<button class="ghost" data-a="revoke" data-i="${inv.invitation_id}">${esc(t('Revoke'))}</button>` : ''}` : '';
        return `<tr data-invite="${esc(inv.email)}"><td>${esc(inv.email)}</td><td>${esc(t(ROLE_NAMES[inv.role] || inv.role))}</td><td><span class="tag ${st[0]}">${esc(t(st[1]))}</span></td><td>${esc(delivery)}${inv.status === 'pending' ? `<small>${esc(t('Expires {d}', { d: fmtTime(inv.expires_at) }))}</small>` : ''}</td><td class="act">${btns}</td></tr>`;
      }).join('') || `<tr><td colspan="5" class="empty">${esc(t('No invitations yet.'))}</td></tr>`;
    } catch (err) { fail(err); }
  }
  // The link is shown only now; the backend keeps only its hash.
  function showInvite(result, again) {
    const box = $('#invite-status'); if (!box) return;
    if (result.email_sent) { box.innerHTML = `<p class="note">${esc(t(again ? 'Invitation emailed again to {e}. The earlier link no longer works.' : 'Invitation emailed to {e}.', { e: result.email }))}</p>`; return; }
    if (!result.share_token) { box.innerHTML = `<p class="lock">${esc(result.detail || '')}</p>`; return; }
    const base = location.href.split(/[?#]/)[0].replace(/[^/]*$/, '');
    const url = `${base}accept-invitation.html#token=${result.share_token}`;
    box.innerHTML = `<div class="lock" style="margin:12px 0 0"><p style="margin:0 0 6px">${esc(t('Email is temporarily unavailable, so no email was sent. Copy the invitation link below and give it to the employee yourself (for example by WhatsApp). Anyone with the link can use it to join, so share it only with them.'))}</p>
<strong>${esc(t('Invitation link for {e} ({r})', { e: result.email, r: t(ROLE_NAMES[result.role] || result.role) }))}</strong>
<div class="row" style="display:flex;gap:8px;margin:6px 0"><input id="invite-link" type="text" readonly value="${esc(url)}" aria-label="${esc(t('Invitation link for {e}', { e: result.email }))}"><button type="button" class="solid" data-a="copylink">${esc(t('Copy link'))}</button></div>
<small>${esc(t('It works once and expires {d}. It is shown only now: if you lose it, choose “New link” (the old one then stops working).', { d: fmtTime(result.expires_at) }))}</small></div>`;
    $('#invite-link').focus(); $('#invite-link').select();
  }
  async function invite(form) {
    const email = form.elements.email.value.trim(), btn = $('#invite-submit');
    if (!/^\S+@\S+\.\S+$/.test(email)) { $('#invite-status').innerHTML = `<p class="lock" role="alert">${esc(t('Enter the employee’s email address.'))}</p>`; return; }
    btn.disabled = true;
    try {
      const result = await data.invite(email, form.elements.role.value);
      form.elements.email.value = '';
      await loadInvites(); showInvite(result);
    } catch (err) { $('#invite-status').innerHTML = `<p class="lock" role="alert">${esc(errorText(err))}</p>`; } finally { btn.disabled = false; }
  }

  // Branches (pharmacy) or depots (supplier): add and edit with the same dialog.
  async function locationDialog(l) {
    const v = k => esc(l && l[k] != null ? l[k] : '');
    const fd = await ask(t(l ? 'Edit {n}' : IS_PH ? 'Add a branch' : 'Add a depot', { n: l ? l.name : '' }),
      `<label>${esc(t('Name'))}<input name="name" required maxlength="200" value="${v('name')}"></label><label>${esc(t('Province'))}<input name="region" maxlength="100" value="${v('region')}"></label><label>${esc(t('District'))}<input name="city" maxlength="100" value="${v('city')}"></label><label>${esc(t('Sector'))}<input name="sector" maxlength="100" value="${v('sector')}"></label><label>${esc(t('Address'))}<input name="address" maxlength="500" value="${v('address')}"></label><label>${esc(t('Phone'))}<input name="phone" placeholder="+250 788 123 456" value="${v('phone')}"></label><label>${esc(t('WhatsApp'))}<input name="whatsapp_phone" placeholder="+250 788 123 456" value="${v('whatsapp_phone')}"></label><label>${esc(t('Latitude'))}<input name="latitude" type="number" step="any" min="-90" max="90" value="${v('latitude')}"></label><label>${esc(t('Longitude'))}<input name="longitude" type="number" step="any" min="-180" max="180" value="${v('longitude')}"></label>`, t('Save'));
    if (!fd) return;
    const val = k => String(fd.get(k) || '').trim();
    if (!!val('latitude') !== !!val('longitude')) { toast(t('Enter both latitude and longitude, or neither.')); return; }
    const body = { name: val('name') };
    ['region', 'city', 'sector', 'address', 'phone', 'whatsapp_phone'].forEach(k => { if (val(k) || l) body[k] = val(k) || null; });
    if (val('latitude')) { body.latitude = Number(val('latitude')); body.longitude = Number(val('longitude')); } else if (l) { body.latitude = null; body.longitude = null; }
    if (!l && !body.whatsapp_phone && body.phone) body.whatsapp_phone = body.phone;
    try {
      if (l) await data.updateLocation(l.location_id, body); else await data.addLocation(body);
      await refreshLocations(); toast(t('Saved.'));
    } catch (err) { fail(err); }
  }
  async function refreshLocations() {
    ctx.locations = await data.locations();
    if (!activeLocations().some(l => l.location_id === S.loc)) {
      S.loc = (activeLocations()[0] || {}).location_id ?? null;
      S.stock = S.loc ? await data.stock(S.loc) : [];
    }
    chrome(); stay('set');
  }

  let unmountForecast = null;
  const AFTER = {
    home() { ovList(); if (!IS_PH) topRequested(); },
    prem() { unmountForecast = DashForecast.mount($('#fc-root'), { role: ROLE, t, locale: LOCALE }); },
    cmp() { if (S.offers.length) renderOffers(); loadOffers(); },
    msg: thread,
    ord: orderRows,
    stk() { stockRows(); renderImp(); },
    set: loadTeam
  };

  /* ---------------------------------------------------------------- events */
  const ACT = {
    nav: d => go(d.v),
    compare: d => { S.q = d.m; S.cat = ''; go('cmp'); },
    cat: d => { S.cat = d.c; S.q = ''; go('cmp'); },
    conv: d => { S.party = +d.c; S.listOpen = false; go('msg'); },
    chat: d => {
      const o = offerById(d.i); if (!o) return;
      S.party = o.supplier_organization_id;
      S.newParty = { organization_id: o.supplier_organization_id, name: o.supplier_name, location_name: o.location_name, phone: o.phone, whatsapp_phone: o.whatsapp_phone };
      S.listOpen = false; go('msg');
    },
    quote: d => { const o = offerById(d.i); if (o) requestQuote(o); },
    order: d => runAction(+d.o, d.x),
    lopen: () => { S.listOpen = true; thread(); },
    lclose: () => { S.listOpen = false; thread(); },
    async lsend() {
      const found = S.listRows.filter(r => r.offer);
      if (!found.length) { toast(t('No line matches this supplier’s list yet.')); return; }
      const items = [...new Map(found.map(r => [r.offer.product_id, { product_id: r.offer.product_id, quantity: r.qty }])).values()];
      try {
        const o = await data.sendOrder({ supplierId: S.party, supplierLocationId: found[0].offer.supplier_location_id, locationId: S.loc, items });
        S.listOpen = false; S.listRows = []; toast(o.draft ? draftText(o) : t('List sent.'));
        await reload('msg');
      } catch (err) { fail(err); }
    },
    async conf() {
      try { await data.confirmStock(S.loc); S.stock = await data.stock(S.loc); toast(t('Stock confirmed for today.')); stay('stk'); } catch (err) { fail(err); }
    },
    addbatch: d => { const x = S.stock.find(s => s.product_id === +d.p); if (x) addBatch(x); },
    async rmbatch(d) {
      const x = S.stock.find(s => s.product_id === +d.p), b = x && x.batches.find(y => y.batch_id === +d.b);
      if (!b || !await ask(t('Remove this batch?'), `<p>${esc(fullLabel(x))} · ${esc(b.batch_number)}</p>`, t('Remove'))) return;
      try { Object.assign(x, await data.removeBatch(S.loc, x.product_id, b.batch_id)); stockRows(); badges(); } catch (err) { fail(err); }
    },
    async rmstock(d) {
      const x = S.stock.find(s => s.product_id === +d.p); if (!x) return;
      if (!await ask(t('Remove this item?'), `<p>${esc(fullLabel(x))}</p>`, t('Remove'))) return;
      try { await data.removeStock(S.loc, x.product_id); S.stock = S.stock.filter(s => s !== x); stockRows(); badges(); } catch (err) { fail(err); }
    },
    tpl() {
      const later = n => new Date(Date.now() + n * 864e5).toISOString().slice(0, 10);
      const csv = `Item description,Pack size,Batch number,Unit price,Total price,Expiry date,Quantity\nAmoxicillin 500mg,B/20 Capsules,AMX2401,225,4500,${later(400)},40\nParacetamol 500mg,B/30 Tablets,PCM2405,83.33,2500,${later(300)},200\n`;
      const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' })); a.download = 'apexrx-stock-template.csv'; a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    },
    doimp: (d, b) => doImport(b),
    noimp() { S.imp = null; renderImp(); },
    addloc: () => locationDialog(null),
    editloc: d => locationDialog(ctx.locations.find(l => l.location_id === +d.l)),
    async offloc(d) {
      const l = ctx.locations.find(x => x.location_id === +d.l); if (!l) return;
      if (!await ask(t('Deactivate {n}?', { n: l.name }), `<p>${esc(t('It disappears from search and cannot receive orders. Its records are kept and you can reactivate it.'))}</p>`, t('Deactivate'))) return;
      try { await data.updateLocation(l.location_id, { is_active: false }); await refreshLocations(); toast(t('{n} deactivated.', { n: l.name })); } catch (err) { fail(err); }
    },
    async onloc(d) {
      const l = ctx.locations.find(x => x.location_id === +d.l); if (!l) return;
      try { await data.updateLocation(l.location_id, { is_active: true }); await refreshLocations(); toast(t('{n} reactivated.', { n: l.name })); } catch (err) { fail(err); }
    },
    async tglmem(d) {
      const m = members.find(x => x.membership_id === +d.m); if (!m) return;
      if (m.is_active && !await ask(t('Deactivate {n}?', { n: m.email }), `<p>${esc(t('They immediately lose access to {o}.', { o: ctx.org.name }))}</p>`, t('Deactivate'))) return;
      try { await data.updateMember(m.membership_id, { is_active: !m.is_active }); toast(t(m.is_active ? '{n} deactivated.' : '{n} reactivated.', { n: m.email })); loadTeam(); } catch (err) { fail(err); }
    },
    async rmmem(d) {
      const m = members.find(x => x.membership_id === +d.m); if (!m) return;
      if (!await ask(t('Remove {n}?', { n: m.email }), `<p>${esc(t('They are removed from {o}. Their own account is kept.', { o: ctx.org.name }))}</p>`, t('Remove'))) return;
      try { await data.removeMember(m.membership_id); toast(t('{n} removed.', { n: m.email })); loadTeam(); } catch (err) { fail(err); }
    },
    async reinvite(d, b) {
      b.disabled = true;
      try { const result = await data.reinvite(+d.i); await loadInvites(); showInvite(result, true); } catch (err) { fail(err); b.disabled = false; }
    },
    async revoke(d) {
      const inv = invites.find(x => x.invitation_id === +d.i); if (!inv) return;
      if (!await ask(t('Revoke the invitation for {e}?', { e: inv.email }), `<p>${esc(t('Its link stops working.'))}</p>`, t('Revoke'))) return;
      try { await data.revokeInvite(inv.invitation_id); toast(t('Invitation for {e} revoked.', { e: inv.email })); loadInvites(); } catch (err) { fail(err); }
    },
    async copylink(d, b) {
      const f = $('#invite-link'); if (!f) return;
      try { await navigator.clipboard.writeText(f.value); b.textContent = t('Copied'); } catch (err) { f.select(); }
    },
    async resubmit() {
      try { ctx.org = await data.resubmit(); chrome(); go(S.view); toast(t('Sent for review.')); } catch (err) { fail(err); }
    },
    pya: d => { S.por[+d.i].st = 'Ready for pickup'; go('por'); },
    pno: d => { S.por[+d.i].st = 'Declined'; go('por'); },
    pdone: d => { S.por[+d.i].st = 'Collected'; go('por'); },
    retry: () => start()
  };
  document.addEventListener('click', e => {
    const b = e.target.closest('[data-a]');
    if (b && ACT[b.dataset.a] && ctx || (b && b.dataset.a === 'retry')) ACT[b.dataset.a](b.dataset, b);
  });
  $('#theme').addEventListener('click', () => ApexTheme.toggle());
  window.addEventListener('apexrx:theme', paintTheme);
  $('#out').addEventListener('click', () => { data.signOut(); location.href = ONBOARD + '?lang=' + lang + (isPreview ? '' : '#signin'); });
  $('#lang').addEventListener('change', e => {
    lang = e.target.value;
    try { localStorage.setItem('apexrx_lang', lang); } catch (err) { /* ignore */ }
    const u = new URL(location.href); u.searchParams.set('lang', lang); location.href = u.toString();
  });
  document.addEventListener('submit', e => {
    if (e.target.id === 'addf') { e.preventDefault(); addItem(e.target); }
    if (e.target.id === 'sendf') { e.preventDefault(); sendWhatsApp(); }
    if (e.target.id === 'invite-form') { e.preventDefault(); invite(e.target); }
  });
  function sendWhatsApp() {
    const i = $('#msg'), x = i.value.trim(), c = threads().find(y => y.party.organization_id === S.party);
    if (!x || !c) return;
    const url = wa(c.party.whatsapp_phone || c.party.phone, `${x}\n\n— ${ctx.org.name} (ApexRX Smart)`);
    if (url) { window.open(url, '_blank', 'noopener'); i.value = ''; }
  }
  document.addEventListener('keydown', e => { if (e.target.id === 'msg' && e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendWhatsApp(); } });
  const typedOffers = debounce(loadOffers, 300);
  document.addEventListener('input', e => {
    const x = e.target;
    if (x.id === 'q') { S.q = x.value; typedOffers(); }
    else if (x.id === 'sf') { S.sf = x.value; stockRows(); }
    else if (x.id === 'ovq') { S.ovq = x.value; ovList(); }
    else if (x.id === 'lt') previewList();
    else if (x.id === 'a-s') searchProducts(x.value);
  });
  document.addEventListener('change', async e => {
    const x = e.target;
    if (x.id === 'sort') { S.sort = x.value; loadOffers(); }
    else if (x.id === 'br') {
      S.loc = +x.value; S.offers = [];
      try { S.stock = await data.stock(S.loc); } catch (err) { fail(err); }
      go(S.view);
    }
    else if (x.id === 'csv') { readCSV(x.files[0]).catch(fail); x.value = ''; }
    else if (x.id === 'doc-f') {
      const f = x.files[0]; if (!f) return;
      try { await data.uploadDocument($('#doc-t').value, f); toast(t('Document uploaded.')); loadTeam(); } catch (err) { fail(err); }
      x.value = '';
    }
    else if (x.dataset.f) saveField(x);
    else if (x.tagName === 'SELECT' && x.dataset.member) { try { await data.updateMember(+x.dataset.member, { role: x.value }); toast(t('Saved.')); loadTeam(); } catch (err) { fail(err); loadTeam(); } }
  });
  // Signed out anywhere (this page, another tab, inactivity or an ended session):
  // back to sign-in. The registration page explains why.
  window.addEventListener('apexrx:signed-out', e => {
    const reason = e.detail && e.detail.reason;
    location.href = ONBOARD + '?lang=' + lang + (reason && reason !== 'signed_out' ? '&signed_out=' + encodeURIComponent(reason) : '') + '#signin';
  });
  // Another organization: remember it for this tab and open its dashboard.
  $('#org').addEventListener('change', e => {
    const [type, id] = e.target.value.split(':');
    data.choose(type, id);
    location.href = type + '-dashboard.html?lang=' + lang;
  });
  window.addEventListener('apexrx:preview-update', async e => {
    toast(e.detail); S.orders = await data.orders(); badges();
    if (['home', 'msg', 'ord'].includes(S.view)) go(S.view);
  });

  // New requests and answers appear without a page reload.
  let polling = null;
  async function poll(now) {
    if ((document.hidden && !now) || isPreview || !ctx || polling) return;
    polling = data.orders();
    try {
      const next = await polling;
      const sig = l => l.map(o => o.purchase_order_id + o.updated_at).join();
      if (sig(next) === sig(S.orders)) return;
      S.orders = next; badges();
      const busy = $('#dlg').open || ['INPUT', 'TEXTAREA', 'SELECT'].includes((document.activeElement || {}).tagName);
      // Repaint whichever order screen is open now (the user may have moved on).
      if (!busy && ORDER_VIEWS.includes(S.view)) go(S.view);
    } catch (e) { /* the next tick tries again */ } finally { polling = null; }
  }

  /* ----------------------------------------------------------------- start */
  async function start() {
    chrome();
    $('#title').textContent = t('Overview');
    $('#view').innerHTML = `<div class="load" aria-busy="true"><p class="muted">${esc(t('Loading your workspace. The first load can take up to a minute.'))}</p><div class="sk"></div><div class="sk"></div><div class="sk"></div></div>`;
    try {
      const c = await data.boot();
      if (!c.org) {
        if (c.otherRole) location.replace(c.otherRole + '-dashboard.html?lang=' + lang);
        else location.replace(ONBOARD + '?lang=' + lang + '#profile');
        return;
      }
      ctx = c;
      S.loc = (activeLocations()[0] || {}).location_id ?? null;
      const [stock, orders, drugs] = await Promise.allSettled([S.loc ? data.stock(S.loc) : [], data.orders(), IS_PH ? data.drugs() : []]);
      if (stock.status === 'fulfilled') S.stock = stock.value;
      if (orders.status === 'fulfilled') S.orders = orders.value;
      if (drugs.status === 'fulfilled') S.drugs = drugs.value;
      chrome(); go('home');
      setInterval(poll, 45000);
    } catch (err) {
      if (err.status === 401) return;
      $('#view').innerHTML = `<div class="err"><p>${esc(errorText(err))}</p><button class="solid" data-a="retry">${esc(t('Try again'))}</button></div>`;
    }
  }
  start();
})();
