'use strict';
/* Pharmacy and supplier dashboards. <body data-role> picks the role.
 * Data comes from js/dashboard-data.js: the live API, or sample data with ?preview=1.
 * The site's Content-Security-Policy forbids inline scripts and handlers, so every
 * control is wired through the delegated listeners at the bottom of this file. */
(function () {
  const ROLE = document.body.dataset.role;
  const IS_PH = ROLE === 'pharmacy';
  const ONBOARD = IS_PH ? 'pharmacies.html' : 'suppliers.html';
  // Where a signed-out member signs in again: the pharmacy sign-in page, or the supplier page's sign-in.
  const SIGN_IN = IS_PH ? 'pharmacy-sign-in.html' : 'suppliers.html';
  const SIGN_IN_HASH = IS_PH ? '' : '#signin';
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
  if (isPreview && params.get('preview') !== '1') { location.replace(SIGN_IN + '?lang=' + lang + SIGN_IN_HASH); return; }
  const data = D || window.DashData.preview(ROLE);
  const S = { view: 'home', loc: null, stock: [], orders: [], full: new Map(), drugs: [], q: '', cat: '', sort: 'price', sf: '', ovq: '', party: null, newParty: null, listOpen: false, listRows: [], imp: null, offers: [], ins: null, insErr: false, convs: [], unread: 0, chat: null, reqs: [], rq: null, rqOpen: null, rqNew: null, notes: { items: [], unread_count: 0 }, resNew: 0 };
  let ctx = null; // { user, org, myRole, locations }

  const approved = () => ctx.org.status === 'approved';
  const canManage = () => ctx.myRole === 'owner' || ctx.myRole === 'manager';
  // Charts, analytics and forecasting: owners and managers only. The API enforces
  // it too (GET /organizations/{id}/insights refuses staff with 403).
  const seesInsights = () => !!ctx && canManage();
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
    ? [['home', 'Overview'], ['cmp', 'Compare prices'], ['msg', 'Messages'], ['rq', 'Procurement requests'], ['ord', 'Supplier orders'], ['stk', 'My stock'], ['res', 'Reservations'], ['prem', 'Forecasting'], ['set', 'Branches and team']]
    : [['home', 'Overview'], ['msg', 'Messages'], ['rq', 'Procurement requests'], ['ord', 'Orders'], ['stk', 'My catalogue'], ['prem', 'Demand forecast'], ['set', 'Depots and team']];
  const TITLES = { home: 'Overview', cmp: 'Compare prices', msg: 'Messages', rq: 'Procurement requests', ord: IS_PH ? 'Supplier orders' : 'Orders', stk: IS_PH ? 'My stock' : 'My catalogue', res: 'Reservations', set: IS_PH ? 'Branches and team' : 'Depots and team', prem: IS_PH ? 'Forecasting' : 'Demand forecast' };

  function chrome() {
    document.documentElement.lang = lang;
    document.title = t(IS_PH ? 'Pharmacy dashboard' : 'Supplier dashboard') + ' — ApexRX Smart';
    $('#nav').innerHTML = NAV.filter(([v]) => v !== 'prem' || seesInsights()).map(([v, l]) => `<button class="nav" data-a="nav" data-v="${v}">${esc(t(l))}${v === 'prem' ? ` <span class="tag">${esc(t('Premium'))}</span>` : `<span class="badge" id="b-${v}" hidden></span>`}</button>`).join('');
    $('#nav').setAttribute('aria-label', t(IS_PH ? 'Pharmacy workspace' : 'Supplier workspace'));
    $('#p-t').textContent = t('Premium');
    $('#p-d').textContent = t(IS_PH ? 'Demand forecast and more tools, coming with Premium.' : 'Demand forecast for your catalogue.');
    $('#p-b').textContent = t('See the preview'); $('#p-b').dataset.v = 'prem';
    $('.pcard').hidden = !seesInsights();
    $('#br-l').textContent = t(IS_PH ? 'Branch' : 'Depot');
    $('#lang').value = lang;
    paintTheme();
    if (ctx) {
      $('#me-name').textContent = ctx.org.name;
      paintAccount();
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
      ver.textContent = st === 'approved' ? '✓ ' + t('Approved by ApexRX') : t({ pending: 'Pending verification', rejected: 'Not approved', suspended: 'Suspended' }[st] || st);
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
    set('msg', S.unread + waiting().length);
    set('rq', S.reqs.filter(r => r.needs_my_action).length);
    set('ord', IS_PH ? 0 : toConfirm().length);
    set('res', S.resNew);
  }
  function go(v) {
    if (!VIEWS[v] || (v === 'prem' && !seesInsights())) v = 'home';
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
    const img = IS_PH ? 'audience-pharmacies.webp' : 'audience-suppliers.webp';
    const alt = t(IS_PH ? 'A pharmacist scans a box of medicine at the counter' : 'A supplier scans a carton in a medical warehouse');
    const cta = IS_PH ? ['cmp', 'Find a medicine source →'] : ['msg', 'Open requests →'];
    const copy = `<div class="hero-copy"><span class="ov-eyebrow">${esc(t(IS_PH ? 'YOUR NETWORK, WITHIN REACH' : 'YOUR DEMAND, WITHIN REACH'))}</span>
<h2>${esc(hello)}, ${esc(ctx.org.name)}.</h2>
<p>${esc(t(IS_PH ? 'The next step in better care starts with a connection.' : 'Verified pharmacies ask you for prices here, instead of by phone.'))}</p>
<div class="hero-cta"><button class="solid" data-a="nav" data-v="${cta[0]}">${esc(t(cta[1]))}</button><button class="ghost" data-a="nav" data-v="${IS_PH ? 'stk' : 'ord'}">${esc(t(IS_PH ? 'My stock' : 'Orders'))}</button></div></div>`;
    const art = `<figure class="hero-art">
<div class="capsule"><div class="capsule-in"><img src="assets/images/${img}" alt="${esc(alt)}"></div></div>
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
    const convs = threads().length, lowNames = low.slice(0, 4).map(label).join(', '), newRes = S.resNew;
    const att = [
      actRow(newRes, newRes ? pl(newRes, '{n} reservation request waiting for an answer', '{n} reservation requests waiting for an answer') : t('No reservation requests waiting'), isPreview ? t('Patient reservations appear in your live workspace.') : t('Patients reserve medicines at your branches. Answer each request within 24 hours.'), navBtn('res', 'Open reservations')),
      actRow(n, n ? pl(n, '{n} price offer waiting for your answer', '{n} price offers waiting for your answer') : t('No offers waiting'), n ? t('Accept or decline the offer from the supplier.') : t('Ask a supplier for a quote from Compare prices.'), navBtn('msg', 'Open messages')),
      actRow(low.length, low.length ? pl(low.length, '{n} item is running low', '{n} items are running low') : t('Your stock looks healthy'), low.length ? lowNames : t('Nothing to reorder right now.'), low.length ? `<button class="solid" data-a="compare" data-m="${esc(low[0].drug_name)}">${esc(t('Compare prices'))}</button>` : navBtn('cmp', 'Compare prices', true)),
      actRow(S.orders.length, S.orders.length ? pl(S.orders.length, '{n} order sent to suppliers', '{n} orders sent to suppliers') : t('No supplier orders yet'), t('Follow each order from request to delivery.'), navBtn('ord', 'View orders'))
    ];
    return `<div class="ov-top"><span class="ov-eyebrow">${esc(t('PHARMACY OVERVIEW'))}</span><p>${esc(todayText())}</p></div>${hero()}
<div class="ov-cards"><button class="ov-card" data-a="nav" data-v="msg"><span class="ov-i">↗</span><strong>${esc(pl(convs, '{n} supplier conversation', '{n} supplier conversations'))}</strong><small>${esc(t('Explore your conversations →'))}</small></button>
<button class="ov-card" data-a="nav" data-v="set"><span class="ov-i">◎</span><strong>${esc(t('Your pharmacy profile'))}</strong><small>${esc((loc && loc.address) || t('Review your location and details'))} →</small></button>
<div class="ov-card" id="plan-card"><span class="ov-i">✓</span><strong>${esc(t('Plans and payments'))}</strong><small><span class="tag">${esc(t('Not live yet'))}</span> ${esc(t('ApexRX takes no payments and has no paid plans yet.'))}</small></div></div>
<h3 class="ov-h">${esc(t('What needs your attention'))}</h3><div class="ov-actions">${att.join('')}</div>
${seesInsights()
  ? `<div class="ov-two"><section class="ov-panel ins"><div class="ov-ph"><div><span class="ov-eyebrow">${esc(t('STOCK HEALTH'))}</span><h3>${esc(t('Stock at {b}', { b: bn }))}</h3></div></div><div id="ins-health">${healthHtml()}</div></section>${expiryPanel()}</div>`
  : expiryPanel()}
${conversationsPanel()}
${seesInsights() ? premiumBanner('AI forecasting and insurance tools.') : ''}`;
  }

  /* Supplier overview: the depot's sales desk. Requests moving through to delivery. */
  function homeSupplier() {
    const n = waiting().length, prep = toConfirm(), low = lowItems(), soon = expiringSoon(), loc = curLoc();
    const convs = threads().length;
    const att = [
      actRow(n, n ? pl(n, '{n} request waiting for your offer', '{n} requests waiting for your offer') : t('No requests waiting'), t('Verified pharmacies asked for prices. Reply with an offer.'), navBtn('msg', 'Open requests')),
      actRow(prep.length, prep.length ? pl(prep.length, '{n} order to prepare', '{n} orders to prepare') : t('No orders to prepare'), t('Orders start when a pharmacy accepts your offer.'), navBtn('ord', 'View orders')),
      actRow(low.length, low.length ? pl(low.length, '{n} item is running low', '{n} items are running low') : t('Your catalogue looks healthy'), low.length ? low.slice(0, 4).map(label).join(', ') : t('Pharmacies can order everything you list.'), navBtn('stk', 'Update catalogue')),
      hasBatches()
        ? actRow(soon.length, soon.length ? pl(soon.length, '{n} batch expires within 90 days', '{n} batches expire within 90 days') : t('No batch expiring soon'), soon.length ? soon.slice(0, 3).map(b => `${label(b.item)} (${b.batch_number})`).join(', ') : t('Your batches have a comfortable shelf life.'), navBtn('stk', 'Check batches', true))
        : actRow(0, t('Expiry tracking is not connected yet'), t(BATCHES_OFF), `<button class="ghost" disabled>${esc(t('Not connected yet'))}</button>`)
    ];
    return `<div class="ov-top"><span class="ov-eyebrow">${esc(t('SUPPLIER OVERVIEW'))}</span><p>${esc(todayText())}</p></div>${hero()}
${seesInsights() ? `<section class="pipe ins" id="ins-pipe" aria-label="${esc(t('Order pipeline'))}">${pipeHtml()}</section>` : ''}
<div class="sup-grid"><div><h3 class="ov-h">${esc(t('What needs your attention'))}</h3><div class="ov-stack">${att.join('')}</div></div>
<div>${seesInsights() ? `<section class="ov-panel ins"><div class="ov-ph"><div><span class="ov-eyebrow">${esc(t('WHAT PHARMACIES WANT'))}</span><h3>${esc(t('Most requested medicines'))}</h3></div></div><div id="toprq">${topHtml()}</div></section>` : ''}${expiryPanel()}</div></div>
<div class="ov-cards two"><button class="ov-card" data-a="nav" data-v="set"><span class="ov-i">◎</span><strong>${esc(t('Your supplier profile'))}</strong><small>${esc(t('Supplier ID'))} ${esc(sid())}. ${esc((loc && loc.address) || t('Review your location and details'))} →</small></button>
<div class="ov-card" id="plan-card"><span class="ov-i">✓</span><strong>${esc(t('Plans and payments'))}</strong><small><span class="tag">${esc(t('Not live yet'))}</span> ${esc(t('ApexRX takes no payments and has no paid plans yet.'))}</small></div></div>
${conversationsPanel()}
${seesInsights() ? premiumBanner('Demand forecasting for your catalogue.') : ''}`;
  }
  const premiumBanner = text => `<section class="ov-premium"><div><span>${esc(t('MORE POSSIBILITIES'))}</span><h3>${esc(t('Think ahead.'))}<br>${esc(t('Grow with confidence.'))}</h3><p>${esc(t(text))}</p></div>${navBtn('prem', 'Explore Premium →')}</section>`;

  /* Overview charts (owners and managers only): figures computed by the API.
   * While new ones load, the last figures shown (or a loading line) stay. */
  const insFail = () => `<p class="empty">${esc(t('These figures could not be loaded. Try again later.'))}</p>`;
  const insLoading = () => `<p class="empty">${esc(t('Loading…'))}</p>`;
  function healthHtml() {
    const h = S.ins && (S.ins.location_id ?? null) === (S.loc ?? null) && S.ins.stock_health;
    if (!h) return S.insErr ? insFail() : insLoading();
    const counts = { in: h.in_stock, low: h.low_stock, out: h.out_of_stock }, total = h.total || 1;
    const seg = (k, l) => counts[k] ? `<span class="h-${k}" style="flex:${counts[k]}" title="${esc(t(l))}: ${counts[k]}"></span>` : '';
    const legend = (k, l) => `<li><i class="h-${k}"></i><span>${esc(t(l))}</span><b>${counts[k]}</b><small>${Math.round(counts[k] / total * 100)}%</small></li>`;
    return `<div class="health" aria-hidden="true">${seg('in', 'In stock')}${seg('low', 'Low stock')}${seg('out', 'Out of stock')}</div><ul class="health-l">${legend('in', 'In stock')}${legend('low', 'Low stock')}${legend('out', 'Out of stock')}</ul>`;
  }
  function pipeHtml() {
    const p = S.ins && S.ins.order_pipeline;
    const STAGES = [['submitted', 'New requests'], ['countered', 'Offers sent'], ['accepted,processing', 'To prepare'], ['dispatched', 'Dispatched'], ['delivered', 'Delivered']];
    const n = st => p ? st.split(',').reduce((v, k) => v + (p[k] || 0), 0) : '—';
    const value = S.ins ? money(S.ins.open_order_value, S.ins.currency) : S.insErr ? '—' : t('Loading…');
    return `${STAGES.map(([st, l], i) => `<button class="pipe-s" data-a="nav" data-v="${i < 2 ? 'msg' : 'ord'}"><b>${n(st)}</b><span>${esc(t(l))}</span></button>`).join('')}<div class="pipe-v"><small>${esc(t('Open order value'))}</small><b>${esc(value)}</b></div>`;
  }
  function topHtml() {
    if (!S.ins) return S.insErr ? insFail() : insLoading();
    const top = S.ins.top_requested || [], max = top.length ? top[0].quantity : 1;
    return top.map(x => `<div class="rq"><span>${esc(fullLabel(x))}</span><i><b style="width:${Math.round(x.quantity / max * 100)}%"></b></i><strong>${esc(pl(x.quantity, '{n} box', '{n} boxes'))}</strong></div>`).join('') || `<p class="empty">${esc(t('No requests yet. They appear here when a pharmacy asks you for prices.'))}</p>`;
  }
  // One reload at most per refusal, so a mismatch can never loop.
  const onceReload = () => { try { if (sessionStorage.getItem('apexrx_ins_reload')) return false; sessionStorage.setItem('apexrx_ins_reload', '1'); } catch (e) { return false; } location.reload(); return true; };
  async function loadInsights() {
    if (!seesInsights()) return;
    const loc = S.loc;
    try {
      const ins = await data.insights(loc);
      if (S.loc !== loc) return; // the branch changed meanwhile
      S.ins = ins; S.insErr = false;
      try { sessionStorage.removeItem('apexrx_ins_reload'); } catch (e) { /* storage unavailable */ }
    } catch (err) {
      if (err.status === 401) return; // signed out: the page goes to sign-in
      // Refused: the role changed since this page loaded (no longer owner or
      // manager). Reload, so the page shows what the current role allows.
      if ((err.status === 403 || err.status === 404) && onceReload()) return;
      S.insErr = true;
    }
    const paint = (id, html) => { const el = $(id); if (el) el.innerHTML = html; };
    paint('#ins-health', healthHtml()); paint('#ins-pipe', pipeHtml()); paint('#toprq', topHtml());
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
    rq() {
      const back = `<p style="margin:0 0 12px"><button class="linkish" data-a="rqback">← ${esc(t('All procurement requests'))}</button></p>`;
      if (S.rqOpen) return `${back}<div id="rqd"><p class="empty">${esc(t('Loading…'))}</p></div>`;
      if (S.rqNew && IS_PH) return `${back}<div id="rqn"></div>`;
      const intro = IS_PH
        ? 'Ask a supplier for prices on several medicines at once, including medicines they have not listed. The supplier answers with a quotation. Nothing is ordered until you accept it and create the order.'
        : 'Pharmacies ask you for prices here, including medicines you have not listed. Answer with a quotation. An order is created only when the pharmacy accepts it.';
      return `<div class="bar"><p class="muted" style="margin:0;flex:1;min-width:220px">${esc(t(intro))}</p>${IS_PH ? `<button class="solid" data-a="rqnew"${approved() ? '' : ' disabled'}>${esc(t('New request'))}</button>` : ''}</div>
${approved() ? '' : `<p class="lock">${esc(t('Procurement requests open once your organization is approved.'))}</p>`}
<div class="tbl"><table><thead><tr><th>${esc(t('Request'))}</th><th>${esc(t(IS_PH ? 'Supplier' : 'Pharmacy'))}</th><th>${esc(t('Medicines'))}</th><th>${esc(t('Quotation'))}</th><th>${esc(t('Status'))}</th><th></th></tr></thead><tbody id="rqrows">${reqRows()}</tbody></table></div>`;
    },
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
<div class="tbl"><table class="stock"><thead><tr><th>${esc(t('Item description'))}</th><th>${esc(t('Pack size'))}</th><th>${esc(t('Batch number'))}</th><th>${esc(t('Unit price'))}</th><th>${esc(t('Total price'))}</th><th>${esc(t('Expiry date'))}</th><th>${esc(t('Quantity'))}${IS_PH ? `<small>${esc(t('Recorded · held · reservable'))}</small>` : ''}</th><th>${esc(t('Low stock alert'))}</th><th>${esc(t('Listed'))}</th><th>${esc(t(IS_PH ? 'What patients see' : 'What pharmacies see'))}<small>${esc(t('Last confirmed'))}</small></th><th></th></tr></thead><tbody id="srows"></tbody></table></div>
<p class="note">${esc(t(IS_PH ? 'Patients see availability and price, never exact quantities. Expired batches are hidden from patients.' : 'Verified pharmacies see your price and quantity. Other suppliers never do. Expired batches are hidden.'))}</p>
${IS_PH ? `<p class="note">${esc(t('Quantity is the stock on your shelf as recorded. Held is taken by open reservation requests and confirmed reservations; unallocated is the rest. Reservable is what patients can still reserve after the minimum this branch keeps for walk-in customers (Reservations › Reservation settings). Collecting a reservation reduces the recorded stock.'))}</p>` : ''}`;
    },
    res() { return RES ? RES.view() : ''; },
    set() {
      const ids = licenceRows();
      const rows = [[t('Name'), ctx.org.name], ...(IS_PH ? [] : [[t('Supplier ID'), sid()]]), [t('Phone'), ctx.org.phone], [t('Email'), ctx.org.email], ...ids];
      const mgr = canManage(), owner = ctx.myRole === 'owner';
      const branches = [...(ctx.locations || [])].sort((a, b) => (b.is_active - a.is_active) || a.name.localeCompare(b.name));
      const place = l => [l.address, l.village, l.cell, l.sector].filter(Boolean).join(', ');
      return `<h2 style="margin-top:0">${esc(t(IS_PH ? 'Your pharmacy profile' : 'Your supplier profile'))}</h2><div class="panel"><dl class="kv">${rows.filter(r => r[1]).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl>${isPreview ? '' : `<p style="margin:12px 0 0"><a class="ghost" id="open-registration" href="${IS_PH ? SIGN_IN : ONBOARD}?lang=${lang}#review">${esc(t('Registration details and review →'))}</a></p>`}</div>
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
  // One thread per counterpart organization: its stored conversation (messages,
  // kept in ApexRX), plus the orders and procurement requests between the two.
  const PARTY_TYPE = IS_PH ? 'Supplier' : 'Pharmacy';
  const ts = d => d ? +new Date(d) : 0;
  const lastAt = c => Math.max(ts(c.conv && (c.conv.last_message_at || c.conv.created_at)), ...c.orders.map(o => ts(o.updated_at)), ...c.reqs.map(r => ts(r.updated_at)), 0);
  function threads() {
    const by = new Map();
    const add = (id, party) => { if (!by.has(id)) by.set(id, { party, orders: [], reqs: [], conv: null }); return by.get(id); };
    S.convs.forEach(c => { const x = c.counterpart; add(x.organization_id, { organization_id: x.organization_id, name: x.name, location_name: x.city, phone: x.phone }).conv = c; });
    S.orders.forEach(o => { const p = partyOf(o); add(p.organization_id, p).orders.push(o); });
    S.reqs.forEach(r => { const p = IS_PH ? r.supplier : r.pharmacy; add(p.organization_id, p).reqs.push(r); });
    if (S.newParty) add(S.newParty.organization_id, S.newParty);
    return [...by.values()].sort((a, b) => lastAt(b) - lastAt(a));
  }
  const unreadOf = c => c.conv ? c.conv.unread_count || 0 : 0;
  const clip = (x, n) => x.length > n ? x.slice(0, n - 1) + '…' : x;
  const threadPreview = c => {
    const m = c.conv && c.conv.last_message;
    if (m) return (m.mine ? t('You') + ': ' : '') + clip(m.body.replace(/\s+/g, ' '), 90);
    const r = c.reqs[0], o = c.orders[0];
    if (r && (!o || ts(r.updated_at) >= ts(o.updated_at))) return t('Request #{id}', { id: r.procurement_request_id }) + ' · ' + t(reqStatus(r.status)[1]);
    return o ? t('Order #{id}', { id: o.purchase_order_id }) + ' · ' + t((STATUS[o.status] || ['', o.status])[1]) : t('New conversation');
  };
  const waitingIn = c => c.orders.some(needsMe) || c.reqs.some(r => r.needs_my_action);
  const unreadMark = c => { const n = unreadOf(c); return n ? `<b class="unread" title="${esc(t('Unread messages'))}">${n}</b>` : waitingIn(c) ? `<i class="dot" title="${esc(t('Waiting for your answer'))}"></i>` : ''; };
  function ovList() {
    const el = $('#ovlist'); if (!el) return;
    const q = S.ovq.toLowerCase();
    el.innerHTML = threads().filter(c => !q || c.party.name.toLowerCase().includes(q)).slice(0, 6).map(c => `<div class="ov-row"><span class="av">${esc(initials(c.party.name))}</span><div><strong>${esc(c.party.name)}</strong> <span class="tag">${esc(t(PARTY_TYPE))}</span><small>${esc(threadPreview(c))}${lastAt(c) ? ' · ' + esc(ago(lastAt(c))) : ''}</small></div>${unreadOf(c) ? `<b class="unread">${unreadOf(c)}</b>` : ''}<button class="ghost" data-a="conv" data-c="${c.party.organization_id}">${esc(t('Open chat ↗'))}</button></div>`).join('')
      || `<p class="empty">${esc(t(S.ovq ? 'No conversation matches your search.' : IS_PH ? 'No conversations yet. Ask a supplier for a quote to start one.' : 'No requests yet. They appear here when a pharmacy asks you for prices.'))}</p>`;
  }
  function clist() {
    const el = $('#clist'); if (!el) return;
    const list = threads();
    if (!S.party && list.length) S.party = list[0].party.organization_id;
    el.innerHTML = `<button class="ghost cl-new" data-a="newconv"${approved() ? '' : ' disabled'}>${esc(t('New conversation'))}</button>` + (list.map(c => `<button class="citem" data-a="conv" data-c="${c.party.organization_id}"${c.party.organization_id === S.party ? ' aria-current="true"' : ''}><strong>${esc(c.party.name)}</strong><span class="ct"><i class="tag">${esc(t(PARTY_TYPE))}</i>${lastAt(c) ? ` <time>${esc(ago(lastAt(c)))}</time>` : ''}</span><span>${esc(threadPreview(c))}</span>${unreadMark(c)}</button>`).join('') || `<p class="empty">${esc(t('No conversations yet.'))}</p>`);
  }
  const itemTable = (o, confirmed) => `<table class="lt"><thead><tr><th>${esc(t('Item'))}</th><th>${esc(t('Boxes'))}</th><th>${esc(t('Per box'))}</th></tr></thead><tbody>${o.items.map(i => `<tr><td>${esc(fullLabel(i))}</td><td>${confirmed ? i.confirmed_quantity ?? i.requested_quantity : i.requested_quantity}</td><td>${money(confirmed ? i.confirmed_unit_price ?? i.requested_unit_price : i.requested_unit_price, o.currency)}</td></tr>`).join('')}</tbody></table>`;
  function orderBubbles(o) {
    const fromPh = IS_PH ? 'out' : 'in', fromSup = IS_PH ? 'in' : 'out';
    const parts = [`<div class="b ${fromPh}"><strong>${esc(t('Order list #{id}', { id: o.purchase_order_id }))}</strong>${o.procurement_request_id ? `<small class="ref">${esc(t('From procurement request #{id}', { id: o.procurement_request_id }))}</small>` : ''}${itemTable(o, false)}<div class="tot">${esc(t('Total'))} ${money(o.requested_total, o.currency)}</div>${o.notes ? `<p style="margin:6px 0">${esc(o.notes)}</p>` : ''}<span class="tm">${esc(fmtTime(o.submitted_at || o.created_at))}</span></div>`];
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
  const msgBubble = m => `<div class="b ${m.mine ? 'out' : 'in'}" data-m="${m.message_id}">${m.mine ? '' : `<span class="who-s">${esc(m.sender_name || '')}</span>`}<p class="tx">${esc(m.body)}</p><span class="tm">${m.mine && m.sender_name ? esc(m.sender_name) + ' · ' : ''}${esc(fmtTime(m.created_at))}</span></div>`;
  const requestCard = r => `<div class="b ${IS_PH ? 'out' : 'in'} rqc"><strong>${esc(t('Procurement request #{id}', { id: r.procurement_request_id }))}</strong><p style="margin:4px 0">${esc(pl(r.item_count, '{n} medicine', '{n} medicines'))} · ${reqTag(r.status)}</p><button class="ghost" data-a="rqopen" data-r="${r.procurement_request_id}">${esc(t('Open request'))}</button><span class="tm">${esc(fmtTime(r.created_at))}</span></div>`;
  async function thread() {
    const el = $('#thread'); if (!el) return;
    clist();
    const c = threads().find(x => x.party.organization_id === S.party);
    S.chat = null;
    if (!c) { el.innerHTML = `<p class="empty">${esc(t(IS_PH ? 'Start a conversation with a supplier, or pick one in Compare prices.' : 'Start a conversation with a pharmacy.'))}</p>`; return; }
    const p = c.party, can = approved();
    el.innerHTML = `<div class="th"><span class="av">${esc(initials(p.name))}</span><div><strong>${esc(p.name)}</strong> <span class="tag">${esc(t(PARTY_TYPE))}</span><small>${esc(p.location_name || '')}</small></div>${IS_PH && can ? `<button class="ghost" data-a="rqnew" data-s="${p.organization_id}">${esc(t('New request'))}</button>` : ''}${p.phone ? `<a class="ghost" href="tel:${esc(String(p.phone).replace(/[^\d+]/g, ''))}">${esc(t('Call'))}</a>` : ''}</div>
<div class="msgs" id="msgs" aria-live="polite"><p class="empty">${esc(t('Loading…'))}</p></div>
${S.listOpen ? `<div class="lb"><strong>${esc(t('Order list'))}</strong><p class="note" style="margin:2px 0">${esc(t('One item per line, with the number of boxes. Example: Paracetamol 500mg x 20'))}</p><textarea id="lt" rows="5" placeholder="Paracetamol 500mg x 20&#10;Amoxicillin 500mg x 10"></textarea><div id="lp"></div><div class="qa"><button class="solid" data-a="lsend">${esc(t('Send list'))}</button><button class="ghost" data-a="lclose">${esc(t('Cancel'))}</button></div></div>` : ''}
<form class="composer" id="sendf">${IS_PH && can ? `<button type="button" class="ic" data-a="lopen" title="${esc(t('Write an order list'))}" aria-label="${esc(t('Write an order list'))}">📋</button>` : ''}<textarea id="msg" rows="1" maxlength="4000" aria-label="${esc(t('Type a message'))}" placeholder="${esc(t(can ? 'Type a message' : 'Messages open once your organization is approved.'))}"${can ? '' : ' disabled'}></textarea><button class="solid"${can ? '' : ' disabled'}>${esc(t('Send'))}</button></form>`;
    const party = S.party;
    try {
      const [full, page] = await Promise.all([
        Promise.all(c.orders.slice(0, 8).map(o => data.order(o.purchase_order_id))),
        c.conv ? data.messages(c.conv.conversation_id) : Promise.resolve({ items: [] })
      ]);
      if (party !== S.party || !$('#msgs')) return;
      full.forEach(o => S.full.set(o.purchase_order_id, o));
      S.chat = { party, conv: c.conv, msgs: page.items, orders: full, reqs: c.reqs };
      paintMsgs(true);
      markSeen();
    } catch (err) {
      if ($('#msgs')) $('#msgs').innerHTML = `<p class="empty">${esc(errorText(err))}<br><button class="ghost" data-a="conv" data-c="${party}">${esc(t('Try again'))}</button></p>`;
    }
    if (S.listOpen && $('#lt')) $('#lt').focus();
  }
  // Messages, orders and requests in time order. Stays at the bottom if it was there.
  function paintMsgs(scroll) {
    const box = $('#msgs'); if (!box || !S.chat) return;
    const atEnd = box.scrollHeight - box.scrollTop - box.clientHeight < 60;
    const parts = [
      ...S.chat.orders.map(o => ({ at: ts(o.submitted_at || o.created_at), html: orderBubbles(o) })),
      ...S.chat.reqs.map(r => ({ at: ts(r.created_at), html: requestCard(r) })),
      ...S.chat.msgs.map(m => ({ at: ts(m.created_at), html: msgBubble(m) }))
    ].sort((a, b) => a.at - b.at);
    box.innerHTML = parts.map(x => x.html).join('') || `<p class="empty">${esc(t('No messages yet. Write the first one below.'))}</p>`;
    if (scroll || atEnd) box.scrollTop = box.scrollHeight;
  }
  const recount = () => { S.unread = S.convs.reduce((n, c) => n + (c.unread_count || 0), 0); badges(); };
  function upsertConv(conv) {
    const i = S.convs.findIndex(c => c.conversation_id === conv.conversation_id);
    if (i >= 0) S.convs[i] = { ...S.convs[i], ...conv }; else S.convs.unshift(conv);
    return S.convs.find(c => c.conversation_id === conv.conversation_id);
  }
  // The open conversation is read: tell the API, so unread counts and message
  // notifications clear for this user (other members keep their own).
  async function markSeen() {
    const ch = S.chat;
    if (!ch || !ch.conv || document.hidden || S.view !== 'msg') return;
    const last = ch.msgs[ch.msgs.length - 1];
    if (!last || (ch.conv.unread_count || 0) === 0) return;
    try {
      await data.markRead(ch.conv.conversation_id, last.message_id);
      ch.conv.unread_count = 0;
      S.notes.items.forEach(n => { if (n.kind === 'message' && n.conversation_id === ch.conv.conversation_id && !n.read) { n.read = true; S.notes.unread_count = Math.max(0, S.notes.unread_count - 1); } });
      recount(); clist(); paintBell();
    } catch (e) { /* tried again with the next message */ }
  }
  let sending = false;
  async function sendMessage() {
    const box = $('#msg'); if (!box || sending) return;
    const text = box.value.trim(); if (!text) return;
    const c = threads().find(y => y.party.organization_id === S.party); if (!c) return;
    const party = S.party, btn = $('#sendf .solid');
    sending = true; if (btn) btn.disabled = true;
    try {
      let conv = c.conv;
      if (!conv) { conv = upsertConv(await data.startConversation(party)); S.newParty = null; }
      const m = await data.sendMessage(conv.conversation_id, text);
      box.value = '';
      Object.assign(conv, { last_message: m, last_message_at: m.created_at });
      if (S.chat && S.chat.party === party) {
        S.chat.conv = conv;
        if (!S.chat.msgs.some(x => x.message_id === m.message_id)) S.chat.msgs.push(m);
        paintMsgs(true);
      }
      clist();
    } catch (err) { fail(err); } finally {
      sending = false;
      if (btn) btn.disabled = false;
      if ($('#msg')) $('#msg').focus();
    }
  }
  // New messages in the open conversation (every few seconds while it is open).
  async function pollChat() {
    const ch = S.chat;
    if (S.view !== 'msg' || !ch || !ch.conv || document.hidden) return;
    const last = ch.msgs.length ? ch.msgs[ch.msgs.length - 1].message_id : 0;
    try {
      const page = await data.messages(ch.conv.conversation_id, last ? { after_id: last } : {}, true);
      if (S.chat !== ch) return;
      const fresh = page.items.filter(m => !ch.msgs.some(x => x.message_id === m.message_id));
      if (!fresh.length) return;
      ch.msgs.push(...fresh);
      const end = fresh[fresh.length - 1];
      Object.assign(ch.conv, { last_message: end, last_message_at: end.created_at });
      ch.conv.unread_count = (ch.conv.unread_count || 0) + fresh.filter(m => !m.mine).length;
      paintMsgs(false); markSeen(); clist();
    } catch (e) { /* the next tick tries again */ }
  }
  // Start (or reopen) the conversation with an organization chosen in the directory.
  function openParty(p) {
    if (!threads().some(c => c.party.organization_id === p.organization_id)) S.newParty = p;
    S.party = p.organization_id; S.listOpen = false; go('msg');
  }
  function newConversation() {
    const d = $('#dlg');
    d.innerHTML = `<form method="dialog" id="dlgf"><h2>${esc(t('New conversation'))}</h2><label>${esc(t(IS_PH ? 'Search a supplier by name' : 'Search a pharmacy by name'))}<input id="nc-q" type="search" autocomplete="off"></label><div id="nc-l" class="picklist" aria-live="polite"></div><div class="dlg-a"><button type="button" class="ghost" data-a="dlgx">${esc(t('Cancel'))}</button></div></form>`;
    d.showModal(); searchContacts('', '#nc-l', 'ncpick');
  }
  let contactRun = 0;
  async function searchContacts(q, target, action) {
    const run = ++contactRun;
    try {
      const list = await data.contacts(q.trim());
      if (run !== contactRun || !$(target)) return;
      $(target).innerHTML = list.map(c => `<button type="button" class="pick-i" data-a="${action}" data-s="${c.organization_id}" data-n="${esc(c.name)}" data-city="${esc(c.city || '')}"><strong>${esc(c.name)}</strong><small>${esc(c.city || t(PARTY_TYPE))}</small></button>`).join('')
        || `<p class="note">${esc(t(IS_PH ? 'No approved supplier matches.' : 'No approved pharmacy matches.'))}</p>`;
    } catch (err) { if ($(target)) $(target).innerHTML = `<p class="note">${esc(errorText(err))}</p>`; }
  }
  const typedContacts = debounce(searchContacts, 250);

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

  /* ----------------------------------------------------------- procurement */
  // Statuses come from the API, which validates every change; the buttons shown
  // are the request's allowed_actions for this user.
  const REQ_STATUS = {
    submitted: ['low', IS_PH ? 'Sent' : 'New request'], viewed: ['low', IS_PH ? 'Seen by the supplier' : 'Seen'],
    quoted: [IS_PH ? 'low' : '', IS_PH ? 'Quotation received' : 'Quotation sent'], negotiation: ['low', 'Revision requested'],
    accepted: ['good', IS_PH ? 'Quotation accepted' : 'Accepted by the pharmacy'], rejected: ['out', 'Rejected'], cancelled: ['out', 'Cancelled'], converted: ['good', 'Order created']
  };
  const reqStatus = st => REQ_STATUS[st] || ['', st];
  const reqTag = st => `<span class="tag ${reqStatus(st)[0]}">${esc(t(reqStatus(st)[1]))}</span>`;
  const Q_STATUS = { draft: ['', 'Draft, not sent'], submitted: ['low', IS_PH ? 'Waiting for your answer' : 'Waiting for the pharmacy'], revision_requested: ['low', 'Revision requested'], accepted: ['good', 'Accepted'], rejected: ['out', 'Rejected'], superseded: ['', 'Replaced by a newer revision'] };
  const qTag = st => { const x = Q_STATUS[st] || ['', st]; return `<span class="tag ${x[0]}">${esc(t(x[1]))}</span>`; };
  const NEXT = IS_PH
    ? { submitted: 'Waiting for the supplier’s quotation.', viewed: 'Waiting for the supplier’s quotation.', quoted: 'Review the quotation: accept it, ask for a revision, or reject it.', negotiation: 'Waiting for the supplier’s revised quotation.', accepted: 'Quotation accepted. Create the supplier order when you are ready.', converted: 'The supplier order was created from this request.', rejected: 'This request is closed.', cancelled: 'This request is closed.' }
    : { submitted: 'Send a quotation for the medicines you can supply, or decline the request.', viewed: 'Send a quotation for the medicines you can supply, or decline the request.', quoted: 'Waiting for the pharmacy’s answer. You can still send an updated quotation.', negotiation: 'The pharmacy asked for a revised quotation.', accepted: 'The pharmacy accepted your quotation. The order appears in Orders once they create it.', converted: 'The order was created. Prepare and dispatch it from Orders.', rejected: 'This request is closed.', cancelled: 'This request is closed.' };
  const RQ_ACTIONS = { request_revision: ['Ask for a revision', 'ghost'], accept: ['Accept quotation', 'solid'], convert: ['Create supplier order', 'solid'], reject: ['Reject quotation', 'ghost'], cancel: ['Cancel request', 'ghost'], decline: ['Decline request', 'ghost'] };
  const specs = i => [i.strength, i.dosage_form, i.pack_size].filter(x => x && !i.medicine_name.toLowerCase().includes(String(x).toLowerCase())).join(' · ');
  const otherOf = r => IS_PH ? r.supplier : r.pharmacy;
  function reqRows() {
    if (!S.reqs.length) return `<tr><td colspan="6" class="empty">${esc(t(IS_PH ? 'No procurement requests yet. Create one to ask a supplier for prices.' : 'No procurement requests yet. They appear here when a pharmacy asks you for prices.'))}</td></tr>`;
    return S.reqs.map(r => `<tr data-request="${r.procurement_request_id}"><td><strong>#${r.procurement_request_id}</strong><small>${esc(fmtDate(r.created_at))}</small></td><td><strong>${esc(otherOf(r).name)}</strong>${IS_PH ? '' : `<small>${esc(r.pharmacy.location_name || '')}</small>`}</td><td>${esc(pl(r.item_count, '{n} medicine', '{n} medicines'))}</td><td>${r.latest_quotation_status ? `${money(r.latest_quotation_total, r.currency)}<small>${qTag(r.latest_quotation_status)}</small>` : '—'}</td><td>${reqTag(r.status)}${r.needs_my_action ? ` <i class="dot-i" title="${esc(t('Waiting for your answer'))}"></i>` : ''}</td><td class="act"><button class="${r.needs_my_action ? 'solid' : 'ghost'}" data-a="rqopen" data-r="${r.procurement_request_id}">${esc(t('Open'))}</button></td></tr>`).join('');
  }
  function upsertReq(r) {
    const i = S.reqs.findIndex(x => x.procurement_request_id === r.procurement_request_id);
    if (i >= 0) S.reqs[i] = r; else S.reqs.unshift(r);
    badges();
  }
  async function loadRequests() {
    try { S.reqs = await data.requests(); } catch (err) { if ($('#rqrows')) { $('#rqrows').innerHTML = `<tr><td colspan="6" class="empty">${esc(errorText(err))}</td></tr>`; } return; }
    if ($('#rqrows')) $('#rqrows').innerHTML = reqRows();
    badges();
  }
  async function loadRequest(id) {
    try {
      let r = await data.request(id);
      // The supplier opening a new request marks it seen for the pharmacy.
      if (!IS_PH && r.status === 'submitted') r = await data.viewedRequest(id);
      if (S.rqOpen !== id || !$('#rqd')) return;
      S.rq = r; upsertReq(r); paintRequest();
    } catch (err) { if ($('#rqd')) $('#rqd').innerHTML = `<div class="err"><p>${esc(errorText(err))}</p><button class="ghost" data-a="rqback">${esc(t('All procurement requests'))}</button></div>`; }
  }
  const lineName = i => `<strong>${esc(i.medicine_name)}</strong>${specs(i) ? `<small>${esc(specs(i))}</small>` : ''}${i.in_catalogue ? '' : `<small><span class="tag">${esc(t('Not in the catalogue'))}</span></small>`}`;
  function quoteBlock(r, q) {
    const items = new Map(r.items.map(i => [i.procurement_request_item_id, i]));
    const resp = { revision_requested: 'Revision asked', rejected: 'Reason', accepted: 'Note' }[q.status];
    return `<section class="panel qb"><div class="rq-t"><h3>${esc(t('Quotation, revision {n}', { n: q.revision }))}</h3>${qTag(q.status)}</div>
<p class="muted">${q.submitted_at ? esc(t('Sent {d}', { d: fmtTime(q.submitted_at) })) + (q.submitted_by_name ? ' · ' + esc(q.submitted_by_name) : '') : ''}${q.estimated_days != null ? ' · ' + esc(pl(q.estimated_days, 'Ready in about {n} day', 'Ready in about {n} days')) : ''}</p>
<div class="tbl"><table><thead><tr><th>${esc(t('Medicine'))}</th><th>${esc(t('Available'))}</th><th>${esc(t('Boxes'))}</th><th>${esc(t('Per box'))}</th><th>${esc(t('Line total'))}</th></tr></thead><tbody>${q.items.map(x => { const i = items.get(x.procurement_request_item_id) || { medicine_name: '?', in_catalogue: true }; return `<tr><td>${lineName(i)}${x.note ? `<small>${esc(x.note)}</small>` : ''}</td><td>${x.available ? `<span class="tag good">${esc(t('Yes'))}</span>` : `<span class="tag out">${esc(t('Not available'))}</span>`}</td><td>${x.available ? `${x.quantity}${i.quantity && x.quantity < i.quantity ? `<small>${esc(t('of {n} requested', { n: i.quantity }))}</small>` : ''}` : '—'}</td><td>${x.available ? money(x.unit_price, q.currency) : '—'}</td><td>${x.available ? money(x.line_total, q.currency) : '—'}</td></tr>`; }).join('')}</tbody></table></div>
<div class="tot" style="margin-top:10px">${esc(t('Total'))} ${money(q.total, q.currency)}</div>
${q.note ? `<p class="pre">${esc(q.note)}</p>` : ''}${resp && q.response_note ? `<p class="note">${esc(t(resp))}: ${esc(q.response_note)}${q.responded_by_name ? ' · ' + esc(q.responded_by_name) : ''}</p>` : ''}</section>`;
  }
  function quoteForm(r) {
    const draft = r.quotations.find(q => q.status === 'draft'), sent = r.quotations.filter(q => q.status !== 'draft');
    const base = draft || sent[sent.length - 1], prev = new Map(base ? base.items.map(x => [x.procurement_request_item_id, x]) : []);
    const rows = r.items.map(i => {
      const x = prev.get(i.procurement_request_item_id) || { available: true, quantity: i.quantity, unit_price: null, note: '' };
      const lbl = esc(i.medicine_name);
      return `<tr data-qi="${i.procurement_request_item_id}" data-max="${i.quantity}"><td>${lineName(i)}${i.notes ? `<small>${esc(i.notes)}</small>` : ''}</td><td>${i.quantity}</td><td><input type="checkbox" data-q="av"${x.available ? ' checked' : ''} aria-label="${esc(t('Can supply'))}: ${lbl}"></td><td><input class="qty" type="number" min="1" max="${i.quantity}" step="1" data-q="qty" value="${x.quantity ?? i.quantity}" aria-label="${esc(t('Boxes'))}: ${lbl}"></td><td><input class="qty" type="number" min="0" step="any" data-q="price" value="${x.unit_price != null ? Number(x.unit_price) : ''}" aria-label="${esc(t('Price per box'))}: ${lbl}"></td><td data-q="line">—</td><td><input data-q="note" maxlength="1000" value="${esc(x.note || '')}" aria-label="${esc(t('Note'))}: ${lbl}"></td></tr>`;
    }).join('');
    return `<form id="qf" class="panel" novalidate><h3 style="margin-top:0">${esc(t(sent.length ? 'Send a revised quotation' : 'Your quotation'))}</h3>
<p class="note" style="margin:0 0 10px">${esc(t('Answer every medicine: give the boxes you can supply and the price per box, or untick it if you cannot supply it.'))}${draft ? ' ' + esc(t('Draft saved {d}. The pharmacy cannot see it until you send it.', { d: fmtTime(draft.updated_at) })) : ''}</p>
<div class="tbl"><table class="qft"><thead><tr><th>${esc(t('Medicine'))}</th><th>${esc(t('Requested'))}</th><th>${esc(t('Can supply'))}</th><th>${esc(t('Boxes'))}</th><th>${esc(t('Price per box'))}</th><th>${esc(t('Line total'))}</th><th>${esc(t('Note'))}</th></tr></thead><tbody>${rows}</tbody></table></div>
<div class="rq-g" style="margin-top:12px"><label>${esc(t('Ready in (days, optional)'))}<input id="qf-days" type="number" min="0" max="365" step="1" value="${base && base.estimated_days != null ? base.estimated_days : ''}"></label><label>${esc(t('Note for the pharmacy (optional)'))}<textarea id="qf-note" rows="2" maxlength="5000">${esc((base && base.note) || '')}</textarea></label></div>
<div class="qa"><span class="tot" id="qf-total"></span><span style="flex:1"></span><button type="button" class="ghost" data-a="qsave">${esc(t('Save draft'))}</button><button type="button" class="solid" data-a="qsend">${esc(t('Send quotation'))}</button></div></form>`;
  }
  function qfTotals() {
    let total = 0;
    document.querySelectorAll('#qf tr[data-qi]').forEach(tr => {
      const av = tr.querySelector('[data-q=av]').checked, qty = tr.querySelector('[data-q=qty]'), price = tr.querySelector('[data-q=price]');
      qty.disabled = price.disabled = !av;
      const line = av && qty.value !== '' && price.value !== '' ? Number(qty.value) * Number(price.value) : null;
      if (line != null) total += line;
      tr.querySelector('[data-q=line]').textContent = !av ? t('Not available') : line != null ? money(line) : '—';
    });
    if ($('#qf-total')) $('#qf-total').textContent = t('Total') + ' ' + money(total);
  }
  function collectQuote() {
    const items = [];
    for (const tr of document.querySelectorAll('#qf tr[data-qi]')) {
      const av = tr.querySelector('[data-q=av]').checked, note = tr.querySelector('[data-q=note]').value.trim() || null;
      const id = +tr.dataset.qi, max = +tr.dataset.max, name = tr.querySelector('strong').textContent;
      if (!av) { items.push({ procurement_request_item_id: id, available: false, note }); continue; }
      const qty = Number(tr.querySelector('[data-q=qty]').value), raw = tr.querySelector('[data-q=price]').value, price = Number(raw);
      if (!Number.isInteger(qty) || qty < 1 || qty > max) { toast(t('{m}: enter between 1 and {n} boxes.', { m: name, n: max })); return null; }
      if (raw === '' || !(price >= 0)) { toast(t('{m}: enter the price per box, or untick it.', { m: name })); return null; }
      items.push({ procurement_request_item_id: id, available: true, quantity: qty, unit_price: Math.round(price * 100) / 100, note });
    }
    const days = $('#qf-days').value;
    if (days !== '' && !(Number.isInteger(+days) && +days >= 0 && +days <= 365)) { toast(t('Ready in: enter a number of days from 0 to 365.')); return null; }
    return { items, note: $('#qf-note').value.trim() || null, estimated_days: days === '' ? null : +days };
  }
  function paintRequest() {
    const r = S.rq, el = $('#rqd'); if (!r || !el) return;
    const other = otherOf(r), acts = r.allowed_actions || [];
    const sent = r.quotations.filter(q => q.status !== 'draft'), latest = sent[sent.length - 1];
    const btns = Object.keys(RQ_ACTIONS).filter(a => acts.includes(a)).map(a => `<button class="${RQ_ACTIONS[a][1]}" data-a="rqact" data-x="${a}">${esc(t(RQ_ACTIONS[a][0]))}</button>`).join('');
    el.innerHTML = `<div class="panel"><div class="rq-t"><h2>${esc(t('Procurement request #{id}', { id: r.procurement_request_id }))}</h2>${reqTag(r.status)}</div>
<dl class="kv"><dt>${esc(t(IS_PH ? 'Supplier' : 'Pharmacy'))}</dt><dd>${esc(other.name)}</dd><dt>${esc(t(IS_PH ? 'Branch' : 'Deliver to'))}</dt><dd>${esc(r.pharmacy.location_name || '—')}</dd><dt>${esc(t('Sent'))}</dt><dd>${esc(fmtTime(r.created_at))}${r.created_by_name ? ' · ' + esc(r.created_by_name) : ''}</dd>${r.needed_by ? `<dt>${esc(t('Needed by'))}</dt><dd>${esc(fmtDate(r.needed_by + 'T00:00:00'))}</dd>` : ''}${r.notes ? `<dt>${esc(t('Notes'))}</dt><dd class="pre">${esc(r.notes)}</dd>` : ''}${r.status_reason ? `<dt>${esc(t('Reason'))}</dt><dd>${esc(r.status_reason)}</dd>` : ''}</dl>
<p class="note">${esc(t(NEXT[r.status] || ''))}</p>
<div class="qa">${btns}<button class="ghost" data-a="conv" data-c="${other.organization_id}">${esc(t('Message {o}', { o: other.name }))}</button>${r.purchase_order_id ? `<button class="solid" data-a="rqorder" data-o="${r.purchase_order_id}">${esc(t('View order #{id}', { id: r.purchase_order_id }))}</button>` : ''}</div></div>
<h3>${esc(t('Requested medicines'))}</h3><div class="tbl" style="margin-bottom:16px"><table><thead><tr><th>#</th><th>${esc(t('Medicine'))}</th><th>${esc(t('Boxes'))}</th><th>${esc(t('Notes or specifications'))}</th></tr></thead><tbody>${r.items.map(i => `<tr><td>${i.line_no}</td><td>${lineName(i)}</td><td>${i.quantity}</td><td>${esc(i.notes || '—')}</td></tr>`).join('')}</tbody></table></div>
${acts.includes('quote') ? quoteForm(r) : ''}
${latest ? quoteBlock(r, latest) : IS_PH && !['rejected', 'cancelled'].includes(r.status) ? `<p class="empty">${esc(t('No quotation yet. You are notified when the supplier answers.'))}</p>` : ''}
${sent.length > 1 ? `<details class="hist"><summary>${esc(pl(sent.length - 1, '{n} earlier revision', '{n} earlier revisions'))}</summary>${sent.slice(0, -1).reverse().map(q => quoteBlock(r, q)).join('')}</details>` : ''}`;
    if ($('#qf')) qfTotals();
  }
  async function saveQuote(submit) {
    const body = collectQuote(); if (!body) return;
    const id = S.rq.procurement_request_id;
    if (submit && !await ask(t('Send quotation'), `<p>${esc(t('Send this quotation to {o}? Once sent it cannot be changed; you can send a revised one.', { o: S.rq.pharmacy.name }))}</p>`, t('Send quotation'))) return;
    try {
      S.rq = await data.quote(id, { ...body, submit });
      upsertReq(S.rq); paintRequest();
      toast(t(submit ? 'Quotation sent to {o}.' : 'Draft saved. The pharmacy cannot see it yet.', { o: S.rq.pharmacy.name }));
    } catch (err) { fail(err); }
  }
  async function requestAction(action) {
    const r = S.rq; if (!r) return;
    const sent = r.quotations.filter(q => q.status !== 'draft'), q = sent[sent.length - 1], id = r.procurement_request_id;
    const reason = async (title, help) => { const fd = await ask(t(title), `${help ? `<p>${esc(t(help))}</p>` : ''}<label>${esc(t('Reason'))}<textarea name="reason" rows="3" required maxlength="1000"></textarea></label>`, t(title)); return fd && { reason: fd.get('reason').trim() }; };
    let body = {};
    if (action === 'request_revision') {
      const fd = await ask(t('Ask for a revision'), `<p>${esc(t('Tell the supplier what to change, for example the price or the quantities. You can also discuss it in Messages.'))}</p><label>${esc(t('Note (optional)'))}<textarea name="note" rows="3" maxlength="1000"></textarea></label>`, t('Ask for a revision'));
      if (!fd) return; body = { note: fd.get('note').trim() || null };
    } else if (action === 'accept') {
      if (!await ask(t('Accept quotation'), `<p>${esc(t('Accept revision {n} from {o}, total {t}? No order is created yet: you create it in the next step.', { n: q.revision, o: r.supplier.name, t: money(q.total, q.currency) }))}</p>`, t('Accept quotation'))) return;
    } else if (action === 'reject') {
      body = await reason('Reject quotation', 'This closes the request. To change the terms instead, ask for a revision.'); if (!body) return;
    } else if (action === 'cancel') {
      body = await reason('Cancel request', null); if (!body) return;
    } else if (action === 'decline') {
      body = await reason('Decline request', 'Tell the pharmacy why you cannot supply this request.'); if (!body) return;
    } else if (action === 'convert') {
      const acc = r.quotations.find(x => x.status === 'accepted'), locs = activeLocations();
      const fd = await ask(t('Create supplier order'), `<p>${esc(t('Create the order to {o} at the accepted quantities and prices, total {t}? The supplier then prepares it from their orders.', { o: r.supplier.name, t: money(acc ? acc.total : 0, r.currency) }))}</p><label>${esc(t('Branch receiving the order'))}<select name="loc">${locs.map(l => `<option value="${l.location_id}"${l.location_id === r.pharmacy.location_id ? ' selected' : ''}>${esc(l.name)}</option>`).join('')}</select></label>`, t('Create supplier order'));
      if (!fd) return; body = { pharmacy_location_id: +fd.get('loc') || null };
    }
    try {
      const res = await data.requestAct(id, action, body, q && q.quotation_id);
      if (action === 'convert') {
        S.rq = res.request; S.orders = await data.orders();
        toast(t('Order #{id} created. Follow it in Supplier orders.', { id: res.purchase_order_id }));
      } else {
        S.rq = res;
        toast(t('Done. Request #{id} is updated.', { id }));
      }
      upsertReq(S.rq);
      if (S.view === 'rq' && S.rqOpen === id) paintRequest();
    } catch (err) { fail(err); if (S.rqOpen === id) loadRequest(id); }
  }

  /* New request (pharmacy): supplier, medicines (catalogue or described), review, send. */
  const newReq = supplier => ({ supplier, loc: S.loc, items: [], notes: '', need: '', review: false, sq: '', found: [] });
  function reqItemsHtml() {
    const f = S.rqNew;
    return f.items.map((it, n) => `<tr><td><strong>${esc(it.label)}</strong>${it.product_id ? '' : `<small><span class="tag">${esc(t('Not in the catalogue'))}</span></small>`}</td><td><input class="qty" type="number" min="1" step="1" value="${it.quantity}" data-rqi="${n}" data-k="quantity" aria-label="${esc(t('Boxes'))}: ${esc(it.label)}"></td><td><input maxlength="1000" value="${esc(it.notes)}" data-rqi="${n}" data-k="notes" placeholder="${esc(t('e.g. blister packs, a brand'))}" aria-label="${esc(t('Notes or specifications'))}: ${esc(it.label)}"></td><td class="act"><button type="button" class="ghost" data-a="rqrm" data-i="${n}">${esc(t('Remove'))}</button></td></tr>`).join('')
      || `<tr><td colspan="4" class="empty">${esc(t('No medicine added yet. Search the catalogue below, or describe a medicine that is not in it.'))}</td></tr>`;
  }
  function paintNewReq() {
    const f = S.rqNew, el = $('#rqn'); if (!f || !el) return;
    const loc = activeLocations().find(l => l.location_id === f.loc);
    if (f.review) {
      el.innerHTML = `<div class="panel"><h2>${esc(t('Review your request'))}</h2><dl class="kv"><dt>${esc(t('Supplier'))}</dt><dd>${esc(f.supplier.name)}</dd><dt>${esc(t('Branch'))}</dt><dd>${esc(loc ? loc.name : '—')}</dd>${f.need ? `<dt>${esc(t('Needed by'))}</dt><dd>${esc(fmtDate(f.need + 'T00:00:00'))}</dd>` : ''}${f.notes.trim() ? `<dt>${esc(t('Notes'))}</dt><dd class="pre">${esc(f.notes.trim())}</dd>` : ''}</dl>
<div class="tbl" style="margin:14px 0"><table><thead><tr><th>${esc(t('Medicine'))}</th><th>${esc(t('Boxes'))}</th><th>${esc(t('Notes or specifications'))}</th></tr></thead><tbody>${f.items.map(it => `<tr><td><strong>${esc(it.label)}</strong>${it.product_id ? '' : `<small><span class="tag">${esc(t('Not in the catalogue'))}</span></small>`}</td><td>${it.quantity}</td><td>${esc(it.notes || '—')}</td></tr>`).join('')}</tbody></table></div>
<p class="note">${esc(t('The supplier sees this request and answers with a quotation. Nothing is ordered until you accept a quotation and create the order.'))}</p>
<div class="qa"><button class="solid" data-a="rqsend">${esc(t('Send request'))}</button><button class="ghost" data-a="rqedit">${esc(t('Back to edit'))}</button></div></div>`;
      return;
    }
    el.innerHTML = `<div class="panel"><h2>${esc(t('New procurement request'))}</h2><p class="muted">${esc(t('List the medicines you need. The supplier does not have to list them, and they do not have to be in the ApexRX catalogue.'))}</p>
<div class="rq-g"><div><span class="lbl">${esc(t('Supplier'))}</span>${f.supplier ? `<div class="pick"><strong>${esc(f.supplier.name)}</strong> <button type="button" class="linkish" data-a="rqsupx">${esc(t('Change'))}</button></div>` : `<input id="rq-sup" type="search" autocomplete="off" value="${esc(f.sq)}" placeholder="${esc(t('Search a supplier by name'))}" aria-label="${esc(t('Search a supplier by name'))}"><div id="rq-supl" class="picklist"></div>`}</div>
<label>${esc(t('Branch'))}<select id="rq-loc">${activeLocations().map(l => `<option value="${l.location_id}"${l.location_id === f.loc ? ' selected' : ''}>${esc(l.name)}</option>`).join('')}</select></label></div>
<h3>${esc(t('Medicines'))}</h3><div class="tbl"><table><thead><tr><th>${esc(t('Medicine'))}</th><th>${esc(t('Boxes'))}</th><th>${esc(t('Notes or specifications'))}</th><th></th></tr></thead><tbody id="rq-items">${reqItemsHtml()}</tbody></table></div>
<div class="up" style="margin-top:12px"><label>${esc(t('Add from the ApexRX catalogue'))}<input id="rq-q" type="search" autocomplete="off" placeholder="${esc(t('Type to search, e.g. Amoxicillin'))}"></label><div id="rq-ql" class="picklist"></div>
<details id="rq-cd"><summary>${esc(t('Not in the catalogue? Describe the medicine'))}</summary><div class="rq-c"><label>${esc(t('Medicine name'))}<input id="rc-n" maxlength="255"></label><label>${esc(t('Strength'))}<input id="rc-s" maxlength="100" placeholder="500mg"></label><label>${esc(t('Dosage form'))}<input id="rc-f" maxlength="100" placeholder="${esc(t('tablet'))}"></label><label>${esc(t('Pack size'))}<input id="rc-p" maxlength="100" placeholder="B/20"></label><button type="button" class="ghost" data-a="rqaddc">${esc(t('Add this medicine'))}</button></div></details></div>
<div class="rq-g"><label>${esc(t('Notes for the supplier (optional)'))}<textarea id="rq-notes" rows="3" maxlength="5000">${esc(f.notes)}</textarea></label><label>${esc(t('Needed by (optional)'))}<input id="rq-need" type="date" value="${esc(f.need)}"></label></div>
<div class="qa"><button class="solid" data-a="rqreview">${esc(t('Review request'))}</button><button class="ghost" data-a="rqback">${esc(t('Cancel'))}</button></div></div>`;
    if (!f.supplier) searchContacts(f.sq, '#rq-supl', 'rqsup');
  }
  const paintReqItems = () => { if ($('#rq-items')) $('#rq-items').innerHTML = reqItemsHtml(); };
  let catRun = 0;
  const searchCatalogue = debounce(async q => {
    const el = $('#rq-ql'); if (!el) return;
    if (q.trim().length < 2) { el.innerHTML = ''; return; }
    const run = ++catRun;
    try {
      const items = await data.products(q.trim());
      if (run !== catRun || !$('#rq-ql')) return;
      S.rqNew.found = items;
      el.innerHTML = items.slice(0, 12).map(p => `<button type="button" class="pick-i" data-a="rqaddp" data-p="${p.product_id}"><strong>${esc(fullLabel(p))}</strong><small>${esc(p.drug_name || '')}</small></button>`).join('')
        || `<p class="note">${esc(t('Not in the catalogue. Describe it below instead.'))}</p>`;
    } catch (err) { el.innerHTML = `<p class="note">${esc(errorText(err))}</p>`; }
  }, 250);
  async function sendRequest(btn) {
    const f = S.rqNew; btn.disabled = true;
    try {
      const r = await data.createRequest({
        supplierId: f.supplier.organization_id, locationId: f.loc, notes: f.notes.trim(), neededBy: f.need || null,
        items: f.items.map(it => it.product_id
          ? { product_id: it.product_id, quantity: it.quantity, notes: it.notes.trim() || null }
          : { medicine_name: it.medicine_name, strength: it.strength || null, dosage_form: it.dosage_form || null, pack_size: it.pack_size || null, quantity: it.quantity, notes: it.notes.trim() || null })
      });
      toast(t('Request #{id} sent to {s}.', { id: r.procurement_request_id, s: f.supplier.name }));
      S.rqNew = null; upsertReq(r); S.rq = r; S.rqOpen = r.procurement_request_id;
      data.conversations().then(c => { S.convs = c.items; recount(); }).catch(() => {});
      go('rq');
    } catch (err) { fail(err); btn.disabled = false; }
  }

  /* ---------------------------------------------------------- notifications */
  const NOTE_TEXT = {
    request_submitted: '{o} sent you a procurement request.', request_cancelled: '{o} cancelled a procurement request.', request_declined: '{o} declined your procurement request.',
    quotation_submitted: '{o} sent you a quotation.', revision_requested: '{o} asked for a revised quotation.', quotation_accepted: '{o} accepted your quotation.',
    quotation_rejected: '{o} rejected your quotation.', order_created: '{o} created an order from your quotation.', message: 'New message from {o}.',
    reservation_requested: 'New reservation request {r}.', reservation_cancelled_patient: 'The patient cancelled reservation {r}.',
    reservation_request_lapsed: 'Reservation request {r} expired without an answer.',
    reservation_expired: 'Reservation {r} was not collected before its deadline. The stock it held is free again.'
  };
  function paintBell() {
    const b = $('#bell'); if (!b) return;
    const n = S.notes.unread_count || 0, c = $('#bell-n');
    c.hidden = !n; c.textContent = n > 99 ? '99+' : n;
    b.setAttribute('aria-label', t('Notifications') + (n ? ' (' + n + ')' : ''));
    b.title = t('Notifications');
    if (!$('#npanel').hidden) paintPanel();
  }
  function paintPanel() {
    const items = S.notes.items || [];
    $('#npanel').innerHTML = `<div class="np-h"><strong>${esc(t('Notifications'))}</strong>${S.notes.unread_count ? `<button class="linkish" data-a="nall">${esc(t('Mark all as read'))}</button>` : ''}</div>`
      + (items.map(x => `<button class="np-i${x.read ? '' : ' new'}" data-a="nopen" data-n="${x.notification_id}"><span>${esc(t(NOTE_TEXT[x.kind] || x.kind, { o: x.from_organization_name || '', r: x.reservation_reference || '' }))}</span><small>${esc(ago(x.created_at))}</small></button>`).join('')
      || `<p class="empty">${esc(t('No notifications yet.'))}</p>`);
  }
  function togglePanel(open) {
    const p = $('#npanel'), b = $('#bell');
    p.hidden = !open; b.setAttribute('aria-expanded', String(open));
    if (open) paintPanel();
  }

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
      return head + `<tr class="${best ? 'best' : ''}"><td><strong>${esc(fullLabel(o))}</strong></td><td><strong>${esc(o.supplier_name)}</strong><small>${esc([o.location_name, o.city].filter(Boolean).join(', '))}</small>${dir ? `<small><a href="${dir}" target="_blank" rel="noopener">${esc(t('Directions'))}</a></small>` : ''}</td><td>${o.distance_km != null ? o.distance_km.toFixed(1) + ' km' : '—'}</td><td><strong>${money(o.unit_price, o.currency)}</strong>${best ? ` <span class="tag good">${esc(t('Best price'))}</span>` : ''}</td><td>${esc(pl(o.quantity, '{n} box', '{n} boxes'))}</td><td class="act"><button class="ghost" data-a="chat" data-i="${o.offer_id}">${esc(t('Message'))}</button><button class="solid" data-a="quote" data-i="${o.offer_id}">${esc(t('Send order'))}</button></td></tr>`;
    }).join('') || `<tr><td colspan="6" class="empty">${esc(t(S.q ? 'No supplier lists this medicine. Try another name.' : 'No supplier offers yet.'))}</td></tr>`;
  }

  /* ----------------------------------------------------------------- stock */
  // Opening My stock re-reads the branch from the API: reservations confirmed or
  // collected since the dashboard loaded change the reserved and free figures.
  async function freshStock() {
    if (!S.loc || isPreview) return;
    const loc = S.loc;
    try {
      const next = await data.stock(loc);
      if (S.view !== 'stk' || S.loc !== loc) return;
      S.stock = next;
      const typing = document.activeElement && document.activeElement.closest && document.activeElement.closest('#srows');
      if (!typing && !$('#dlg').open) stockRows();
    } catch (err) { /* the cached list stays on screen */ }
  }
  // Reservation figures from the inventory API (never computed here).
  function reservedInfo(x) {
    if (!IS_PH || x.allocated_quantity == null) return '';
    const short = x.reservation_shortfall || 0;
    return `<small class="rsv">${esc(t('Held {a} · unallocated {f} · reservable {r}', { a: x.allocated_quantity, f: x.available_to_reserve, r: x.reservable_quantity ?? x.available_to_reserve }))}</small>`
      + (short ? `<small><span class="tag out">${esc(t('{s} short of open reservations', { s: short }))}</span></small>` : '');
  }
  // Before saving a recorded quantity below what open reservations hold.
  async function belowReserved(items) {
    const list = items.filter(i => IS_PH && i.x && i.qty < (i.x.allocated_quantity || 0));
    if (!list.length) return true;
    const form = await ask(t('Stock below what reservations hold'), `<p>${esc(t('Open reservation requests and confirmed reservations hold stock for patients. With these quantities the recorded stock is lower than what they hold:'))}</p>
<ul>${list.map(i => `<li><strong>${esc(label(i.x))}</strong>: ${esc(t('{q} recorded, {a} reserved ({s} short)', { q: i.qty, a: i.x.allocated_quantity, s: i.x.allocated_quantity - i.qty }))}</li>`).join('')}</ul>
<p>${esc(t('Save only if this is the real count. Nothing is cancelled automatically: the Reservations screen will show the shortfall, and an owner or manager decides what to do with the affected reservations.'))}</p>`, t('Save anyway'));
    return !!form;
  }
  // Save a quantity. The server refuses one below what reservations hold unless
  // the pharmacy confirmed the count (``confirmed``); if reservations arrived
  // since this list loaded, ask now with the server's figure, then retry.
  async function putQuantity(pid, qty, x, confirmed) {
    try {
      return await data.setQuantity(S.loc, pid, qty, confirmed);
    } catch (err) {
      const d = err && err.data;
      if (!IS_PH || !d || d.code !== 'below_reserved' || confirmed) throw err;
      if (!(await belowReserved([{ x: { ...(x || {}), allocated_quantity: d.held_quantity }, qty }]))) return null;
      return data.setQuantity(S.loc, pid, qty, true);
    }
  }
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
          : `<td><input class="qty" type="number" min="0" step="1" value="${x.quantity}" data-f="qty" data-p="${id}" aria-label="${esc(t('Quantity'))}: ${esc(label(x))}"${edit ? '' : ' disabled'}>${reservedInfo(x)}</td>`;
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
        const below = IS_PH && q < (x.allocated_quantity || 0);
        if (below && !(await belowReserved([{ x, qty: q }]))) { stockRows(); return; }
        const next = await putQuantity(pid, q, x, below);
        if (next === null) { stockRows(); return; }
        if (next && next.quantity != null) Object.assign(x, next); else x.quantity = q;
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
      else if ((await putQuantity(pid, qty, S.stock.find(s => s.product_id === pid), false)) === null) { btn.disabled = false; return; }
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
    el.innerHTML = `<div class="tbl" style="margin-top:12px"><table style="min-width:520px"><thead><tr><th>${esc(t('Row'))}</th><th>${esc(t('Item'))}</th><th>${esc(t('Batch number'))}</th><th>${esc(t('Check'))}</th></tr></thead><tbody>${S.imp.rows.slice(0, 50).map(r => `<tr><td>${r.n}</td><td>${esc(r.product ? fullLabel(r.product) : r.d)}</td><td>${esc(r.batch || '')}</td><td>${r.e ? `<span class="tag out">${esc(r.e)}</span>` : r.warn ? `<span class="tag low">${esc(r.warn)}</span>` : '<span class="tag good">OK</span>'}${!r.e && shortOf(r) ? ` <span class="tag out">${esc(t('Below reserved ({a})', { a: shortOf(r) }))}</span>` : ''}</td></tr>`).join('')}</tbody></table></div>
<div class="qa"><button class="solid" data-a="doimp"${ok.length ? '' : ' disabled'}>${esc(pl(ok.length, 'Import {n} valid row', 'Import {n} valid rows'))}</button><button class="ghost" data-a="noimp">${esc(t('Cancel'))}</button><span class="note" style="margin:0">${esc(t('{n} row(s) with errors will be skipped.', { n: S.imp.rows.length - ok.length }))}</span></div>`;
  }
  // Reserved quantity of an import row's product at this branch, when the row would go below it.
  function shortOf(r) {
    if (!IS_PH || !r.product) return 0;
    const x = S.stock.find(s => s.product_id === r.product.product_id);
    return x && r.qty < (x.allocated_quantity || 0) ? x.allocated_quantity : 0;
  }
  async function doImport(btn) {
    const rows = S.imp.rows.filter(row => !row.e && row.product);
    const ok = await belowReserved(rows.map(r => ({ x: S.stock.find(s => s.product_id === r.product.product_id), qty: r.qty })));
    if (!ok) return;
    btn.disabled = true;
    let done = 0;
    try {
      for (const r of S.imp.rows.filter(row => !row.e)) {
        if (hasBatches()) await data.setBatch(S.loc, r.product.product_id, { batch_number: r.batch, expiry_date: r.exp, quantity: r.qty });
        else if ((await putQuantity(r.product.product_id, r.qty, S.stock.find(s => s.product_id === r.product.product_id), true)) === null) continue;
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
  // onOpen(dialog): runs once the dialog is shown (e.g. to size a map inside it).
  function ask(title, bodyHtml, submit, onOpen) {
    const d = $('#dlg');
    d.innerHTML = `<form method="dialog" id="dlgf"><h2>${esc(title)}</h2>${bodyHtml}<div class="dlg-a"><button type="button" class="ghost" id="dlg-x">${esc(t('Cancel'))}</button><button class="solid">${esc(submit)}</button></div></form>`;
    return new Promise(res => {
      const form = $('#dlgf');
      const finish = v => { d.close(); res(v); };
      form.addEventListener('submit', e => { e.preventDefault(); finish(new FormData(form)); });
      $('#dlg-x').addEventListener('click', () => finish(null));
      d.addEventListener('cancel', () => res(null), { once: true });
      d.showModal();
      if (onOpen) onOpen(d);
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
    // Creates and submits a purchase order at the listed price; it is not a quotation
    // request (those are Procurement requests). Staff orders stay drafts (see draftText).
    const fd = await ask(t('Send order'), `<p class="muted" style="margin:0">${esc(fullLabel(offer))}<br>${esc(offer.supplier_name)} · ${money(offer.unit_price, offer.currency)}</p><p class="note" style="margin:0">${esc(t('This creates a purchase order at the price this supplier lists now. To ask a supplier for a quotation instead, use Procurement requests.'))}${canManage() ? '' : ' ' + esc(t('As staff, your order is saved as a draft. An owner or manager sends it from Supplier orders.'))}</p><label>${esc(t('Boxes'))}<input name="qty" type="number" min="1" step="1" value="20" required></label><label>${esc(t('Note (optional)'))}<textarea name="note" rows="2" maxlength="1000"></textarea></label>`, t(canManage() ? 'Send order' : 'Save draft'));
    if (!fd) return;
    try {
      const o = await data.sendOrder({ supplierId: offer.supplier_organization_id, supplierLocationId: offer.supplier_location_id, locationId: S.loc, items: [{ product_id: offer.product_id, quantity: +fd.get('qty') }], notes: fd.get('note').trim() });
      toast(o.draft ? draftText(o) : t('Order sent to {s}.', { s: offer.supplier_name }));
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
    let picker = null;
    const fd = await ask(t(l ? 'Edit {n}' : IS_PH ? 'Add a branch' : 'Add a depot', { n: l ? l.name : '' }),
      `<label>${esc(t('Name'))}<input name="name" required maxlength="200" value="${v('name')}"></label><label>${esc(t('Province'))}<input name="region" maxlength="100" value="${v('region')}"></label><label>${esc(t('District'))}<input name="city" maxlength="100" value="${v('city')}"></label><label>${esc(t('Sector'))}<input name="sector" maxlength="100" value="${v('sector')}"></label><label>${esc(t('Address'))}<input name="address" maxlength="500" value="${v('address')}"></label><label>${esc(t('Phone'))}<input name="phone" placeholder="+250 788 123 456" value="${v('phone')}"></label><label>${esc(t('WhatsApp'))}<input name="whatsapp_phone" placeholder="+250 788 123 456" value="${v('whatsapp_phone')}"></label><div class="loc-map-field"><strong>${esc(t('Map location'))}</strong><p class="muted">${esc(t(IS_PH ? 'Place the branch on the map: search for its address or click the map. You do not need to be there.' : 'Place the depot on the map: search for its address or click the map. You do not need to be there.'))}</p><div id="loc-picker"></div></div>`, t('Save'),
      () => {
        // The map location (js/location-picker.js); the server checks it again.
        if (!window.ApexLocationPicker) return;
        picker = window.ApexLocationPicker.mount($('#loc-picker'), {
          t, buttonClass: 'ghost',
          value: l && l.latitude != null ? { lat: Number(l.latitude), lng: Number(l.longitude) } : null
        });
        setTimeout(() => picker.refresh(), 50); // sized once the dialog is visible
      });
    if (!fd) return;
    const val = k => String(fd.get(k) || '').trim();
    const body = { name: val('name') };
    ['region', 'city', 'sector', 'address', 'phone', 'whatsapp_phone'].forEach(k => { if (val(k) || l) body[k] = val(k) || null; });
    const at = picker ? picker.get() : null;
    if (at) { body.latitude = at.lat; body.longitude = at.lng; } else if (l && picker) { body.latitude = null; body.longitude = null; }
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
    home() { ovList(); loadInsights(); },
    prem() { unmountForecast = DashForecast.mount($('#fc-root'), { role: ROLE, t, locale: LOCALE }); },
    cmp() { if (S.offers.length) renderOffers(); loadOffers(); },
    msg: thread,
    rq() { if (S.rqOpen) loadRequest(S.rqOpen); else if (S.rqNew) paintNewReq(); else loadRequests(); },
    ord: orderRows,
    stk() { stockRows(); renderImp(); freshStock(); },
    res() { if (RES) RES.after(); },
    set: loadTeam
  };

  /* --------------------------------------------------------- reservations */
  // Patient reservations: js/dashboard-reservations.js (pharmacies only).
  const RES = IS_PH && window.DashReservations ? window.DashReservations({
    data: () => data, ctx: () => ctx, isPreview: () => isPreview,
    t, esc, fmtTime, ask, toast, errorText, canManage,
    go: () => go('res'),
    currentLocation: () => S.loc,
    badge: n => { if (n != null) { S.resNew = n; badges(); } },
    // A dialog is open or the user is typing: background refreshes wait.
    busy: () => $('#dlg').open || ['INPUT', 'TEXTAREA', 'SELECT'].includes((document.activeElement || {}).tagName),
    // Opening or handling a reservation marks ITS notifications read (only those).
    markRead(reference) {
      const ids = (S.notes.items || []).filter(n => n.reservation_reference === reference && !n.read).map(n => n.notification_id);
      if (!ids.length) return;
      S.notes.items.forEach(n => { if (ids.includes(n.notification_id)) n.read = true; });
      S.notes.unread_count = Math.max(0, (S.notes.unread_count || 0) - ids.length);
      paintBell();
      data.readNotifications(ids).catch(() => {});
    },
    // A shortfall: open My stock at that branch, filtered to the medicine.
    async openStock(locationId, name) {
      if (activeLocations().some(l => l.location_id === locationId) && S.loc !== locationId) {
        S.loc = locationId; $('#br').value = String(locationId);
        try { S.stock = await data.stock(S.loc); } catch (err) { fail(err); }
      }
      S.sf = name || ''; go('stk');
    }
  }) : null;
  async function refreshReservations(quiet) {
    if (!RES) return;
    S.resNew = await RES.newRequests(quiet); badges();
  }

  /* ---------------------------------------------------------------- events */
  const ACT = {
    nav: d => go(d.v),
    compare: d => { S.q = d.m; S.cat = ''; go('cmp'); },
    cat: d => { S.cat = d.c; S.q = ''; go('cmp'); },
    conv: d => { S.party = +d.c; S.listOpen = false; go('msg'); },
    newconv: () => newConversation(),
    dlgx: () => $('#dlg').close(),
    ncpick: d => { $('#dlg').close(); openParty({ organization_id: +d.s, name: d.n, location_name: d.city || '' }); },
    rqopen: d => { S.rqOpen = +d.r; S.rqNew = null; S.rq = null; go('rq'); },
    rqback: () => { S.rqOpen = null; S.rqNew = null; go('rq'); },
    rqorder: () => go('ord'),
    rqact: d => requestAction(d.x),
    qsave: () => saveQuote(false),
    qsend: () => saveQuote(true),
    rqnew: d => {
      const party = d.s ? threads().find(c => c.party.organization_id === +d.s) : null;
      S.rqNew = newReq(party ? { organization_id: party.party.organization_id, name: party.party.name } : null);
      S.rqOpen = null; go('rq');
    },
    rqsup: d => { S.rqNew.supplier = { organization_id: +d.s, name: d.n }; paintNewReq(); },
    rqsupx: () => { S.rqNew.supplier = null; paintNewReq(); },
    rqaddp: d => {
      const f = S.rqNew, p = f.found.find(x => x.product_id === +d.p); if (!p) return;
      if (f.items.some(it => it.product_id === p.product_id)) { toast(t('This medicine is already on the request.')); return; }
      f.items.push({ product_id: p.product_id, label: fullLabel(p), quantity: 1, notes: '' });
      $('#rq-q').value = ''; $('#rq-ql').innerHTML = ''; paintReqItems();
    },
    rqaddc: () => {
      const v = id => $(id).value.trim(), name = v('#rc-n');
      if (!name) { toast(t('Enter the medicine name.')); $('#rc-n').focus(); return; }
      S.rqNew.items.push({ product_id: null, medicine_name: name, strength: v('#rc-s'), dosage_form: v('#rc-f'), pack_size: v('#rc-p'), label: [name, v('#rc-s'), v('#rc-f'), v('#rc-p')].filter(Boolean).join(' '), quantity: 1, notes: '' });
      ['#rc-n', '#rc-s', '#rc-f', '#rc-p'].forEach(id => { $(id).value = ''; });
      paintReqItems(); $('#rc-n').focus();
    },
    rqrm: d => { S.rqNew.items.splice(+d.i, 1); paintReqItems(); },
    rqreview: () => {
      const f = S.rqNew;
      if (!f.supplier) { toast(t('Choose the supplier.')); return; }
      if (!f.loc) { toast(t(IS_PH ? 'Add a branch first' : 'Add a depot first')); return; }
      if (!f.items.length) { toast(t('Add at least one medicine.')); return; }
      const bad = f.items.find(it => !(Number.isInteger(it.quantity) && it.quantity >= 1));
      if (bad) { toast(t('{m}: enter the number of boxes.', { m: bad.label })); return; }
      f.review = true; paintNewReq();
    },
    rqedit: () => { S.rqNew.review = false; paintNewReq(); },
    rqsend: (d, b) => sendRequest(b),
    bell: () => togglePanel($('#npanel').hidden),
    async nall() {
      try { await data.readNotifications(null); S.notes.items.forEach(n => { n.read = true; }); S.notes.unread_count = 0; paintBell(); } catch (err) { fail(err); }
    },
    async nopen(d) {
      const n = S.notes.items.find(x => x.notification_id === +d.n); if (!n) return;
      togglePanel(false);
      if (!n.read) { n.read = true; S.notes.unread_count = Math.max(0, S.notes.unread_count - 1); paintBell(); data.readNotifications([n.notification_id]).catch(() => {}); }
      if (n.kind === 'message') { S.party = n.from_organization_id; S.listOpen = false; go('msg'); }
      else if (n.procurement_request_id) { S.rqOpen = n.procurement_request_id; S.rqNew = null; S.rq = null; go('rq'); }
      else if (n.reservation_reference && RES) RES.openRef(n.reservation_reference);
    },
    chat: d => {
      const o = offerById(d.i); if (!o) return;
      S.party = o.supplier_organization_id;
      openParty({ organization_id: o.supplier_organization_id, name: o.supplier_name, location_name: o.location_name, phone: o.phone });
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
      const short = IS_PH ? S.stock.filter(x => x.reservation_shortfall > 0) : [];
      if (short.length && !(await ask(t('Confirm all as still correct'), `<p>${esc(t('These items have less recorded stock than their open reservations hold. Confirming says the counts are correct; the reservations stay commitments.'))}</p><ul>${short.map(x => `<li><strong>${esc(label(x))}</strong>: ${esc(t('{q} recorded, {a} reserved ({s} short)', { q: x.quantity, a: x.allocated_quantity, s: x.reservation_shortfall }))}</li>`).join('')}</ul>`, t('Confirm all')))) return;
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
    retry: () => start()
  };
  if (RES) Object.assign(ACT, RES.actions);
  document.addEventListener('click', e => {
    const b = e.target.closest('[data-a]');
    if (b && ACT[b.dataset.a] && ctx || (b && b.dataset.a === 'retry')) ACT[b.dataset.a](b.dataset, b);
  });
  $('#theme').addEventListener('click', () => ApexTheme.toggle());
  window.addEventListener('apexrx:theme', paintTheme);
  // Account menu (js/account-menu.js): initials, the account's own email, the
  // organization and role, and Sign out, which ends the session and opens the
  // landing page. The preview has no account: an "Exit preview" button instead.
  var acct = null; // var: paintAccount may run before this line (no TDZ)
  function paintAccount() {
    const host = $('#acct'); if (!host) return;
    if (isPreview) {
      if (!host.querySelector('#out')) host.innerHTML = '<button class="linkish" id="out" type="button"></button>';
      $('#out').textContent = t('Exit preview');
      $('#out').onclick = () => { location.href = ONBOARD + '?lang=' + lang; };
      return;
    }
    if (!ctx || !window.ApexAccountMenu) return;
    const opts = {
      name: ctx.user.name || ctx.user.email, email: ctx.user.email,
      detail: `${ctx.org.name} · ${t(ROLE_NAMES[ctx.myRole] || ctx.myRole)}`,
      verifyPhone: !!ctx.user.phone_verification_available && !ctx.user.phone_verified,
      labels: { menu: t('Account menu'), signOut: t('Sign out'), verifyPhone: t('Verify your mobile number') }
    };
    if (acct) acct.update(opts); else acct = ApexAccountMenu.mount(host, opts);
  }
  $('#lang').addEventListener('change', e => {
    lang = e.target.value;
    try { localStorage.setItem('apexrx_lang', lang); } catch (err) { /* ignore */ }
    const u = new URL(location.href); u.searchParams.set('lang', lang); location.href = u.toString();
  });
  document.addEventListener('submit', e => {
    if (e.target.id === 'addf') { e.preventDefault(); addItem(e.target); }
    if (e.target.id === 'sendf') { e.preventDefault(); sendMessage(); }
    if (e.target.id === 'invite-form') { e.preventDefault(); invite(e.target); }
  });
  // Enter sends, Shift+Enter starts a new line. Escape closes the notifications.
  document.addEventListener('keydown', e => {
    if (e.target.id === 'msg' && e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    if (e.key === 'Escape' && !$('#npanel').hidden) { togglePanel(false); $('#bell').focus(); }
  });
  document.addEventListener('click', e => { if (!$('#npanel').hidden && !e.target.closest('#npanel, #bell')) togglePanel(false); });
  const typedOffers = debounce(loadOffers, 300);
  document.addEventListener('input', e => {
    const x = e.target;
    if (x.id === 'q') { S.q = x.value; typedOffers(); }
    else if (x.id === 'sf') { S.sf = x.value; stockRows(); }
    else if (x.id === 'ovq') { S.ovq = x.value; ovList(); }
    else if (x.id === 'lt') previewList();
    else if (x.id === 'a-s') searchProducts(x.value);
    else if (x.id === 'nc-q') typedContacts(x.value, '#nc-l', 'ncpick');
    else if (x.id === 'rq-sup') { S.rqNew.sq = x.value; typedContacts(x.value, '#rq-supl', 'rqsup'); }
    else if (x.id === 'rq-q') searchCatalogue(x.value);
    else if (x.id === 'rq-notes') S.rqNew.notes = x.value;
    else if (x.dataset.rqi) { const it = S.rqNew.items[+x.dataset.rqi]; if (it) it[x.dataset.k] = x.dataset.k === 'quantity' ? parseInt(x.value, 10) : x.value; }
    else if (x.closest('#qf')) qfTotals();
  });
  document.addEventListener('change', async e => {
    const x = e.target;
    if (x.id === 'sort') { S.sort = x.value; loadOffers(); }
    else if (x.id === 'rq-loc') S.rqNew.loc = +x.value;
    else if (x.id === 'rq-need') S.rqNew.need = x.value;
    else if (x.dataset.q === 'av') qfTotals();
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
  // A deliberate sign-out (the account menu) ends on the landing page; inactivity,
  // another tab or an ended session go to sign-in with the reason.
  window.addEventListener('apexrx:signed-out', e => {
    const reason = e.detail && e.detail.reason;
    if (!reason || reason === 'signed_out') { location.replace('index.html'); return; }
    location.href = SIGN_IN + '?lang=' + lang + (reason && reason !== 'signed_out' ? '&signed_out=' + encodeURIComponent(reason) : '') + SIGN_IN_HASH;
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

  let livePolling = false;
  async function pollLive(now) {
    if ((document.hidden && !now) || !ctx || livePolling) return;
    livePolling = true;
    try {
      const [cv, nt, rq] = await Promise.allSettled([data.conversations(true), data.notifications(true), data.requests(true)]);
      if (cv.status === 'fulfilled') { S.convs = cv.value.items; S.unread = cv.value.unread_total; }
      if (nt.status === 'fulfilled') { S.notes = nt.value; paintBell(); }
      refreshReservations(true).catch(() => {});
      if (RES && S.view === 'res') RES.poll();
      let changed = false;
      if (rq.status === 'fulfilled') {
        const sig = l => l.map(r => r.procurement_request_id + r.status + r.updated_at).join();
        changed = sig(rq.value) !== sig(S.reqs); S.reqs = rq.value;
      }
      badges();
      const busy = $('#dlg').open || ['INPUT', 'TEXTAREA', 'SELECT'].includes((document.activeElement || {}).tagName);
      if (S.view === 'home') ovList();
      if (S.view === 'msg') {
        // Keep the open conversation's unread count as the chat poll set it.
        if (S.chat && S.chat.conv) { const c = S.convs.find(x => x.conversation_id === S.chat.conv.conversation_id); if (c) { c.unread_count = 0; S.chat.conv = c; } recount(); }
        clist();
        // The other side started the conversation while it was open here.
        if (S.chat && !S.chat.conv && !busy && S.convs.some(c => c.counterpart.organization_id === S.chat.party)) thread();
      }
      if (S.view === 'rq' && changed && !busy) {
        if (!S.rqOpen && !S.rqNew && $('#rqrows')) $('#rqrows').innerHTML = reqRows();
        // An open request reloads unless the supplier is writing a quotation.
        else if (S.rqOpen && !$('#qf')) loadRequest(S.rqOpen);
      }
    } finally { livePolling = false; }
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
      // Only an approved business uses the workspace; the server refuses the rest.
      // Pending, rejected or suspended: the application status page instead.
      if (!isPreview && c.org.status !== 'approved') { location.replace('business-status.html?lang=' + lang); return; }
      ctx = c;
      S.loc = (activeLocations()[0] || {}).location_id ?? null;
      const [stock, orders, drugs, convs, reqs, notes] = await Promise.allSettled([S.loc ? data.stock(S.loc) : [], data.orders(), IS_PH ? data.drugs() : [], data.conversations(), data.requests(), data.notifications()]);
      if (stock.status === 'fulfilled') S.stock = stock.value;
      if (orders.status === 'fulfilled') S.orders = orders.value;
      if (drugs.status === 'fulfilled') S.drugs = drugs.value;
      if (convs.status === 'fulfilled') { S.convs = convs.value.items; S.unread = convs.value.unread_total; }
      if (reqs.status === 'fulfilled') S.reqs = reqs.value;
      if (notes.status === 'fulfilled') S.notes = notes.value;
      await refreshReservations(true);
      chrome(); paintBell(); go('home');
      setInterval(poll, 45000);
      // Messages arrive by polling (no paid real-time service): the open
      // conversation every 5 seconds, the lists and notifications every 20.
      setInterval(pollChat, 5000);
      setInterval(pollLive, 20000);
      document.addEventListener('visibilitychange', () => { if (!document.hidden) { pollLive(true); pollChat(); } });
    } catch (err) {
      if (err.status === 401) return;
      $('#view').innerHTML = `<div class="err"><p>${esc(errorText(err))}</p><button class="solid" data-a="retry">${esc(t('Try again'))}</button></div>`;
    }
  }
  start();
})();
