'use strict';
/* Registration for pharmacies.html and suppliers.html (<body data-role>).
 *   Account  -> POST /auth/register, /auth/login. A known email signs in instead.
 *   Verify   -> mobile number by SMS one-time code: POST /auth/phone/send-code, then
 *               /auth/phone/verify. GET /auth/phone/status says whether the step is
 *               needed. The backend decides: it refuses a pharmacy until the caller's
 *               phone is verified, and uses that verified number.
 *   Profile  -> POST /organizations, its location and the selected documents.
 *               Coming back and saving again updates the same records.
 *   Plan     -> subscriptions are not in the backend yet; payment is simulated.
 * Then the dashboard opens. "Just exploring?" opens it with sample data and no account. */
(function () {
  const R = document.body.dataset.role;
  const CFG = R === 'pharmacy'
    ? { price: '20,000', dash: 'pharmacy-dashboard.html' }
    : { price: '15,000', dash: 'supplier-dashboard.html' };
  const API = window.ApexAPI;
  const { T, PN, API_TEXT } = window.ONBOARD_T;
  const PROV = ['Kigali', 'East', 'West', 'North', 'South'];
  const LIVE = 'https://apexrx-smart.netlify.app';
  // The API only answers the hosted site, so a copy opened elsewhere cannot sign anyone up.
  const wrongPlace = location.origin !== LIVE && /apexrx-smart\.onrender\.com/.test(API.baseUrl);
  const MAX_FILE = 10 * 1024 * 1024;
  const DOC_TYPES = { d_biz: 'business_license', d_pharm: 'pharmacy_license', d_owner: 'owner_id', d_tin: 'tin_certificate', d_fda: 'fda_license' };
  const $ = s => document.querySelector(s);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  let lang = 'en';
  try { lang = new URLSearchParams(location.search).get('lang') || localStorage.getItem('apexrx_lang') || 'en'; } catch (e) { /* ignore */ }
  if (!T[lang]) lang = 'en';
  const t = k => T[lang][k] ?? T.en[k] ?? k;
  const r = k => T[lang][k + '_' + R] ?? T.en[k + '_' + R] ?? t(k);

  let step = 0, L = null, coords = null, method = 'mtn';
  let signin = location.hash === '#signin';
  const V = {}, A = { prov: 'Kigali', dist: '', sect: '', cell: '', vill: '', street: '' };
  const account = { org: null, location: null, role: null, email: '' };
  // SMS step: survives a redraw of the form (language change, going back).
  const P = { phone: '', sentTo: null, masked: '', minutes: 5, resendAt: 0, timer: null, verified: null };

  fetch('data/rwanda-locations.json').then(x => x.json()).then(j => { L = j; if (step === 2) render(); }).catch(() => { L = false; if (step === 2) render(); });

  const iv = n => esc(V[n] || '');
  const keys = o => Object.keys(o || {}).sort((a, b) => a.localeCompare(b));
  const node = () => { const o = L && L[A.prov]; return { d: o, s: o && o[A.dist], c: o && o[A.dist] && o[A.dist][A.sect], v: o && o[A.dist] && o[A.dist][A.sect] && o[A.dist][A.sect][A.cell] }; };
  function sel(id, label, list, val) { return `<label>${label}<select data-a="${id}"${!list.length ? ' disabled' : ''}><option value="">${t('select')}</option>${list.map(x => `<option value="${esc(x)}"${x === val ? ' selected' : ''}>${esc(x)}</option>`).join('')}</select></label>`; }
  function addr() {
    const n = node();
    if (L === false) return `<div class="fields"><label>${t('district')}<input data-a="dist" value="${esc(A.dist)}"></label><label>${t('sector')}<input data-a="sect" value="${esc(A.sect)}"></label><label>${t('cell')}<input data-a="cell" value="${esc(A.cell)}"></label><label>${t('village')}<input data-a="vill" value="${esc(A.vill)}"></label></div><p class="note">${t('noData')}</p>`;
    return `<label>${t('province')}<select data-a="prov">${PROV.map(p => `<option value="${p}"${p === A.prov ? ' selected' : ''}>${PN[lang][p]}</option>`).join('')}</select></label><div class="fields">${sel('dist', t('district'), keys(n.d), A.dist)}${sel('sect', t('sector'), keys(n.s), A.sect)}${sel('cell', t('cell'), keys(n.c), A.cell)}${sel('vill', t('village'), (n.v || []).slice().sort(), A.vill)}</div>`;
  }
  const summary = () => [PN[lang][A.prov], A.dist, A.sect, A.cell, A.vill, A.street].filter(Boolean).join(' > ');
  function addrBlock() { return `<div class="loc-title"><strong>${r('locT')}</strong></div><div id="addr">${addr()}</div><p class="sum" id="sum">${t('summary')}: ${esc(summary())}</p><label>${t('street')}<input data-a="street" placeholder="${t('streetph')}" value="${esc(A.street)}"></label>`; }
  function field(n, label, ph, help, type) {
    const locked = n === 'phone' && R === 'pharmacy' && P.verified;
    return `<label>${label}<input name="${n}" data-v="${n}" type="${type || 'text'}" placeholder="${ph || ''}" value="${iv(n)}"${locked ? ` readonly title="${esc(t('smsLocked'))}"` : ''}>${help ? `<span class="help">${help}</span>` : ''}</label>`;
  }
  const docs = () => R === 'pharmacy' ? ['d_pharm', 'd_biz', 'd_owner'] : ['d_tin', 'd_fda', 'd_owner'];

  const FORMS = [
    () => `<form id="account" novalidate><label>${t('email')}<input name="email" data-v="email" type="email" autocomplete="email" placeholder="${R === 'pharmacy' ? 'pharmacy' : 'depot'}@example.com" value="${iv('email')}"></label>${signin
      ? `<label>${t('pw')}<input name="password" type="password" autocomplete="current-password"></label>`
      : `<div class="fields"><label>${t('pw')}<input name="password" type="password" autocomplete="new-password" placeholder="${t('pwph')}"></label><label>${t('pw2')}<input name="confirm" type="password" autocomplete="new-password" placeholder="${t('pw2ph')}"></label></div><p class="note">${t('demoNote')}</p>`}<button class="primary">${signin ? t('signinBtn') : t('create')} <span>→</span></button><button type="button" class="text-button" data-mode>${signin ? t('toCreate') : t('toSignin')}</button><button type="button" class="text-button" data-go="preview">${t('explore')}</button></form>`,
    () => `<form id="verify" novalidate><div class="mail" aria-hidden="true">✆</div><label>${t('mobile')}<input name="phone" type="tel" inputmode="tel" autocomplete="tel" placeholder="078 812 3456" maxlength="30" value="${esc(P.phone)}"></label><button type="button" class="secondary" id="send-code">${t('sendCode')}</button><div id="code-area"${P.sentTo ? '' : ' hidden'}><p id="code-sent" class="note" role="status">${P.sentTo ? esc(codeSentText()) : ''}</p><label>${t('code')}<input name="code" class="otp" inputmode="numeric" maxlength="6" autocomplete="one-time-code"></label><button type="button" class="text-button" id="resend-code" disabled>${t('resend')}</button></div><p class="note">${t('smsNote')}</p><button class="primary" id="verify-code">${t('verify')} <span>→</span></button><button type="button" class="text-button" data-back="0">${t('change')}</button></form>`,
    () => `<form id="profile" novalidate>${R === 'pharmacy' ? field('name', t('pname'), 'Kigali Central Pharmacy') + field('npc', t('npc'), t('npcph'), t('npchelp')) + field('lic', t('lic'), 'PH-12345') + field('phone', t('phone'), '+250 788 123 456', '', 'tel') : field('name', t('bname'), 'PharmaRwanda Wholesale') + field('tin', t('tin'), t('tinph'), t('tinhelp')) + field('fda', t('fda'), t('fdaph'), t('fdahelp')) + field('fdaexp', t('fdaexp'), '', '', 'date') + field('phone', t('phone'), '+250 788 123 456', '', 'tel')}
${addrBlock()}
<div class="doc-h"><button type="button" class="secondary" data-geo>${coords ? '✓ ' + t('geoOk') : t('geo')}</button></div><p class="note">${R === 'pharmacy' ? t('geoPh') : t('geoHelp')}</p>
<div class="doc-h"><strong>${t('docs')}</strong><small>${t('optional')}</small></div><div class="uploads">${docs().map(k => `<label>${t(k)}<input type="file" data-doc="${DOC_TYPES[k]}" accept=".pdf,.png,.jpg,.jpeg"></label>`).join('')}</div><p class="note">${t('docNote')}</p>
<div class="actions"><button type="button" class="secondary" data-back="1">${t('back2')}</button><button class="primary">${t('toPlan')}</button></div></form>`,
    () => `<form id="payment" novalidate><div class="plan"><span class="eyebrow">${t('planLbl')}</span><div><strong>${CFG.price}</strong> RWF <span class="u">${t('month')}</span></div><p>${t('ben_' + R)}</p><p>${t('neutral')}</p></div><fieldset><legend>${t('payM')}</legend><div class="methods">${['mtn', 'airtel', 'card'].map(m => `<label><input type="radio" name="m" value="${m}"${m === method ? ' checked' : ''}> ${t(m)}</label>`).join('')}</div></fieldset><div class="pay"><span class="demo">${t('sim')}</span><h3 id="pm">${t(method)}</h3><p>${t('simNote')}</p></div><div class="actions"><button type="button" class="secondary" data-back="2">${t('back2')}</button><button class="primary">${t('simBtn')}</button></div></form>`,
    () => `<div class="done-card"><dl><dt>${t('sumName')}</dt><dd>${esc(V.name)}</dd>${R === 'pharmacy' ? `<dt>${t('sumNpc')}</dt><dd>${esc(V.npc)}</dd>` : `<dt>${t('sumTin')}</dt><dd>${esc(V.tin)}</dd><dt>${t('sumFda')}</dt><dd>${esc(V.fda)}</dd>`}<dt>${t('sumAddr')}</dt><dd>${esc(summary())}</dd><dt>${t('sumStatus')}</dt><dd><span class="pill">${t('pending')}</span></dd></dl>${R === 'supplier' ? `<div class="idbox"><span class="eyebrow">${t('idLbl')}</span><br><strong>${esc(V.sid)}</strong><p>${t('idNote')}</p></div>` : ''}</div><button class="primary" data-go="dash">${t('open')}</button>`
  ];

  function render() {
    const e = (i, k) => { const el = $(i); if (el) el.innerHTML = k; };
    document.documentElement.lang = lang; $('#lang').value = lang; $('#tag').textContent = t('tag'); $('#back').textContent = t('back');
    e('#st-e', r('e')); e('#st-h', r('h')); e('#st-p', r('p')); e('#st-c', r('c')); e('#st-f', r('f')); e('#wf', r('w'));
    $('#steps').innerHTML = t('steps').map((s, i) => `<li class="${i === step ? 'active' : i < step ? 'done' : ''}"${i === step ? ' aria-current="step"' : ''}>${s}</li>`).join('');
    $('#cap').textContent = t('cap').replace('{n}', step + 1);
    const titles = [signin ? t('signinT') : r('s1t'), t('s2t'), r('s3t'), t('s4t'), t('s5t')];
    const descs = [signin ? t('signinD') : r('s1d'), t('s2d'), r('s3d'), t('s4d').replace('{r}', R === 'pharmacy' ? 'pharmacy' : 'supplier').replace('{p}', CFG.price), r('s5d')];
    $('#stitle').textContent = titles[step]; $('#step-description').textContent = descs[step]; $('#body').innerHTML = FORMS[step](); $('#form-error').textContent = '';
    if (wrongPlace) {
      const note = document.createElement('p'); note.className = 'sum';
      const link = document.createElement('a'); link.href = LIVE + location.pathname.replace(/^.*\//, '/') + '?lang=' + lang; link.textContent = t('addrLink');
      note.append(t('addrNote') + ' ', link); $('#body').prepend(note);
    }
    paintTheme();
    if (step === 1) renderResend();
  }
  function paintTheme() {
    const b = $('#theme'); b.textContent = ApexTheme.get() === 'dark' ? '☀' : '☾';
    b.title = t('theme'); b.setAttribute('aria-label', t('theme'));
  }
  // A language change redraws the form: put back what cannot be redrawn from V.
  function renderKeepingInput() {
    const secret = {}, files = {};
    ['password', 'confirm', 'code'].forEach(n => { const i = document.querySelector(`[name=${n}]`); if (i) secret[n] = i.value; });
    document.querySelectorAll('input[data-doc]').forEach(i => { if (i.files && i.files[0]) files[i.dataset.doc] = i.files[0]; });
    render();
    Object.keys(secret).forEach(n => { const i = document.querySelector(`[name=${n}]`); if (i) i.value = secret[n]; });
    Object.keys(files).forEach(k => {
      const i = document.querySelector(`input[data-doc=${k}]`), box = new DataTransfer();
      box.items.add(files[k]); if (i) i.files = box.files;
    });
  }
  const fail = m => { $('#form-error').textContent = m; };
  // Browsers can fill a form without any input event, so read the fields on submit.
  const readFields = form => form.querySelectorAll('[data-v]').forEach(i => { V[i.dataset.v] = i.value.trim(); });
  function errorText(err) {
    if (err.status === 0) return wrongPlace ? t('addrNote') : t('errNet');
    if (err.data && (err.data.retry_after || err.data.reason)) return API_TEXT(err.message, lang);
    if (err.status === 429) return t('errRate');
    if (err.status === 502 || err.status === 503) return API_TEXT(err.message, lang);
    if (err.status >= 500) return t('errServer');
    return API_TEXT(err.message, lang);
  }
  const go = n => { step = n; render(); window.scrollTo(0, 0); $('#stitle').focus(); };
  const openDash = preview => { location.href = CFG.dash + '?lang=' + lang + (preview ? '&preview=1' : ''); };

  async function busy(form, task) {
    const buttons = [...form.querySelectorAll('button')];
    if (form.dataset.busy === 'true') return;
    form.dataset.busy = 'true'; form.setAttribute('aria-busy', 'true'); buttons.forEach(b => { b.disabled = true; });
    fail('');
    // Render's free plan sleeps, and the first request can take about a minute.
    const slow = setTimeout(() => fail(t('slow')), 4000);
    try { await task(); } catch (err) {
      clearTimeout(slow);
      if (err.status === 401) { go(0); fail(t('errSession')); } else fail(errorText(err));
    } finally {
      clearTimeout(slow);
      if ($('#form-error').textContent === t('slow')) fail('');
      form.dataset.busy = 'false'; form.removeAttribute('aria-busy'); buttons.forEach(b => { b.disabled = false; });
    }
  }

  /* Returns true when the signed-in user already has a workspace, and opens it. */
  async function loadAccount() {
    const me = await API.auth.me();
    account.email = me.email; V.email = me.email;
    const all = me.memberships || [];
    const mine = all.filter(m => m.organization_type === R);
    const m = mine.find(x => x.role === 'owner') || mine.find(x => x.role === 'manager') || mine[0];
    if (m) { openDash(); return true; }
    if (all.length) { location.href = all[0].organization_type + '-dashboard.html?lang=' + lang; return true; }
    return false;
  }

  /* The SMS step. Every decision is made by the backend; this only drives the form. */
  const codeSentText = () => t('codeSent').replace('{p}', P.masked).replace('{m}', P.minutes);
  function renderResend() {
    const b = $('#resend-code'); if (!b) return;
    const left = Math.ceil((P.resendAt - Date.now()) / 1000);
    if (left > 0) { b.disabled = true; b.textContent = t('resendIn').replace('{n}', left); return; }
    b.disabled = false; b.textContent = t('resend');
    clearInterval(P.timer); P.timer = null;
  }
  function startCountdown(seconds) {
    P.resendAt = Date.now() + Math.max(0, seconds) * 1000;
    clearInterval(P.timer); P.timer = setInterval(renderResend, 1000);
    renderResend();
  }
  function useVerifiedPhone(number) { P.verified = number; V.phone = number; }
  // After sign-in: verify the phone, unless the backend says it is not needed.
  async function toPhoneStep() {
    let status = null;
    try {
      const res = await API.auth.phone.status();
      if (res && typeof res.required === 'boolean' && typeof res.verified === 'boolean') status = res;
    } catch (err) {
      if (err.status === 401) throw err;
      // An older backend or a network error: unknown. The backend still refuses an
      // unverified pharmacy (403), and the profile step then brings the user back here.
    }
    if (!status) { go(2); return; }
    if (status.verified) { useVerifiedPhone(status.verified_phone); go(2); return; }
    if (!status.required || (R === 'supplier' && !status.sms_available)) { go(2); return; }
    go(1);
    if (!status.sms_available) fail(t('smsOff'));
  }
  async function requestCode() {
    const form = $('#verify'), f = form.elements, phone = f.phone.value.trim();
    if (!phone) { fail(t('smsPhone')); f.phone.focus(); return; }
    if (P.sentTo === phone && P.resendAt > Date.now()) { renderResend(); return; }
    await busy(form, async () => {
      try {
        const sent = await API.auth.phone.sendCode(phone);
        P.sentTo = sent.phone; P.phone = sent.phone; P.masked = sent.phone_masked;
        P.minutes = Math.max(1, Math.round(sent.expires_in / 60));
        f.phone.value = sent.phone;
        $('#code-area').hidden = false; $('#code-sent').textContent = codeSentText();
        f.code.value = '';
        startCountdown(sent.resend_after);
        f.code.focus();
      } catch (err) {
        if (err.status === 401) throw err;
        if (err.status === 429 && err.data && err.data.retry_after) startCountdown(err.data.retry_after);
        fail(errorText(err));
      }
    });
    renderResend(); // busy() re-enabled every button: keep the countdown
  }
  function submitCode(form) {
    const f = form.elements;
    if (!P.sentTo) { requestCode(); return; } // Enter in the phone field sends the code
    const code = f.code.value.replace(/\D/g, '');
    if (code.length !== 6) { fail(t('smsCode')); f.code.focus(); return; }
    busy(form, async () => {
      try {
        const res = await API.auth.phone.verify(P.sentTo, code);
        clearInterval(P.timer); P.timer = null;
        useVerifiedPhone(res.verified_phone);
        go(2);
      } catch (err) {
        if (err.status === 401) throw err;
        const reason = err.data && err.data.reason;
        if (['expired', 'too_many_attempts', 'no_active_code'].includes(reason)) { f.code.value = ''; P.resendAt = 0; }
        fail(errorText(err));
        if (reason === 'incorrect' || reason === 'format') f.code.select();
      }
    }).then(renderResend);
  }

  async function saveProfile(form) {
    const province = A.prov, line = [A.street, A.vill, A.cell, A.sect].filter(Boolean).join(', ');
    const licence = R === 'pharmacy'
      ? { npc_number: V.npc || null, license_number: V.lic || null }
      : { tin: V.tin || null, fda_license_number: V.fda || null, fda_license_expiry: V.fdaexp || null };
    const organization = { name: V.name, phone: V.phone || null, email: account.email || null, ...licence };
    const location_ = { name: V.name, address: line || null, city: A.dist || null, region: province, phone: V.phone || null, whatsapp_phone: V.phone || null, latitude: coords ? coords.lat : null, longitude: coords ? coords.lng : null };
    if (!account.org) {
      account.org = await API.organizations.create({ ...organization, type: R });
    } else {
      account.org = await API.organizations.update(account.org.organization_id, organization);
    }
    const id = account.org.organization_id;
    account.location = account.location
      ? await API.organizations.updateLocation(id, account.location.location_id, location_)
      : await API.organizations.createLocation(id, location_);
    for (const input of form.querySelectorAll('input[type=file][data-doc]')) {
      if (input.files && input.files[0]) { await API.organizations.uploadDocument(id, input.dataset.doc, input.files[0]); input.value = ''; }
    }
    V.sid = 'SUP-' + String(id).padStart(5, '0');
  }

  document.addEventListener('input', e => {
    const x = e.target;
    if (x.form && x.form.id === 'verify' && x.name === 'phone') {
      P.phone = x.value.trim();
      // Editing the number after a code was sent means a new code is needed.
      if (P.sentTo && P.phone !== P.sentTo) { P.sentTo = null; $('#code-area').hidden = true; $('#code-sent').textContent = ''; }
    } else if (x.dataset.v) { V[x.dataset.v] = x.value.trim(); x.classList.remove('bad'); }
    else if (x.dataset.a === 'street' || (L === false && x.dataset.a)) { A[x.dataset.a] = x.value.trim(); $('#sum').textContent = t('summary') + ': ' + summary(); }
  });
  document.addEventListener('change', e => {
    const x = e.target;
    if (x.id === 'lang') { lang = x.value; try { localStorage.setItem('apexrx_lang', lang); } catch (err) { /* ignore */ } renderKeepingInput(); return; }
    if (x.name === 'm') { method = x.value; $('#pm').textContent = t(x.value); return; }
    if (x.dataset.doc) {
      const file = x.files[0];
      if (file && (file.size > MAX_FILE || !/\.(pdf|png|jpe?g)$/i.test(file.name))) { x.value = ''; fail(t('errFile')); } else fail('');
      return;
    }
    const k = x.dataset.a;
    if (!k || L === false || k === 'street') return;
    A[k] = x.value;
    if (k === 'prov') A.dist = A.sect = A.cell = A.vill = '';
    if (k === 'dist') A.sect = A.cell = A.vill = '';
    if (k === 'sect') A.cell = A.vill = '';
    if (k === 'cell') A.vill = '';
    $('#addr').innerHTML = addr(); $('#sum').textContent = t('summary') + ': ' + summary();
  });
  document.addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.id === 'theme') { ApexTheme.toggle(); paintTheme(); return; }
    if (b.id === 'send-code' || b.id === 'resend-code') { requestCode(); return; }
    if (b.dataset.mode !== undefined) { readFields(b.form); signin = !signin; render(); return; }
    if (b.dataset.go === 'dash') { openDash(false); return; }
    if (b.dataset.go === 'preview') { openDash(true); return; }
    if (b.dataset.back !== undefined) { go(+b.dataset.back); return; }
    if (b.dataset.geo !== undefined) {
      if (!navigator.geolocation) { fail(t('geoHelp')); return; }
      navigator.geolocation.getCurrentPosition(p => { coords = { lat: +p.coords.latitude.toFixed(6), lng: +p.coords.longitude.toFixed(6) }; b.textContent = '✓ ' + t('geoOk'); }, () => fail(t('geoHelp')));
    }
  });
  document.addEventListener('submit', e => {
    e.preventDefault();
    const form = e.target, id = form.id, f = form.elements;
    if (id === 'account') {
      readFields(form);
      if (!/^\S+@\S+\.\S+$/.test(V.email || '')) return fail(t('errMail'));
      const password = f.password.value;
      if (signin) {
        if (!password) return fail(t('errLogin'));
        busy(form, async () => {
          try { await API.auth.login(V.email, password); } catch (err) {
            if (err.status === 401) { fail(t('errLogin')); return; }
            throw err;
          }
          if (!await loadAccount()) await toPhoneStep();
        });
        return;
      }
      if (password.length < 8) return fail(t('errPwShort'));
      if (password !== f.confirm.value) return fail(t('errPw'));
      busy(form, async () => {
        let existing = false;
        try { await API.auth.register({ name: V.email.split('@')[0].slice(0, 150) || V.email, email: V.email, password }); } catch (err) {
          if (err.status !== 409) throw err;
          existing = true;
        }
        try { await API.auth.login(V.email, password); } catch (err) {
          if (err.status === 401 && existing) { fail(t('errExists')); return; }
          throw err;
        }
        if (!await loadAccount()) await toPhoneStep();
      });
    } else if (id === 'verify') {
      submitCode(form);
    } else if (id === 'profile') {
      readFields(form);
      const need = R === 'pharmacy' ? ['name', 'lic', 'phone'] : ['name', 'fda', 'fdaexp', 'phone'];
      document.querySelectorAll('[data-v]').forEach(i => i.classList.remove('bad'));
      if (R === 'pharmacy' && !V.npc) { document.querySelector('[data-v=npc]').classList.add('bad'); return fail(t('errNpc')); }
      if (need.some(k => !V[k])) return fail(t('errReq'));
      if (!/^\+?[0-9 ()-]{6,30}$/.test(V.phone)) return fail(t('errPhone'));
      if (R === 'supplier') {
        if (!/^\d{9}$/.test(V.tin || '')) return fail(t('errTin'));
        if (V.fdaexp < new Date().toISOString().slice(0, 10)) return fail(t('errExp'));
      }
      if (L === false ? !(A.dist && A.sect && A.cell && A.vill) : !(A.prov && A.dist && A.sect && A.cell && A.vill)) return fail(t('errAddr'));
      busy(form, async () => {
        try { await saveProfile(form); go(3); } catch (err) {
          if (err.status === 403 && !account.org) { go(1); fail(errorText(err)); return; } // phone not verified yet
          throw err;
        }
      });
    } else if (id === 'payment') {
      go(4);
    }
  });
  window.addEventListener('apexrx:theme', () => { if ($('#theme')) paintTheme(); });

  render();
  // Wake the free-plan server early, so it is ready by the time the form is sent.
  API.health().catch(() => {});
  (async function resume() {
    if (!API.session.isSignedIn()) return;
    try { if (!await loadAccount()) await toPhoneStep(); } catch (err) { if (err.status !== 401) fail(errorText(err)); }
  })();
})();
