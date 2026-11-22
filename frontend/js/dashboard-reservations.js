'use strict';
/* Pharmacy dashboard: the Reservations workspace (patient reservations).
 *
 * Plugged into js/dashboard.js (window.DashReservations(env)); everything it does
 * goes through the reservation API (js/api.js -> js/dashboard-data.js):
 *   GET  /organizations/{id}/reservations                list, counts (total with limit=1),
 *                                                         server-side filters, pages, sort
 *   GET  /organizations/{id}/reservations/{reference}    detail: history, stock, collection,
 *                                                         and `actions` (what THIS member may do now)
 *   POST .../{reference}/confirm | decline | cancel | collect (with optional override)
 *   GET  /organizations/{id}/locations/{loc}/reservation-medicines  (stock breakdown per medicine)
 *   PATCH /organizations/{id}/locations/{loc} {reservation_min_stock}  (owners and managers)
 *   GET  /catalogue/products/{id}/reservation-settings   (read only: admins edit the catalogue)
 *
 * The page never decides an outcome: buttons come from the API's `actions`, every
 * change is a request, and the screen is reloaded from the API afterwards (also after
 * a refusal). Membership is organization-wide, so every branch is visible to every
 * active member; the API hides other organizations' reservations.
 */
(function (global) {
  const STATUSES = ['requested', 'confirmed', 'collected', 'declined', 'cancelled', 'expired'];
  const GROUP_LABEL = {
    requested: 'New requests', confirmed: 'Awaiting collection', collected: 'Collected',
    declined: 'Declined', cancelled: 'Cancelled', expired: 'Expired (reservation)'
  };
  const STATUS_LABEL = {
    requested: 'New request', confirmed: 'Confirmed: awaiting collection', collected: 'Collected',
    declined: 'Declined', cancelled: 'Cancelled', expired: 'Expired (reservation)'
  };
  const STATUS_TAG = { requested: 'low', confirmed: 'good', collected: 'in', declined: 'out', cancelled: 'out', expired: '' };
  const STATUS_ICON = { requested: '⏳', confirmed: '✓', collected: '✔', declined: '✕', cancelled: '⊘', expired: '⌛' };
  const REFERENCE = /^RX-[A-Z0-9]{10}$/;
  const PAGE = 20;

  function create(env) {
    const { t, esc, fmtTime, ask, toast, errorText } = env;
    const R = {
      mode: 'list',               // list | detail | setup
      status: 'requested', loc: '', from: '', to: '', ref: '', sort: 'deadline', page: 0,
      counts: null, list: null, listErr: null, open: null, detail: null, detailErr: null, busy: false,
      problem: null,              // a refused collection or confirmation, explained on the detail
      setupLoc: null, meds: null, run: 0
    };
    const data = () => env.data();
    const ctx = () => env.ctx();
    const live = () => !env.isPreview() && !!data().reservations;
    const tagFor = s => `<span class="tag ${STATUS_TAG[s] || ''}"><span aria-hidden="true">${STATUS_ICON[s] || ''}</span> ${esc(t(STATUS_LABEL[s] || s))}</span>`;
    const unitText = u => !u || !u.unit_label ? '—' : u.stock_unit === 'pack' && u.pack_size ? `${u.unit_label} (${u.pack_size})` : u.unit_label;
    const med = m => [m.product_name || m.drug_name, m.strength && !String(m.product_name || '').toLowerCase().includes(String(m.strength).toLowerCase()) ? m.strength : '', m.dosage_form]
      .filter(Boolean).join(' · ');
    const time = iso => iso ? fmtTime(iso) : '—';
    const branches = () => (ctx().locations || []);

    /* ------------------------------------------------------------ queries */
    function filters(extra) {
      const p = { sort: R.sort };
      if (R.loc) p.location_id = R.loc;
      if (R.from) p.submitted_from = new Date(R.from + 'T00:00:00').toISOString();
      if (R.to) { const d = new Date(R.to + 'T00:00:00'); d.setDate(d.getDate() + 1); p.submitted_to = d.toISOString(); }
      if (R.ref) p.reference = R.ref;
      return Object.assign(p, extra || {});
    }
    async function refreshCounts(quiet) {
      if (!live()) return null;
      const base = filters();
      delete base.sort;
      const totals = await Promise.all(STATUSES.map(s => data().reservations(Object.assign({}, base, { status: s, limit: 1 }), quiet)
        .then(r => r.total, () => null)));
      R.counts = Object.fromEntries(STATUSES.map((s, i) => [s, totals[i]]));
      return R.counts;
    }
    // Waiting for an answer, at every branch (the navigation badge and the overview).
    async function newRequests(quiet) {
      if (!live()) return 0;
      try { return (await data().reservations({ status: 'requested', limit: 1 }, quiet)).total; } catch (e) { return 0; }
    }

    /* --------------------------------------------------------------- view */
    function view() {
      if (!live()) {
        return `<div class="panel"><h2>${esc(t('Reservations'))}</h2><p class="muted" style="margin:0">${esc(t('Patient reservations appear here in your live workspace. The preview has no sample reservations.'))}</p></div>`;
      }
      const tabs = `<div class="chips rv-tabs" role="group" aria-label="${esc(t('Reservations'))}">
<button class="chip${R.mode !== 'setup' ? ' on' : ''}" data-a="rvmode" data-m="list" aria-pressed="${R.mode !== 'setup'}">${esc(t('Reservations'))}</button>
<button class="chip${R.mode === 'setup' ? ' on' : ''}" data-a="rvmode" data-m="setup" aria-pressed="${R.mode === 'setup'}">${esc(t('Reservation settings'))}</button></div>`;
      const readOnly = ctx().org.status !== 'approved'
        ? `<p class="lock">${esc(t('Your pharmacy is not approved right now: you can read reservations but not act on them.'))}</p>` : '';
      if (R.mode === 'setup') return tabs + readOnly + `<div id="rv-setup"><p class="empty">${esc(t('Loading…'))}</p></div>`;
      if (R.mode === 'detail') return tabs + readOnly + `<p style="margin:0 0 12px"><button class="linkish" data-a="rvback">← ${esc(t('Back to the list'))}</button></p><div id="rv-detail" aria-live="polite"><p class="empty">${esc(t('Loading…'))}</p></div>`;
      return tabs + readOnly + `<p class="muted rv-intro">${esc(t('A new request holds no stock. Confirming it commits your branch to hand over the full quantity within 24 hours.'))}</p>
<div class="chips rv-groups" id="rv-groups" role="group" aria-label="${esc(t('Status'))}">${groupChips()}</div>
<form class="rv-filters" id="rv-filters" novalidate>
  <label>${esc(t('Branch'))}<select id="rv-loc"><option value="">${esc(t('All branches'))}</option>${branches().map(l => `<option value="${l.location_id}"${String(l.location_id) === String(R.loc) ? ' selected' : ''}>${esc(l.name)}${l.is_active ? '' : ' (' + esc(t('closed')) + ')'}</option>`).join('')}</select></label>
  <label>${esc(t('Submitted from'))}<input id="rv-from" type="date" value="${esc(R.from)}"></label>
  <label>${esc(t('Submitted until'))}<input id="rv-to" type="date" value="${esc(R.to)}"></label>
  <label>${esc(t('Reference'))}<input id="rv-ref" type="search" value="${esc(R.ref)}" placeholder="RX-…" autocomplete="off" maxlength="13"></label>
  <label>${esc(t('Sort'))}<select id="rv-sort"><option value="deadline"${R.sort === 'deadline' ? ' selected' : ''}>${esc(t('Most urgent first'))}</option><option value="newest"${R.sort === 'newest' ? ' selected' : ''}>${esc(t('Newest first'))}</option></select></label>
  <div class="rv-fa"><button class="solid" type="submit">${esc(t('Apply'))}</button><button class="ghost" type="button" data-a="rvreset">${esc(t('Reset filters'))}</button></div>
  <p class="rv-ferr" id="rv-ferr" role="alert"></p>
</form>
<div id="rv-list" aria-live="polite"><p class="empty">${esc(t('Loading…'))}</p></div>`;
    }
    function groupChips() {
      const n = s => R.counts && R.counts[s] != null ? ` <span class="rv-n">${R.counts[s]}</span>` : '';
      return [['', t('All')]].concat(STATUSES.map(s => [s, t(GROUP_LABEL[s])]))
        .map(([s, l]) => `<button class="chip${R.status === s ? ' on' : ''}" data-a="rvgroup" data-s="${s}" aria-pressed="${R.status === s}">${esc(l)}${s ? n(s) : ''}</button>`).join('');
    }
    function after() {
      if (!live()) return;
      if (R.mode === 'detail') return loadDetail();
      if (R.mode === 'setup') return loadSetup();
      $('#rv-filters').addEventListener('submit', e => { e.preventDefault(); applyFilters(); });
      loadList();
    }
    const $ = s => document.querySelector(s);

    /* --------------------------------------------------------------- list */
    function applyFilters() {
      const ref = $('#rv-ref').value.trim().toUpperCase();
      if (ref && !REFERENCE.test(ref)) { $('#rv-ferr').textContent = t('A reference looks like RX- followed by 10 letters and digits.'); $('#rv-ref').focus(); return; }
      const from = $('#rv-from').value, to = $('#rv-to').value;
      if (from && to && from > to) { $('#rv-ferr').textContent = t('The start date is after the end date.'); return; }
      Object.assign(R, { loc: $('#rv-loc').value, from, to, ref, sort: $('#rv-sort').value, page: 0 });
      $('#rv-ferr').textContent = '';
      loadList();
    }
    async function loadList() {
      const box = $('#rv-list'); if (!box) return;
      const run = ++R.run;
      box.setAttribute('aria-busy', 'true');
      try {
        const params = filters({ limit: PAGE, offset: R.page * PAGE });
        if (R.status) params.status = R.status;
        const [page] = await Promise.all([data().reservations(params), refreshCounts(true)]);
        if (run !== R.run || !$('#rv-list')) return;
        R.list = page;
        const g = $('#rv-groups'); if (g) g.innerHTML = groupChips();
        env.badge(R.counts ? R.counts.requested : null);
        paintList();
      } catch (err) {
        if (run !== R.run || !$('#rv-list')) return;
        box.innerHTML = `<div class="err"><p>${esc(errorText(err))}</p><button class="solid" data-a="rvretry">${esc(t('Try again'))}</button></div>`;
      } finally {
        // Only the newest load ends the busy state (an older, superseded one must not).
        if (run === R.run && $('#rv-list')) $('#rv-list').removeAttribute('aria-busy');
      }
    }
    function deadline(r) {
      if (r.status === 'requested') return `<span class="rv-dl"><strong>${esc(t('Respond by'))}</strong> ${esc(time(r.respond_by))}</span>`;
      if (r.status === 'confirmed') return `<span class="rv-dl"><strong>${esc(t('Collect by'))}</strong> ${esc(time(r.collect_by))}</span>`;
      return r.closed_at ? `<span class="rv-dl">${esc(t('Closed'))} ${esc(time(r.closed_at))}</span>` : '';
    }
    function paintList() {
      const box = $('#rv-list'), page = R.list;
      if (!page.items.length) {
        const filtered = R.loc || R.from || R.to || R.ref;
        box.innerHTML = `<p class="empty">${esc(t(filtered ? 'No reservations match these filters.' : R.status ? 'No reservations with this status.' : 'No reservations yet. Patients reserve medicines that your branches have set up.'))}</p>`;
        return;
      }
      const pages = Math.max(1, Math.ceil(page.total / PAGE));
      box.innerHTML = `<ul class="rv-cards">${page.items.map(r => `<li class="rv-card">
  <div class="rv-top"><button class="linkish rv-ref" data-a="rvopen" data-r="${esc(r.reference)}">${esc(r.reference)}</button>${tagFor(r.status)}</div>
  <p class="rv-med"><strong>${esc(med(r.medicine))}</strong> · ${esc(r.quantity)} × ${esc(unitText(r.unit))}</p>
  <p class="muted rv-meta">${esc(r.patient.name)} · ${esc(r.location_name)} · ${esc(t('Requested'))} ${esc(time(r.submitted_at))}</p>
  <p class="rv-meta">${deadline(r)}</p>
  <button class="ghost rv-go" data-a="rvopen" data-r="${esc(r.reference)}">${esc(t('Open'))}<span class="sr"> ${esc(r.reference)}</span></button>
</li>`).join('')}</ul>
${page.total > PAGE ? `<nav class="rv-pager" aria-label="${esc(t('Pages'))}"><button class="ghost" data-a="rvpage" data-d="-1"${R.page === 0 ? ' disabled' : ''}>← ${esc(t('Previous'))}</button><span>${esc(t('Page {a} of {b}', { a: R.page + 1, b: pages }))}</span><button class="ghost" data-a="rvpage" data-d="1"${R.page + 1 >= pages ? ' disabled' : ''}>${esc(t('Next'))} →</button></nav>` : ''}`;
    }

    /* ------------------------------------------------------------- detail */
    async function loadDetail() {
      const box = $('#rv-detail'); if (!box) return;
      const run = ++R.run;
      try {
        const r = await data().reservation(R.open);
        if (run !== R.run || !$('#rv-detail')) return;
        R.detail = r;
        paintDetail();
        env.markRead(r.reference);
      } catch (err) {
        if (run !== R.run || !$('#rv-detail')) return;
        box.innerHTML = `<div class="err"><p>${esc(err && err.status === 404 ? t('Reservation not found.') : errorText(err))}</p></div>`;
      }
    }
    function kind(r) {
      if (r.status === 'requested') return ['rv-kind req', t('Patient request: no stock is committed yet. Confirm or decline it before {d}.', { d: time(r.respond_by) })];
      if (r.status === 'confirmed') return ['rv-kind com', t('Confirmed commitment: {n} × {u} is held for this patient until {d}. Hand over the full quantity or, if you cannot, an owner or manager cancels it with a reason.', { n: r.quantity, u: unitText(r.unit), d: time(r.collect_by) })];
      return ['rv-kind closed', t('Closed: nothing more can be done with this reservation.')];
    }
    function paintDetail() {
      const r = R.detail, st = r.stock, [kc, ktext] = kind(r);
      const phone = r.patient.phone
        ? `<a href="tel:${esc(String(r.patient.phone).replace(/[^\d+]/g, ''))}">${esc(r.patient.phone)}</a>`
        : `<span class="muted">${esc(t('Hidden: the reservation is closed.'))}</span>`;
      const reasons = [[t('Reason for declining'), r.decline_reason], [t('Reason for cancelling'), r.cancel_reason],
        [t('Closed by ApexRX'), r.system_reason ? t(SYSTEM_REASON[r.system_reason] || r.system_reason) : null]].filter(x => x[1]);
      const short = st.shortfall > 0 ? shortfallPanel(r) : '';
      const actions = r.actions || [];
      const btn = (a, cls, label) => actions.includes(a) ? `<button class="${cls}" data-a="rvact" data-x="${a}">${esc(t(label))}</button>` : '';
      $('#rv-detail').innerHTML = `<div class="panel">
<div class="rv-top"><h2 tabindex="-1" id="rv-title" class="rv-refbig">${esc(r.reference)}</h2>${tagFor(r.status)}</div>
<p class="${kc}">${esc(ktext)}</p>
${R.problem ? `<div class="banner bad rv-problem" role="alert"><span>${R.problem}</span></div>` : ''}
${short}
<dl class="kv">
  <dt>${esc(t('Patient'))}</dt><dd>${esc(r.patient.name)}</dd>
  <dt>${esc(t('Patient phone'))}</dt><dd>${phone}</dd>
  <dt>${esc(t('Medicine'))}</dt><dd><strong>${esc(med(r.medicine))}</strong></dd>
  <dt>${esc(t('Quantity'))}</dt><dd>${esc(r.quantity)} × ${esc(unitText(r.unit))}</dd>
  <dt>${esc(t('Branch'))}</dt><dd>${esc(r.location_name)}</dd>
  <dt>${esc(t('Price per unit'))}</dt><dd>${esc(Number(r.unit_price).toLocaleString('en-US'))} ${esc(r.currency)}<br><span class="muted">${esc(t('Your listed price when the patient sent the request. It is indicative: the patient pays at the pharmacy, and you confirm the final price with them.'))}</span></dd>
  ${r.note ? `<dt>${esc(t('Patient note'))}</dt><dd class="pre">${esc(r.note)}</dd>` : ''}
  <dt>${esc(t('Requested'))}</dt><dd>${esc(time(r.submitted_at))}</dd>
  ${r.status === 'requested' ? `<dt>${esc(t('Response deadline'))}</dt><dd><strong>${esc(time(r.respond_by))}</strong></dd>` : ''}
  ${r.confirmed_at ? `<dt>${esc(t('Confirmed'))}</dt><dd>${esc(time(r.confirmed_at))}</dd>` : ''}
  ${r.collect_by ? `<dt>${esc(t('Collection deadline'))}</dt><dd>${r.status === 'confirmed' ? `<strong>${esc(time(r.collect_by))}</strong>` : esc(time(r.collect_by))}</dd>` : ''}
  ${r.closed_at ? `<dt>${esc(t('Closed'))}</dt><dd>${esc(time(r.closed_at))}</dd>` : ''}
  ${reasons.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}
</dl>
${actions.length ? `<div class="rv-actions">${btn('confirm', 'solid', 'Confirm…')}${btn('collect', 'solid', 'Collect…')}${btn('decline', 'ghost', 'Decline…')}${btn('cancel', 'ghost danger', 'Cancel reservation…')}</div>
${actions.includes('override') ? `<p class="note rv-ovnote">${esc(t('Recorded stock too low but the shelf has it?'))} <button class="linkish" data-a="rvact" data-x="override">${esc(t('Physical-count override (exception)…'))}</button></p>` : ''}` : ''}
</div>
<div class="panel"><h3 style="margin-top:0">${esc(t('Stock of this medicine at {b}', { b: r.location_name }))}</h3>
<dl class="kv">
  <dt>${esc(t('Recorded stock'))}</dt><dd>${st.recorded_quantity == null ? esc(t('No stock record')) : esc(st.recorded_quantity)}</dd>
  <dt>${esc(t('Held by reservations'))}</dt><dd>${esc(st.allocated_quantity)}</dd>
  <dt>${esc(t('Unallocated'))}</dt><dd>${esc(st.available_to_reserve)}</dd>
  <dt>${esc(t('Kept back'))}</dt><dd>${esc(st.min_stock ?? 0)}</dd>
  <dt>${esc(t('Reservable now'))}</dt><dd>${esc(st.reservable_quantity ?? st.available_to_reserve)}</dd>
  <dt>${esc(t('Shortfall'))}</dt><dd>${st.shortfall ? `<strong class="rv-bad">${esc(st.shortfall)}</strong>` : '0'}</dd>
  <dt>${esc(t('Stock last confirmed'))}</dt><dd>${esc(time(st.last_updated))}</dd>
</dl></div>
${r.collection ? collectionPanel(r.collection) : ''}
<div class="panel"><h3 style="margin-top:0">${esc(t('History'))}</h3><ol class="rv-hist">${r.history.map(h => `<li><strong>${esc(time(h.changed_at))}</strong> ${esc(t(HISTORY[h.to_status] || h.to_status))} · ${esc(h.by === 'pharmacy' ? (h.by_name || t('Pharmacy')) : t(h.by === 'patient' ? 'Patient' : 'ApexRX (automatic)'))}${h.reason ? `<br><span class="muted">${esc(h.reason)}</span>` : ''}${h.system_reason ? `<br><span class="muted">${esc(t(SYSTEM_REASON[h.system_reason] || h.system_reason))}</span>` : ''}</li>`).join('')}</ol></div>`;
      const title = $('#rv-title'); if (title) title.focus({ preventScroll: true });
    }
    function shortfallPanel(r) {
      const st = r.stock;
      return `<div class="banner bad rv-short" role="alert"><div>
<strong>${esc(t('Stock shortfall: {m} at {b}', { m: med(r.medicine), b: r.location_name }))}</strong>
<p style="margin:6px 0 0">${esc(t('Confirmed reservations hold {a} but the recorded stock is {q} ({s} short). Confirmed reservations stay commitments: nothing is cancelled automatically.', { a: st.allocated_quantity, q: st.recorded_quantity ?? 0, s: st.shortfall }))}</p>
<p style="margin:6px 0 0">${esc(t('Count the shelf. If the record is wrong, correct it in My stock. If the pharmacy really cannot supply, an owner or manager cancels the affected reservations with a reason, and the patients are told.'))}</p>
<button class="ghost" data-a="rvstock" style="margin-top:8px">${esc(t('Correct the stock in My stock'))}</button></div></div>`;
    }
    function collectionPanel(c) {
      return `<div class="panel"><h3 style="margin-top:0">${esc(t('Collection'))}</h3><dl class="kv">
<dt>${esc(t('Collected'))}</dt><dd>${esc(time(c.collected_at))} · ${esc(c.collected_by_name || '')}</dd>
<dt>${esc(t('Quantity handed over'))}</dt><dd>${esc(c.quantity)}</dd>
<dt>${esc(t('Recorded stock before and after'))}</dt><dd>${esc(c.recorded_quantity_before)} → ${esc(c.quantity_after)}</dd>
${c.override ? `<dt>${esc(t('Physical-count override'))}</dt><dd>${esc(t('By {n}: counted {c}, the record showed {s}.', { n: c.override_by_name || '', c: c.verified_on_hand, s: c.recorded_quantity_seen }))}<br><span class="muted">${esc(c.override_reason || '')}</span></dd>` : ''}
</dl></div>`;
    }

    /* ------------------------------------------------------------ actions */
    const facts = (r, withStock, hideRef) => `<dl class="kv rv-dlg">
${hideRef ? '' : `<dt>${esc(t('Reference'))}</dt><dd>${esc(r.reference)}</dd>`}
<dt>${esc(t('Medicine'))}</dt><dd>${esc(med(r.medicine))}</dd>
<dt>${esc(t('Quantity'))}</dt><dd><strong>${esc(r.quantity)} × ${esc(unitText(r.unit))}</strong></dd>
<dt>${esc(t('Branch'))}</dt><dd>${esc(r.location_name)}</dd>
${withStock ? `<dt>${esc(t('Recorded stock'))}</dt><dd>${esc(r.stock.recorded_quantity ?? 0)}</dd>
<dt>${esc(t('Held by reservations'))}</dt><dd>${esc(r.stock.allocated_quantity)}</dd>
<dt>${esc(t('Unallocated'))}</dt><dd>${esc(r.stock.available_to_reserve)}</dd>
${r.stock.shortfall ? `<dt>${esc(t('Shortfall'))}</dt><dd>${esc(r.stock.shortfall)}</dd>` : ''}` : ''}
</dl>`;
    async function act(action) {
      const r = R.detail;
      const refField = `<label>${esc(t('Reference shown by the patient'))}<input name="reference" required autocomplete="off" autocapitalize="characters" spellcheck="false" maxlength="13" pattern="[Rr][Xx]-[A-Za-z0-9]{10}" placeholder="RX-…"></label>`;
      if (!r || R.busy) return;
      let body, title, submit, html;
      if (action === 'confirm') {
        // The request already holds its own quantity: it can be confirmed while the
        // recorded stock covers it after the OTHER open reservations.
        const covers = Math.max(0, (r.stock.recorded_quantity || 0) - (r.stock.allocated_quantity - r.quantity));
        const short = covers < r.quantity;
        html = facts(r, true) + `<p><strong>${esc(t('Respond by'))}:</strong> ${esc(time(r.respond_by))}</p>
<p>${esc(t('Confirming commits this branch to hand over the full {n} × {u} to the patient. The quantity is held for 24 hours and is not available to other patients.', { n: r.quantity, u: unitText(r.unit) }))}</p>
${short ? `<p class="lock" role="alert">${esc(t('After the other open reservations, the recorded stock covers only {a}: the confirmation will be refused unless the recorded stock is corrected first.', { a: covers }))}</p>` : ''}
<label class="rv-check"><input type="checkbox" name="sure" required> ${esc(t('I have checked that we can supply the full quantity.'))}</label>`;
        title = t('Confirm reservation {r}', { r: r.reference }); submit = t('Confirm reservation');
      } else if (action === 'decline') {
        html = facts(r) + `<p>${esc(t('Declining closes the request. The patient is told, with your reason, and can reserve elsewhere.'))}</p>
<label>${esc(t('Reason (the patient sees it)'))}<textarea name="reason" rows="3" maxlength="500" required></textarea></label>`;
        title = t('Decline reservation {r}', { r: r.reference }); submit = t('Decline reservation');
      } else if (action === 'cancel') {
        html = facts(r) + `<p>${esc(t('Cancelling breaks a commitment made to the patient: the held quantity is released and the reservation closes. The patient is told, with your reason. Use it only when the pharmacy cannot honour the reservation.'))}</p>
<label>${esc(t('Reason (the patient sees it)'))}<textarea name="reason" rows="3" maxlength="500" required></textarea></label>
<label class="rv-check"><input type="checkbox" name="sure" required> ${esc(t('I understand that this cancels a confirmed reservation.'))}</label>`;
        title = t('Cancel reservation {r}', { r: r.reference }); submit = t('Cancel reservation');
      } else if (action === 'collect') {
        html = facts(r, false, true) + `<p>${esc(t('Ask the patient for their reservation reference and type it here. Collection is refused if it does not match this reservation.'))}</p>${refField}
<p><strong>${esc(t('Hand over the full {n} × {u}. Partial collection is not possible.', { n: r.quantity, u: unitText(r.unit) }))}</strong> ${esc(t('The recorded stock is reduced by {n} in the same step.', { n: r.quantity }))}</p>
<label class="rv-check"><input type="checkbox" name="sure" required> ${esc(t('I am handing over the full quantity to the patient now.'))}</label>`;
        title = t('Collect this reservation');  // no reference: staff type the one the patient shows submit = t('Record collection');
      } else if (action === 'override') {
        const seen = r.stock.recorded_quantity ?? 0;
        html = `<p class="lock">${esc(t('Exception: use this only when the recorded stock is too low but the medicine is physically on the shelf.'))}</p>
${facts(r, false, true)}
<p>${esc(t('Ask the patient for their reservation reference and type it here. Collection is refused if it does not match this reservation.'))}</p>${refField}
<p>${esc(t('Count the stock on the shelf now. Your count replaces the recorded stock, then the full {n} × {u} is handed over. Your name, count and reason are recorded.', { n: r.quantity, u: unitText(r.unit) }))}</p>
<p><strong>${esc(t('Recorded stock you are correcting'))}:</strong> ${esc(seen)}. ${esc(t('If the record changes before you submit, the override is refused and you must count again.'))}</p>
<label>${esc(t('Physical count on hand'))}<input name="count" type="number" inputmode="numeric" min="${r.quantity}" step="1" required></label>
<label>${esc(t('Reason (10 to 500 characters)'))}<textarea name="reason" rows="3" minlength="10" maxlength="500" required></textarea></label>
<label class="rv-check"><input type="checkbox" name="sure" required> ${esc(t('I physically counted this stock myself.'))}</label>
<input type="hidden" name="seen" value="${esc(seen)}">`;
        title = t('Physical-count override and collection'); submit = t('Override and record collection');
      } else return;
      const form = await ask(title, html, submit);
      if (!form) return;
      if (action === 'decline' || action === 'cancel') body = { reason: String(form.get('reason') || '').trim() };
      const typed = String(form.get('reference') || '').trim().toUpperCase();
      if (action === 'override') {
        body = { reference: typed, override: { verified_on_hand: Number(form.get('count')), recorded_quantity_seen: Number(form.get('seen')),
          reason: String(form.get('reason') || '').trim(), physically_verified: form.get('sure') === 'on' } };
      }
      if (action === 'collect') body = { reference: typed };
      await send(action === 'override' ? 'collect' : action, body, action);
    }
    async function send(apiAction, body, label) {
      const r = R.detail;
      R.busy = true; R.problem = null;
      document.querySelectorAll('#rv-detail [data-a="rvact"]').forEach(b => { b.disabled = true; });
      try {
        await data().reservationAct(r.reference, apiAction, body);
        toast(t(DONE[label]));
        env.markRead(r.reference);
      } catch (err) {
        R.problem = problemText(err, label);
      } finally {
        R.busy = false;
        await loadDetail();   // always reload: the API says what happened
        refreshCounts(true).then(c => env.badge(c ? c.requested : null)).catch(() => {});
      }
    }
    function problemText(err, label) {
      const d = (err && err.data) || {};
      const code = d.code;
      const canOverride = d.can_override;
      if (code === 'stock_record_insufficient') {
        return esc(t('Not collected: the recorded stock ({s}) is lower than the reserved quantity ({n}). Nothing was changed and the reservation is still confirmed.', { s: d.recorded_quantity, n: d.reserved_quantity }))
          + ' ' + esc(t(canOverride ? 'Count the shelf: correct the stock in My stock if the record is wrong, or use the physical-count override.' : 'Count the shelf and correct the stock in My stock, or ask an owner or manager for a physical-count override.'));
      }
      const map = {
        insufficient_stock: t('Not confirmed: after the other open reservations, the recorded stock covers only {a}. Correct the recorded stock if it is wrong, or decline the request.', { a: d.available_to_reserve ?? 0 }),
        expired: t('This reservation has expired: its deadline passed. It can no longer be changed.'),
        reservation_state_conflict: t('This reservation was already handled (now: {s}). The current state is shown.', { s: t(STATUS_LABEL[d.status] || d.status || '') }),
        stock_changed: t('The recorded stock changed since you looked (now {s}). Count again and repeat the override.', { s: d.recorded_quantity }),
        count_too_low: t('The count must cover the full reserved quantity. Partial collection is not possible.'),
        reason_required: t('Give a reason.'),
        unit_changed: t('The medicine’s unit changed after the request, so it cannot be confirmed. Decline it with a reason.'),
        not_verified: t('Confirm that you physically counted the stock.'),
        stock_missing: t('This branch has no stock record for this medicine any more.'),
        reference_mismatch: t('Not collected: the reference you typed does not match this reservation. Check the code the patient shows, or open the right reservation.'),
        not_reservable: t('This medicine cannot be reserved at this branch right now: {m}', { m: t(ELIGIBILITY[d.reason] || 'it is not set up for reservations.') })
      };
      if (map[code]) return esc(map[code]);
      if (err && err.status === 403) return esc(t('Your role does not allow this action.'));
      return esc(errorText(err));
    }

    /* -------------------------------------------------------------- setup */
    async function loadSetup() {
      const box = $('#rv-setup'); if (!box) return;
      const locs = branches().filter(l => l.is_active);
      if (!locs.length) { box.innerHTML = `<p class="empty">${esc(t('Add a branch first.'))}</p>`; return; }
      if (!locs.some(l => l.location_id === R.setupLoc)) R.setupLoc = (locs.find(l => l.location_id === env.currentLocation()) || locs[0]).location_id;
      const loc = locs.find(l => l.location_id === R.setupLoc);
      const min = loc.reservation_min_stock || 0;
      const canEdit = env.canManage() && !env.isPreview();
      const run = ++R.run;
      box.innerHTML = `<label class="rv-inline">${esc(t('Branch'))} <select id="rv-setup-loc">${locs.map(l => `<option value="${l.location_id}"${l.location_id === R.setupLoc ? ' selected' : ''}>${esc(l.name)}</option>`).join('')}</select></label>
<section class="rv-min" aria-labelledby="rv-min-h">
  <h3 id="rv-min-h">${esc(t('Minimum stock for walk-in customers'))}</h3>
  <p>${esc(t('Set the minimum quantity of each medicine you want to retain for walk-in customers. Medicines will automatically become unavailable for public reservations when their remaining unallocated stock reaches this threshold.'))}</p>
  ${canEdit ? `<form id="rv-min-f" class="rv-inline"><label>${esc(t('Keep back at {b}', { b: loc.name }))} <input id="rv-min" type="number" min="0" max="1000000" step="1" required value="${min}" inputmode="numeric"></label> <button class="solid">${esc(t('Save'))}</button></form>
  <p class="muted">${esc(t('It applies to every medicine at this branch, counted in each medicine’s own unit. Existing reservations are kept when you change it; it only limits new requests.'))}</p>`
    : `<p><strong>${esc(t('{n} of each medicine', { n: min }))}</strong></p><p class="muted">${esc(t('Owners and managers change this.'))}</p>`}
</section>
<p class="muted">${esc(t('A medicine can be reserved when ApexRX has classified it as non-prescription with a defined unit, this branch lists it, and its unallocated stock is above the minimum. Open requests and confirmed reservations both hold stock. Only ApexRX administrators change the catalogue settings.'))}</p>
<div id="rv-meds"><p class="empty">${esc(t('Loading…'))}</p></div>`;
      $('#rv-setup-loc').addEventListener('change', e => { R.setupLoc = +e.target.value; loadSetup(); });
      const f = $('#rv-min-f');
      if (f) f.addEventListener('submit', e => { e.preventDefault(); saveMin(loc); });
      if (env.isPreview()) { $('#rv-meds').innerHTML = `<p class="empty">${esc(t('Your medicines appear here in your live workspace.'))}</p>`; return; }
      try {
        const page = await data().reservationMedicines(R.setupLoc, { limit: 100 });
        if (run !== R.run || !$('#rv-meds')) return;
        R.meds = page.items;
        paintMeds(page.total);
      } catch (err) {
        if (run !== R.run || !$('#rv-meds')) return;
        $('#rv-meds').innerHTML = `<div class="err"><p>${esc(errorText(err))}</p></div>`;
      }
    }
    async function saveMin(loc) {
      const input = $('#rv-min'); if (!input || R.busy) return;
      const n = Number(input.value);
      if (!Number.isInteger(n) || n < 0 || n > 1000000) { input.setCustomValidity(t('Enter a whole number from 0 to 1,000,000.')); input.reportValidity(); input.setCustomValidity(''); return; }
      if (n === (loc.reservation_min_stock || 0)) { toast(t('No change.')); return; }
      R.busy = true;
      try {
        const saved = await data().updateLocation(loc.location_id, { reservation_min_stock: n });
        Object.assign(loc, { reservation_min_stock: saved && saved.reservation_min_stock != null ? saved.reservation_min_stock : n });
        toast(t('Saved. {b} keeps {n} of each medicine for walk-in customers.', { b: loc.name, n: loc.reservation_min_stock }));
      } catch (err) {
        toast(err && err.status === 403 ? t('Your role does not allow this action.') : errorText(err));
      } finally { R.busy = false; loadSetup(); }
    }
    function paintMeds(total) {
      const rows = R.meds || [];
      const more = total > rows.length ? `<p class="muted">${esc(t('Showing the first {n} of {m} medicines.', { n: rows.length, m: total }))}</p>` : '';
      $('#rv-meds').innerHTML = rows.length ? `<div class="tw"><table class="rv-meds">
<caption class="sr">${esc(t('Medicines at this branch'))}</caption>
<thead><tr><th scope="col">${esc(t('Medicine'))}</th><th scope="col">${esc(t('Recorded'))}</th><th scope="col">${esc(t('Held by reservations'))}</th><th scope="col">${esc(t('Unallocated'))}</th><th scope="col">${esc(t('Kept back'))}</th><th scope="col">${esc(t('Reservable now'))}</th><th scope="col">${esc(t('Status'))}</th><th scope="col"><span class="sr">${esc(t('Catalogue settings'))}</span></th></tr></thead>
<tbody>${rows.map((m, i) => `<tr>
<th scope="row">${esc(m.product_name)}<br><small class="muted">${esc(unitText(m.unit))}</small></th>
<td>${m.recorded_quantity}</td><td>${m.held_quantity}</td><td>${m.unallocated_quantity}</td><td>${m.min_stock}</td><td><strong>${m.reservable_quantity}</strong></td>
<td>${m.reservable ? `<span class="tag good">✓ ${esc(t('Reservable'))}</span><br><small class="muted">${esc(t('Up to {n} per reservation', { n: m.max_quantity }))}</small>` : `<span class="tag">${esc(t('Not reservable'))}</span><br><small>${esc(t(ELIGIBILITY[m.reason] || m.message || m.reason || ''))}</small>`}</td>
<td><button class="ghost" data-a="rvsettings" data-i="${i}">${esc(t('Catalogue settings'))}</button></td></tr>`).join('')}</tbody></table></div>${more}`
        : `<p class="empty">${esc(t('This branch has no stock records yet. Add medicines in My stock first.'))}</p>`;
    }
    async function settings(i) {
      const u = (R.meds || [])[i]; if (!u) return;
      try {
        const s = await data().reservationSettings(u.product_id);
        await ask(t('Catalogue settings for {m}', { m: u.product_name }), `<dl class="kv rv-dlg">
<dt>${esc(t('Classification'))}</dt><dd>${esc(t(CLASS[s.dispensing_class] || s.dispensing_class))}</dd>
<dt>${esc(t('Counted in'))}</dt><dd>${esc(s.stock_unit === 'pack' ? t('Packs') : s.stock_unit === 'unit' ? t('Single units') : t('Not defined yet'))}</dd>
<dt>${esc(t('Unit name'))}</dt><dd>${esc(s.unit_label || '—')}</dd>
<dt>${esc(t('Pack size'))}</dt><dd>${esc(s.pack_size || '—')}</dd>
<dt>${esc(t('Maximum per reservation'))}</dt><dd>${esc(s.effective_max_quantity)}</dd></dl>
${s.problems.length ? `<p><strong>${esc(t('Why it cannot be reserved yet'))}</strong></p><ul>${s.problems.map(p => `<li>${esc(t(PROBLEMS[p.code] || p.message))}</li>`).join('')}</ul>` : ''}
<p class="note">${esc(t('Only ApexRX administrators change these settings, because every pharmacy shares the catalogue.'))}</p>`, t('Close'));
      } catch (err) { toast(errorText(err)); }
    }

    /* ---------------------------------------------------------- dispatch */
    const actions = {
      rvmode: d => { R.mode = d.m; R.problem = null; env.go(); },
      rvgroup: d => { R.status = d.s; R.page = 0; document.querySelectorAll('#rv-groups .chip').forEach(c => { const on = c.dataset.s === d.s; c.classList.toggle('on', on); c.setAttribute('aria-pressed', String(on)); }); loadList(); },
      rvreset: () => { Object.assign(R, { status: 'requested', loc: '', from: '', to: '', ref: '', sort: 'deadline', page: 0 }); env.go(); },
      rvpage: d => { R.page = Math.max(0, R.page + Number(d.d)); loadList(); },
      rvretry: () => loadList(),
      rvopen: d => openRef(d.r),
      rvback: () => { R.mode = 'list'; R.problem = null; env.go(); },
      rvact: d => act(d.x),
      rvstock: () => { const r = R.detail; if (r) env.openStock(r.location_id, r.medicine.product_name); },
      rvsettings: d => settings(+d.i)
    };
    // Background refresh: at most every 40 s, only on this screen, never while a
    // dialog is open or a field has focus, and never overlapping. Failures keep
    // what is shown (a 401 signs out through js/api.js).
    let lastPoll = 0, polling = false;
    const sig = x => JSON.stringify(x);
    async function poll() {
      if (!live() || polling || R.busy || env.busy() || Date.now() - lastPoll < 40000) return;
      if (R.mode === 'setup') return;
      polling = true; lastPoll = Date.now();
      try {
        if (R.mode === 'detail' && R.open && $('#rv-detail')) {
          const next = await data().reservation(R.open, true);
          if (R.mode === 'detail' && $('#rv-detail') && sig(next) !== sig(R.detail) && !env.busy()) {
            R.detail = next; paintDetail();
          }
        } else if (R.mode === 'list' && $('#rv-list') && R.list) {
          const params = filters({ limit: PAGE, offset: R.page * PAGE });
          if (R.status) params.status = R.status;
          const [page] = await Promise.all([data().reservations(params, true), refreshCounts(true)]);
          if (R.mode !== 'list' || !$('#rv-list') || env.busy()) return;
          const g = $('#rv-groups'); if (g) g.innerHTML = groupChips();
          env.badge(R.counts ? R.counts.requested : null);
          if (sig(page) !== sig(R.list)) { R.list = page; paintList(); }
        }
      } catch (e) { /* keep the current screen */ } finally { polling = false; }
    }
    function openRef(ref) { R.mode = 'detail'; R.open = ref; R.problem = null; R.detail = null; env.go(); }
    return { view, after, actions, openRef, newRequests, refreshCounts, poll };
  }

  const DONE = {
    confirm: 'Reservation confirmed. The patient is told.', decline: 'Request declined. The patient is told.',
    cancel: 'Reservation cancelled. The patient is told.', collect: 'Collection recorded. The stock was reduced.',
    override: 'Override recorded and collection completed.'
  };
  const HISTORY = {
    requested: 'Requested', confirmed: 'Confirmed', declined: 'Declined', cancelled: 'Cancelled', collected: 'Collected', expired: 'Expired (reservation)'
  };
  const SYSTEM_REASON = {
    response_window_elapsed: 'No answer within 24 hours.', collection_window_elapsed: 'Not collected within 24 hours.',
    pharmacy_suspended: 'The pharmacy was suspended.'
  };
  const ELIGIBILITY = {
    branch_not_found: 'This branch does not exist.', not_a_pharmacy: 'Only pharmacies take reservations.',
    pharmacy_unavailable: 'The pharmacy is not approved right now.', branch_inactive: 'The branch is closed.',
    product_inactive: 'The medicine was retired from the catalogue.', prescription_only: 'Prescription-only medicines cannot be reserved.',
    unclassified: 'ApexRX has not classified this medicine yet.', unit_unknown: 'ApexRX has not defined its unit yet.',
    pack_size_missing: 'ApexRX has not defined its pack size yet.',
    offer_unlisted: 'The branch does not list this medicine (price it and list it in My stock).',
    no_reservable_stock: 'Its unallocated stock is at or below the minimum kept for walk-in customers.'
  };
  const CLASS = { unclassified: 'Not classified yet', non_prescription: 'Non-prescription', prescription_only: 'Prescription only' };
  const PROBLEMS = {
    product_inactive: 'The medicine was retired from the catalogue.', not_non_prescription: 'It is not classified as non-prescription.',
    unit_unknown: 'Its unit is not defined.', unit_label_missing: 'Its unit has no name.', unit_label_invalid: 'Its unit name is not valid.',
    pack_size_missing: 'It is counted in packs but has no pack size.'
  };

  global.DashReservations = create;
})(window);
