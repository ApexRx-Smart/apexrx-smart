'use strict';
/* Patient reservations (reservations.html) on the ApexRX reservation API (js/api.js).
 *
 * Views, chosen from the address (only public ids are ever put there):
 *   ?location=<branch>&product=<product>   reserve one medicine at one branch
 *   ?ref=RX-XXXXXXXXXX                     one reservation: details, history, cancel
 *   (none)                                 updates + the patient's reservations (status, pages)
 * Signed out, the view is preceded by a sign-in / create-account panel (the same
 * /auth/login and /auth/register as the rest of the site) and then continues.
 *
 * The server is the authority for everything: eligibility, unit, price, limits,
 * deadlines and status. This page only shows what the API returns and explains its
 * error codes. It never shows stock quantities (the API does not send them to patients).
 *
 * Duplicate submissions: one client_request_id per reservation attempt, kept with the
 * draft in sessionStorage (this tab only) until the request succeeds, so a double
 * click, a retry after a network error or a sign-in in the middle never creates a
 * second reservation. The submit button is disabled while a request is in flight.
 */
(function () {
  const API = window.ApexAPI, SITE = window.ApexSite;
  if (!API || !SITE) return;

  const $ = id => document.getElementById(id);
  const t = SITE.t;
  const tf = (key, vars) => Object.keys(vars || {}).reduce((s, k) => s.split('{' + k + '}').join(vars[k]), t(key));
  const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const PAGE = 10;
  const DRAFT_KEY = 'apexrx_reservation_draft';
  const REFERENCE = /^RX-[A-Z0-9]{10}$/;
  const STATUSES = ['requested', 'confirmed', 'collected', 'declined', 'cancelled', 'expired'];
  // A symbol as well as the colour, so the status never depends on colour alone.
  const STATUS_ICON = { requested: '⏳', confirmed: '✓', collected: '✔', declined: '✕', cancelled: '⊘', expired: '⌛' };

  const S = {
    // #register (the header's "For Patients" / Get started) opens account creation.
    view: null, authMode: location.hash === '#register' ? 'create' : 'signin', me: null,
    reserve: null,        // {location, product, options, place, medicine}
    submitting: false, page: 0, status: '', run: 0,
    inflight: 0, listSig: null, detailRef: null, detailSig: null
  };
  // Background refresh of the list or the open reservation: every 45 s by default
  // (tests may set window.APEX_RES_POLL_MS), not while the tab is hidden, a request
  // is running, a field has focus or the cancel form is open.
  const POLL_MS = Math.max(2000, Number(window.APEX_RES_POLL_MS) || 45000);

  /* -------------------------------------------------------------- helpers */
  function dateText(iso) {
    if (!iso) return '';
    try { return new Intl.DateTimeFormat(SITE.locale(), { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(iso)); }
    catch (e) { return new Date(iso).toLocaleString(); }
  }
  function unitText(unit) {
    if (!unit || !unit.unit_label) return '';
    return unit.stock_unit === 'pack' && unit.pack_size ? `${unit.unit_label} (${unit.pack_size})` : unit.unit_label;
  }
  function badge(status) {
    const s = STATUSES.includes(status) ? status : 'requested';
    return `<span class="rs-badge ${s}"><span aria-hidden="true">${STATUS_ICON[s]}</span> ${esc(t('rs_st_' + s))}</span>`;
  }
  function langParam() { return 'lang=' + encodeURIComponent(SITE.lang()); }
  function href(params) {
    const p = new URLSearchParams(params || {});
    p.set('lang', SITE.lang());
    return 'reservations.html?' + p.toString();
  }
  function flash(text, kind) {
    const el = $('rs-flash');
    el.textContent = text || ''; el.hidden = !text;
    el.className = 'rs-flash' + (kind ? ' ' + kind : '');
  }
  function show(view) {
    S.view = view;
    ['rs-auth', 'rs-reserve', 'rs-success', 'rs-list', 'rs-detail'].forEach(id => { $(id).hidden = id !== view; });
  }
  function focusHeading(id) { const h = $(id); if (h) h.focus({ preventScroll: false }); }
  function uuid() {
    if (window.crypto && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
    const b = new Uint8Array(16); crypto.getRandomValues(b);
    b[6] = (b[6] & 0x0f) | 0x40; b[8] = (b[8] & 0x3f) | 0x80;
    const h = Array.from(b, x => x.toString(16).padStart(2, '0')).join('');
    return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
  }
  function readDraft() { try { return JSON.parse(sessionStorage.getItem(DRAFT_KEY) || 'null'); } catch (e) { return null; } }
  function saveDraft(d) { try { sessionStorage.setItem(DRAFT_KEY, JSON.stringify(d)); } catch (e) { /* storage off: still works, without retry memory */ } }
  function clearDraft() { try { sessionStorage.removeItem(DRAFT_KEY); } catch (e) { /* ignore */ } }
  function draftFor(location, product) {
    const d = readDraft();
    if (d && d.location === location && d.product === product && d.client_request_id) return d;
    const fresh = { location, product, client_request_id: uuid(), quantity: 1, phone: '', note: '' };
    saveDraft(fresh);
    return fresh;
  }

  /* --------------------------------------------------------------- routing */
  function route() {
    const p = new URLSearchParams(location.search);
    const ref = (p.get('ref') || '').trim().toUpperCase();
    const loc = Number(p.get('location')), prod = Number(p.get('product'));
    const wantsReserve = Number.isInteger(loc) && loc > 0 && Number.isInteger(prod) && prod > 0;
    paintAccount();
    if (!API.session.isSignedIn()) return showAuth(wantsReserve ? { location: loc, product: prod } : null);
    if (REFERENCE.test(ref)) return openDetail(ref);
    if (p.has('location') || p.has('product')) {
      if (wantsReserve) return openReserve(loc, prod);
      show('rs-reserve');
      $('rs-reserve-body').innerHTML = `<p class="rs-error" role="alert">${esc(t('rs_err_missing'))}</p>${findLink()}`;
      return;
    }
    S.status = STATUSES.includes(p.get('status')) ? p.get('status') : '';
    S.page = Math.max(0, (Number(p.get('page')) || 1) - 1);
    openList();
  }
  function go(params, replace) {
    const url = href(params);
    if (replace) history.replaceState(null, '', url); else history.pushState(null, '', url);
    flash('');
    route();
  }
  function findLink() { return `<p><a class="rs-btn" href="index.html?${langParam()}#hero-search">${esc(t('rs_find'))}</a></p>`; }

  /* ----------------------------------------------------- account and auth */
  function paintAccount() {
    const email = API.session.isSignedIn() && API.session.email();
    $('rs-account').hidden = !API.session.isSignedIn();
    $('rs-account-text').textContent = email ? tf('rs_signed_in', { email }) : '';
  }
  async function showAuth(reserving) {
    show('rs-auth');
    $('rs-auth-title').textContent = t(reserving ? 'rs_auth_title' : 'rs_auth_title_list');
    $('rs-auth-title').setAttribute('data-i18n', reserving ? 'rs_auth_title' : 'rs_auth_title_list');
    const ctx = $('rs-auth-context');
    ctx.hidden = true;
    setAuthMode(S.authMode);
    if (!reserving) return;
    // Say what is being reserved (public data only), so the patient knows where they are going back to.
    try {
      const place = await API.search.pharmacy(reserving.location);
      const med = (place.medicines || []).find(m => m.product_id === reserving.product);
      if (med && S.view === 'rs-auth') {
        ctx.textContent = tf('rs_auth_reserving', { medicine: SITE.medicineLabel(med), pharmacy: placeName(place) });
        ctx.hidden = false;
      }
    } catch (e) { /* the context line is optional */ }
  }
  function setAuthMode(mode) {
    S.authMode = mode;
    const create = mode === 'create';
    $('rs-tab-signin').setAttribute('aria-pressed', String(!create));
    $('rs-tab-create').setAttribute('aria-pressed', String(create));
    $('rs-name-field').hidden = !create;
    $('rs-password').setAttribute('autocomplete', create ? 'new-password' : 'current-password');
    $('rs-auth-submit').setAttribute('data-i18n', create ? 'rs_create_btn' : 'rs_signin_btn');
    $('rs-auth-submit').textContent = t(create ? 'rs_create_btn' : 'rs_signin_btn');
    $('rs-auth-error').textContent = '';
    $('rs-forgot-row').hidden = create;
  }
  async function submitAuth(e) {
    e.preventDefault();
    const create = S.authMode === 'create';
    const name = $('rs-name').value.trim(), email = $('rs-email').value.trim(), password = $('rs-password').value;
    const err = $('rs-auth-error');
    if (create && !name) { err.textContent = t('rs_err_name'); $('rs-name').focus(); return; }
    if (!email || !password) { err.textContent = t('rs_err_credentials'); (email ? $('rs-password') : $('rs-email')).focus(); return; }
    if (create && password.length < 8) { err.textContent = t('rs_err_password'); $('rs-password').focus(); return; }
    const btn = $('rs-auth-submit');
    btn.disabled = true; btn.textContent = t('rs_working'); err.textContent = '';
    try {
      if (create) {
        try { await API.auth.register({ name, email, password }); }
        catch (x) {
          if (x && x.status === 409) { err.textContent = t('rs_err_email_taken'); setAuthMode('signin'); return; }
          throw x;
        }
      }
      await API.auth.login(email, password);
      $('rs-password').value = '';
      S.me = null;
      route();
    } catch (x) {
      err.textContent = (x && x.message) || t('rs_err_generic');
    } finally {
      btn.disabled = false;
      btn.textContent = t(S.authMode === 'create' ? 'rs_create_btn' : 'rs_signin_btn');
    }
  }
  async function me() {
    if (!S.me) { try { S.me = await API.auth.me(); } catch (e) { S.me = null; } }
    return S.me;
  }

  /* ------------------------------------------------------------- reserve */
  function placeName(place) {
    return place.location_name && place.location_name !== place.pharmacy_name
      ? `${place.pharmacy_name} (${place.location_name})` : place.pharmacy_name;
  }
  async function openReserve(location, product, notice) {
    show('rs-reserve');
    const body = $('rs-reserve-body');
    if (!notice) body.innerHTML = `<p class="rs-muted">${esc(t('rs_loading'))}</p>`;
    const run = ++S.run;
    let options, place;
    try {
      [options, place] = await Promise.all([API.reservations.options(location, product), API.search.pharmacy(location)]);
    } catch (x) {
      if (run !== S.run) return;
      body.innerHTML = `<p class="rs-error" role="alert">${esc(x && x.status === 404 ? t('rs_err_not_found') : t('rs_err_generic'))}</p>${findLink()}`;
      return;
    }
    if (run !== S.run) return;
    const medicine = (place.medicines || []).find(m => m.product_id === product) || null;
    S.reserve = { location, product, options, place, medicine };
    if (!options.reservable || !medicine) {
      const reason = options.reason ? t('rs_reason_' + options.reason) : t('rs_err_not_found');
      body.innerHTML = `${medicine ? summary(medicine, place, options) : ''}
<p class="rs-error" role="alert"><strong>${esc(t('rs_cannot'))}</strong> ${esc(reason)}</p>${findLink()}`;
      focusHeading('rs-form-title');
      return;
    }
    const draft = draftFor(location, product);
    const account = await me();
    if (run !== S.run) return;
    const max = options.max_quantity;
    const unit = options.unit.unit_label;
    const qty = Math.min(Math.max(1, Number(draft.quantity) || 1), max);
    body.innerHTML = `${notice ? `<p class="rs-notice" role="alert">${esc(notice)}</p>` : ''}
${summary(medicine, place, options)}
<p class="rs-explain">${esc(t('rs_not_confirmed'))}</p>
<form class="rs-form" id="rs-reserve-form" novalidate>
  <div class="rs-field">
    <label for="rs-qty">${esc(tf('rs_quantity', { unit }))}</label>
    <input id="rs-qty" name="quantity" type="number" inputmode="numeric" min="1" max="${max}" step="1" value="${qty}" required aria-describedby="rs-qty-hint">
    <small class="rs-hint" id="rs-qty-hint">${esc(tf('rs_quantity_hint', { max }))}</small>
  </div>
  <div class="rs-field">
    <label for="rs-phone">${esc(t('rs_phone'))}</label>
    <input id="rs-phone" name="phone" type="tel" inputmode="tel" autocomplete="tel" maxlength="30" required aria-describedby="rs-phone-hint"
      value="${esc(draft.phone || (account && account.phone) || '')}">
    <small class="rs-hint" id="rs-phone-hint">${esc(t('rs_phone_hint'))}</small>
  </div>
  <div class="rs-field">
    <label for="rs-note">${esc(t('rs_note'))}</label>
    <textarea id="rs-note" name="note" rows="3" maxlength="500" aria-describedby="rs-note-hint">${esc(draft.note || '')}</textarea>
    <small class="rs-hint" id="rs-note-hint">${esc(t('rs_note_hint'))}</small>
  </div>
  <div class="rs-error" id="rs-reserve-error" role="alert"></div>
  <button type="submit" class="rs-btn primary" id="rs-submit">${esc(t('rs_submit'))}</button>
</form>`;
    const form = $('rs-reserve-form');
    form.addEventListener('submit', submitReserve);
    form.addEventListener('input', () => {
      const d = readDraft();
      if (d) { d.quantity = $('rs-qty').value; d.phone = $('rs-phone').value; d.note = $('rs-note').value; saveDraft(d); }
    });
    focusHeading('rs-form-title');
  }
  function summary(medicine, place, options) {
    const address = [place.address, place.city].filter(Boolean).join(', ');
    const status = options.availability_status ? SITE.stockClass(options.availability_status) : null;
    const unit = unitText(options.unit);
    return `<dl class="rs-facts">
  <dt>${esc(t('rs_medicine'))}</dt><dd><strong>${esc(SITE.medicineLabel(medicine))}</strong></dd>
  <dt>${esc(t('rs_pharmacy'))}</dt><dd>${esc(placeName(place))}${address ? `<br><span class="rs-muted">${esc(address)}</span>` : ''}</dd>
  ${unit ? `<dt>${esc(t('rs_unit'))}</dt><dd>${esc(unit)}</dd>` : ''}
  ${options.unit_price != null && options.unit.unit_label ? `<dt>${esc(tf('rs_price', { unit: options.unit.unit_label }))}</dt><dd>${esc(SITE.formatPrice(options.unit_price, options.currency))}<br><span class="rs-muted rs-small">${esc(t('rs_price_note'))}</span></dd>` : ''}
  ${status ? `<dt>${esc(t('rs_status_public'))}</dt><dd><span class="rstock ${status[0]}">${esc(t(status[1]))}</span> <span class="rs-muted">${esc(t('rs_status_note'))}</span></dd>` : ''}
</dl>`;
  }
  async function submitReserve(e) {
    e.preventDefault();
    if (S.submitting) return; // one request at a time
    const r = S.reserve, err = $('rs-reserve-error');
    const max = r.options.max_quantity;
    const raw = $('rs-qty').value.trim(), quantity = Number(raw);
    const phone = $('rs-phone').value.trim(), note = $('rs-note').value.trim();
    err.textContent = '';
    if (!/^\d+$/.test(raw) || quantity < 1 || quantity > max) { err.textContent = tf('rs_err_quantity', { max }); $('rs-qty').focus(); return; }
    if (!phone) { err.textContent = t('rs_err_phone'); $('rs-phone').focus(); return; }
    if (!/^\+?[0-9 ()\-./]{6,30}$/.test(phone)) { err.textContent = t('rs_err_phone_format'); $('rs-phone').focus(); return; }
    const draft = draftFor(r.location, r.product);
    Object.assign(draft, { quantity, phone, note }); saveDraft(draft);
    const btn = $('rs-submit');
    S.submitting = true; btn.disabled = true; btn.textContent = t('rs_sending');
    $('rs-reserve-form').setAttribute('aria-busy', 'true');
    try {
      const created = await API.reservations.submit({
        location_id: r.location, product_id: r.product, quantity,
        unit_version: r.options.unit.unit_version,
        client_request_id: draft.client_request_id,
        contact_phone: phone, note: note || null
      });
      clearDraft();
      showSuccess(created);
    } catch (x) {
      await reserveError(x, err);
    } finally {
      S.submitting = false;
      const b = $('rs-submit');
      if (b) { b.disabled = false; b.textContent = t('rs_submit'); }
      const f = $('rs-reserve-form'); if (f) f.removeAttribute('aria-busy');
    }
  }
  async function reserveError(x, err) {
    const data = (x && x.data) || {};
    const code = data.code;
    const r = S.reserve;
    if (x && x.status === 401) return; // signed out: the sign-in panel opens (apexrx:signed-out), the draft is kept
    if (!x || x.status === 0) { err.textContent = t('rs_err_network'); return; }
    if (code === 'unit_changed') { return openReserve(r.location, r.product, t('rs_err_unit_changed')); }
    if (code === 'not_reservable') { return openReserve(r.location, r.product); }
    if (code === 'open_reservation_exists' && data.reference) {
      clearDraft();
      err.innerHTML = `${esc(t('rs_err_open_exists'))} <a href="${esc(href({ ref: data.reference }))}">${esc(t('rs_view_existing'))}</a>`;
      return;
    }
    if (code === 'idempotency_key_reused') {
      clearDraft();
      err.innerHTML = `${esc(t('rs_err_reused'))} <a href="${esc(href())}">${esc(t('rs_title'))}</a>`;
      return;
    }
    const messages = {
      too_many_open_reservations: t('rs_err_limit'),
      quantity_above_limit: tf('rs_err_above_limit', { n: data.max_quantity || r.options.max_quantity }),
      own_pharmacy: t('rs_reason_own_pharmacy'),
      phone_required: t('rs_err_phone'),
      invalid_phone: t('rs_err_phone_format'),
      invalid_quantity: tf('rs_err_quantity', { max: r.options.max_quantity }),
      rate_limited: t('rs_err_rate'),
      insufficient_stock: t('rs_err_stock')
    };
    if (messages[code]) { err.textContent = messages[code]; return; }
    if (x.status === 429) { err.textContent = t('rs_err_rate'); return; }
    if (x.status === 404) { err.textContent = t('rs_err_not_found'); return; }
    err.textContent = x.status === 422 ? (x.message || t('rs_err_generic')) : t('rs_err_generic');
  }
  function showSuccess(res) {
    S.created = res;
    show('rs-success');
    history.replaceState(null, '', href({ ref: res.reference }));
    $('rs-success-body').innerHTML = `<p class="rs-reference" aria-label="${esc(t('rs_reference'))}">${esc(res.reference)}</p>
<p>${badge(res.status)}</p>
<p>${esc(tf('rs_success_lede', { ref: res.reference }))}</p>
<dl class="rs-facts">
  <dt>${esc(t('rs_medicine'))}</dt><dd>${esc(SITE.medicineLabel(res.medicine))}</dd>
  <dt>${esc(t('rs_pharmacy'))}</dt><dd>${esc(branchName(res.branch))}</dd>
  <dt>${esc(t('rs_requested_qty'))}</dt><dd>${esc(res.quantity)} × ${esc(unitText(res.unit))}</dd>
  <dt>${esc(res.unit.unit_label ? tf('rs_price', { unit: res.unit.unit_label }) : t('rs_unit_price'))}</dt><dd>${esc(SITE.formatPrice(res.unit_price, res.currency))}<br><span class="rs-muted rs-small">${esc(t('rs_price_note'))}</span></dd>
  <dt>${esc(t('rs_respond_by'))}</dt><dd>${esc(dateText(res.respond_by))}</dd>
</dl>
<p class="rs-explain">${esc(t('rs_not_confirmed'))}</p>
<p><a class="rs-btn primary" id="rs-success-view" href="${esc(href({ ref: res.reference }))}">${esc(t('rs_view'))}</a></p>`;
    focusHeading('rs-success-title');
  }
  function branchName(b) {
    return b.name && b.name !== b.pharmacy_name ? `${b.pharmacy_name} (${b.name})` : b.pharmacy_name;
  }

  /* ---------------------------------------------------------------- list */
  // quiet: a background refresh (no loading state; redrawn only if something changed;
  // a failure keeps what is shown).
  async function openList(quiet) {
    quiet = quiet === true;
    const list = $('rs-cards'), status = $('rs-list-status');
    if (!quiet) {
      show('rs-list');
      $('rs-status').value = S.status;
      list.setAttribute('aria-busy', 'true');
      list.innerHTML = '';
      status.textContent = t('rs_loading');
      $('rs-pager').hidden = true;
      S.listSig = null;
    }
    loadNotes(quiet);
    const run = quiet ? S.run : ++S.run;
    if (!quiet) S.inflight++;
    try {
      const params = { limit: PAGE, offset: S.page * PAGE };
      if (S.status) params.status = S.status;
      const page = await API.reservations.list(params, quiet ? { quiet: true } : undefined);
      if (run !== S.run || S.view !== 'rs-list') return;
      const sig = JSON.stringify(page);
      if (quiet && sig === S.listSig) return;
      S.listSig = sig;
      const pages = Math.max(1, Math.ceil(page.total / PAGE));
      if (!page.items.length) {
        status.textContent = '';
        list.innerHTML = `<li class="rs-empty">${esc(t(S.status ? 'rs_empty_filter' : 'rs_empty'))}</li>`;
      } else {
        status.textContent = '';
        list.innerHTML = page.items.map(card).join('');
      }
      $('rs-pager').hidden = page.total <= PAGE;
      $('rs-page').textContent = tf('rs_page', { a: S.page + 1, b: pages });
      $('rs-prev').disabled = S.page === 0;
      $('rs-next').disabled = S.page + 1 >= pages;
    } catch (x) {
      if (quiet || run !== S.run || (x && x.status === 401)) return;
      status.textContent = '';
      list.innerHTML = `<li class="rs-empty" role="alert">${esc(t('rs_load_error'))} <button type="button" class="rs-link" id="rs-retry">${esc(t('rs_retry'))}</button></li>`;
      $('rs-retry').addEventListener('click', () => openList());
    } finally {
      if (!quiet) S.inflight--;
      if (run === S.run) list.setAttribute('aria-busy', 'false');
    }
  }
  function card(r) {
    const dates = [[t('rs_submitted'), r.submitted_at]];
    if (r.status === 'requested') dates.push([t('rs_respond_by'), r.respond_by]);
    if (r.status === 'confirmed') dates.push([t('rs_collect_by'), r.collect_by]);
    if (r.closed_at) dates.push([t('rs_closed'), r.closed_at]);
    return `<li class="rs-card">
  <div class="rs-card-top"><a class="rs-ref" href="${esc(href({ ref: r.reference }))}" data-ref="${esc(r.reference)}">${esc(r.reference)}</a>${badge(r.status)}</div>
  <p class="rs-card-med"><strong>${esc(SITE.medicineLabel(r.medicine))}</strong> · ${esc(r.quantity)} × ${esc(unitText(r.unit))}</p>
  <p class="rs-muted">${esc(branchName(r.branch))}</p>
  <dl class="rs-dates">${dates.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(dateText(v))}</dd></div>`).join('')}</dl>
  <a class="rs-btn" href="${esc(href({ ref: r.reference }))}" data-ref="${esc(r.reference)}">${esc(t('rs_open_detail'))}<span class="sr-only"> ${esc(r.reference)}</span></a>
</li>`;
  }

  /* ------------------------------------------------------- notifications */
  async function loadNotes(quiet) {
    const box = $('rs-notes');
    try {
      const res = await API.notifications.personal({ limit: 20 }, quiet ? { quiet: true } : undefined);
      const items = res.items.filter(n => n.reservation_reference);
      const unread = items.filter(n => !n.read).length;
      $('rs-unread').hidden = !unread;
      $('rs-unread').textContent = tf('rs_unread', { n: unread });
      $('rs-mark-read').hidden = !unread;
      box.innerHTML = items.length ? items.map(n => {
        const key = 'rs_n_' + n.kind;
        const text = tf(t(key) !== key ? key : 'rs_n_other', { ref: n.reservation_reference });
        return `<li class="${n.read ? '' : 'unread'}">
  ${n.read ? '' : `<span class="rs-new">${esc(t('rs_new'))}</span>`}
  <a href="${esc(href({ ref: n.reservation_reference }))}" data-note="${n.notification_id}" data-ref="${esc(n.reservation_reference)}">${esc(text)}</a>
  <time class="rs-muted" datetime="${esc(n.created_at)}">${esc(dateText(n.created_at))}</time>
</li>`;
      }).join('') : `<li class="rs-muted">${esc(t('rs_updates_empty'))}</li>`;
    } catch (x) {
      box.innerHTML = '';
    }
  }

  /* -------------------------------------------------------------- detail */
  async function openDetail(reference, message, quiet) {
    quiet = quiet === true;
    const body = $('rs-detail-body');
    if (!quiet) {
      show('rs-detail');
      $('rs-back').href = href();
      if (!message) body.innerHTML = `<p class="rs-muted">${esc(t('rs_loading'))}</p>`;
      S.detailRef = reference; S.detailSig = null;
    }
    const run = quiet ? S.run : ++S.run;
    let r;
    if (!quiet) S.inflight++;
    try { r = await API.reservations.get(reference, quiet ? { quiet: true } : undefined); }
    catch (x) {
      if (quiet || run !== S.run || (x && x.status === 401)) return;
      body.innerHTML = `<p class="rs-error" role="alert">${esc(x && x.status === 404 ? t('rs_not_found') : t('rs_load_error'))}</p>`;
      return;
    } finally { if (!quiet) S.inflight--; }
    if (run !== S.run || S.view !== 'rs-detail' || S.detailRef !== reference) return;
    const sig = JSON.stringify(r);
    if (quiet && sig === S.detailSig) return;
    S.detailSig = sig;
    markRead(reference);
    if (message) flash(message, 'ok');
    const next = {
      requested: tf('rs_next_requested', { date: dateText(r.respond_by) }),
      confirmed: tf('rs_next_confirmed', { date: dateText(r.collect_by) }),
      collected: t('rs_next_collected'), declined: t('rs_next_declined'),
      cancelled: t('rs_next_cancelled'), expired: t('rs_next_expired')
    }[r.status];
    const b = r.branch;
    const address = [b.address, b.city].filter(Boolean).join(', ');
    const phone = b.phone ? `<a href="tel:${esc(String(b.phone).replace(/[^\d+]/g, ''))}">${esc(t('rs_call'))}: ${esc(b.phone)}</a>` : '';
    const reasons = [
      r.decline_reason ? [t('rs_reason_given'), r.decline_reason] : null,
      r.cancel_reason ? [t('rs_reason_given'), r.cancel_reason] : null,
      r.system_reason ? [t('rs_reason_given'), t('rs_sys_' + r.system_reason)] : null
    ].filter(Boolean);
    body.innerHTML = `<div class="rs-detail-head">
  <h2 id="rs-detail-title" tabindex="-1"><span class="rs-muted rs-small">${esc(t('rs_reference'))}</span> <span class="rs-reference">${esc(r.reference)}</span></h2>
  ${badge(r.status)}
</div>
<p class="rs-muted rs-small">${esc(t('rs_reference_hint'))}</p>
<div class="rs-next"><h3>${esc(t('rs_next_action'))}</h3><p>${esc(next)}</p></div>
<dl class="rs-facts">
  <dt>${esc(t('rs_medicine'))}</dt><dd><strong>${esc(SITE.medicineLabel(r.medicine))}</strong></dd>
  <dt>${esc(t('rs_pharmacy'))}</dt><dd>${esc(branchName(b))}${address ? `<br><span class="rs-muted">${esc(address)}</span>` : ''}${phone ? `<br>${phone}` : ''}</dd>
  <dt>${esc(t('rs_requested_qty'))}</dt><dd>${esc(r.quantity)} × ${esc(unitText(r.unit))}</dd>
  <dt>${esc(r.unit.unit_label ? tf('rs_price', { unit: r.unit.unit_label }) : t('rs_unit_price'))}</dt><dd>${esc(SITE.formatPrice(r.unit_price, r.currency))}<br><span class="rs-muted rs-small">${esc(t('rs_price_note'))}</span></dd>
  <dt>${esc(t('rs_contact'))}</dt><dd>${esc(r.contact_phone)}</dd>
  ${r.note ? `<dt>${esc(t('rs_note_label'))}</dt><dd>${esc(r.note)}</dd>` : ''}
  <dt>${esc(t('rs_submitted'))}</dt><dd>${esc(dateText(r.submitted_at))}</dd>
  ${r.status === 'requested' ? `<dt>${esc(t('rs_respond_by'))}</dt><dd>${esc(dateText(r.respond_by))}</dd>` : ''}
  ${r.confirmed_at ? `<dt>${esc(t('rs_confirmed_at'))}</dt><dd>${esc(dateText(r.confirmed_at))}</dd>` : ''}
  ${r.collect_by ? `<dt>${esc(t('rs_collect_by'))}</dt><dd>${esc(dateText(r.collect_by))}</dd>` : ''}
  ${r.closed_at ? `<dt>${esc(t('rs_closed'))}</dt><dd>${esc(dateText(r.closed_at))}</dd>` : ''}
  ${reasons.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}
</dl>
<h3>${esc(t('rs_history'))}</h3>
<ol class="rs-history">${r.history.map(historyItem).join('')}</ol>
${r.can_cancel ? cancelBlock() : ''}`;
    if (r.can_cancel) wireCancel(r.reference);
    if (!quiet) focusHeading('rs-detail-title');
  }
  // Opening a reservation marks its own updates read (never other ones).
  async function markRead(reference) {
    try {
      const res = await API.notifications.personal({ limit: 50 }, { quiet: true });
      const ids = res.items.filter(n => n.reservation_reference === reference && !n.read).map(n => n.notification_id);
      if (ids.length) await API.notifications.readPersonal(ids);
    } catch (e) { /* the list still shows them as new */ }
  }
  function historyItem(h) {
    let key = 'rs_h_' + h.to_status;
    if (h.to_status === 'cancelled') key = 'rs_h_cancelled_' + (h.by === 'system' ? 'system' : h.by === 'patient' ? 'patient' : 'pharmacy');
    const detail = h.system_reason ? t('rs_sys_' + h.system_reason) : h.reason || '';
    return `<li><time datetime="${esc(h.changed_at)}">${esc(dateText(h.changed_at))}</time> <span>${esc(t(key))}</span>${detail ? `<br><span class="rs-muted">${esc(detail)}</span>` : ''}</li>`;
  }
  function cancelBlock() {
    return `<div class="rs-cancel">
  <button type="button" class="rs-btn danger" id="rs-cancel-open">${esc(t('rs_cancel'))}</button>
  <form id="rs-cancel-form" class="rs-form" hidden novalidate>
    <p><strong>${esc(t('rs_cancel_confirm'))}</strong></p>
    <div class="rs-field">
      <label for="rs-cancel-reason">${esc(t('rs_cancel_reason'))}</label>
      <textarea id="rs-cancel-reason" rows="2" maxlength="500"></textarea>
    </div>
    <p class="rs-error" id="rs-cancel-error" role="alert"></p>
    <div class="rs-actions">
      <button type="submit" class="rs-btn danger" id="rs-cancel-yes">${esc(t('rs_cancel_yes'))}</button>
      <button type="button" class="rs-btn" id="rs-cancel-no">${esc(t('rs_cancel_no'))}</button>
    </div>
  </form>
</div>`;
  }
  function wireCancel(reference) {
    const open = $('rs-cancel-open'), form = $('rs-cancel-form');
    open.addEventListener('click', () => { open.hidden = true; form.hidden = false; $('rs-cancel-reason').focus(); });
    $('rs-cancel-no').addEventListener('click', () => { form.hidden = true; open.hidden = false; open.focus(); });
    let busy = false;
    form.addEventListener('submit', async e => {
      e.preventDefault();
      if (busy) return;
      busy = true;
      const yes = $('rs-cancel-yes');
      yes.disabled = true; yes.textContent = t('rs_working');
      try {
        await API.reservations.cancel(reference, $('rs-cancel-reason').value.trim() || null);
        openDetail(reference, t('rs_cancelled_ok'));
      } catch (x) {
        if (x && x.status === 401) return;
        const code = x && x.data && x.data.code;
        if (code === 'expired' || code === 'reservation_state_conflict') return openDetail(reference, t('rs_cancel_conflict'));
        $('rs-cancel-error').textContent = x && x.status === 0 ? t('rs_err_network') : t('rs_err_generic');
        busy = false; yes.disabled = false; yes.textContent = t('rs_cancel_yes');
      }
    });
  }

  /* --------------------------------------------------------------- events */
  // A link to #signin or #register on this page (the header's account chooser) switches the form.
  window.addEventListener('hashchange', () => {
    const mode = location.hash === '#register' ? 'create' : location.hash === '#signin' ? 'signin' : null;
    if (mode && !$('rs-auth').hidden) { setAuthMode(mode); $(mode === 'create' ? 'rs-name' : 'rs-email').focus(); }
    else if (mode) S.authMode = mode;
  });
  $('rs-tab-signin').addEventListener('click', () => setAuthMode('signin'));
  $('rs-tab-create').addEventListener('click', () => setAuthMode('create'));
  $('rs-auth-form').addEventListener('submit', submitAuth);
  $('rs-signout').addEventListener('click', () => { clearDraft(); API.auth.logout(); });
  $('rs-status').addEventListener('change', e => go(e.target.value ? { status: e.target.value } : {}));
  $('rs-prev').addEventListener('click', () => go(Object.assign(S.status ? { status: S.status } : {}, { page: S.page })));
  $('rs-next').addEventListener('click', () => go(Object.assign(S.status ? { status: S.status } : {}, { page: S.page + 2 })));
  $('rs-mark-read').addEventListener('click', async () => {
    try { await API.notifications.readPersonal(); } catch (e) { /* the list says what is unread */ }
    loadNotes();
  });
  // Links inside the page open views without reloading (and keep history).
  document.querySelector('.rs-body').addEventListener('click', e => {
    const a = e.target.closest('a[data-ref]');
    if (!a || e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    if (a.dataset.note) API.notifications.readPersonal([Number(a.dataset.note)]).catch(() => {});
    go({ ref: a.dataset.ref });
  });
  $('rs-back').addEventListener('click', e => { e.preventDefault(); go({}); });
  window.addEventListener('popstate', route);
  window.addEventListener('apexrx:signed-out', e => {
    S.me = null;
    route();
    if (e && e.detail && e.detail.reason !== 'signed_out' && readDraft()) $('rs-auth-error').textContent = t('rs_err_session');
  });
  window.addEventListener('apexrx:lang', () => {
    // Redraw dynamic text in the new language; form values are kept in the draft.
    history.replaceState(null, '', location.pathname + '?' + (() => { const p = new URLSearchParams(location.search); p.set('lang', SITE.lang()); return p; })());
    if (S.view === 'rs-success' && S.created) return showSuccess(S.created);
    if (S.view === 'rs-reserve' && S.reserve) return openReserve(S.reserve.location, S.reserve.product);
    route();
  });

  let ticking = false;
  async function tick() {
    if (ticking || document.hidden || S.inflight || !API.session.isSignedIn()) return;
    const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes((document.activeElement || {}).tagName);
    const cancelling = $('rs-cancel-form') && !$('rs-cancel-form').hidden;
    if (typing || cancelling) return;
    ticking = true;
    try {
      if (S.view === 'rs-list') await openList(true);
      else if (S.view === 'rs-detail' && S.detailRef) await openDetail(S.detailRef, null, true);
    } finally { ticking = false; }
  }
  setInterval(tick, POLL_MS);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) tick(); });

  route();
})();
