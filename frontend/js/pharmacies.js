'use strict';
/* Pharmacy onboarding and workspace, connected to the ApexRX API (js/api.js).
 *
 * Steps:
 *   0 Account  -> POST /auth/register, then POST /auth/login. If the email is
 *                 already registered, the same form signs in instead.
 *   1 Verify   -> mobile number by SMS one-time code: POST /auth/phone/send-code,
 *                 then POST /auth/phone/verify. The backend decides: it refuses
 *                 to create a pharmacy until the caller's phone is verified, and
 *                 uses that verified number. GET /auth/phone/status says whether
 *                 the step is needed (skipped when already verified or when the
 *                 backend does not require it).
 *   2 Profile  -> POST /organizations (type pharmacy), POST .../locations,
 *                 POST .../documents for each selected file. Going back and
 *                 resubmitting updates the same records (PATCH).
 *   3 Plan     -> subscriptions are not in the v6 backend; still simulated.
 *   4 Workspace-> supplier discovery via GET /supplier-offers (approved
 *                 pharmacies only), contact through WhatsApp/phone links.
 *
 * "Just exploring?" still opens the workspace with sample data and no account.
 */
const $ = s => document.querySelector(s);
const API = window.ApexAPI;
const forms = [...document.querySelectorAll('.step-form')];
const titles = ['Create your pharmacy account', 'A little check. A stronger connection.', 'Make your pharmacy easy to find.', 'One plan. More possibilities.'];
const descriptions = ['Join a connected community of pharmacies and suppliers in Kigali.', 'Verify your mobile number to take the next step.', 'Add your practice details, location and licensing documents.', 'Access your pharmacy workspace for 5,000 RWF per month.'];
const SAMPLE_PROFILE = { name: 'Kigali Pharmacy', license: 'PH-DEMO', phone: '+250 788 123 456', address: 'Kigali, Rwanda', latitude: '-1.9441', longitude: '30.0619' };
const DEFAULT_CITY = 'Kigali';
const STATUS_NOTES = {
  pending: 'Your pharmacy is awaiting verification by ApexRX. Supplier search opens once it is approved.',
  approved: 'Your pharmacy is verified. Listed medicines are visible to patients on ApexRX.',
  rejected: 'Your registration was not approved. Update your details and documents, then contact ApexRX to resubmit.',
  suspended: 'Your pharmacy is suspended. Contact ApexRX for help.'
};
const NO_CONTACTS = 'No supplier conversations yet. Search for a medicine to find a supplier and contact them.';
const SEARCH_HINT = 'Search for a medicine to see supplier stock, prices and contacts.';
const LIVE_PANEL_NOTE = 'Supplier stock and prices are live. Conversations happen on WhatsApp or by phone; subscriptions are not live yet.';

let profile = { ...SAMPLE_PROFILE };
// Live account state. null while previewing with sample data.
let live = null; // { user, organization, location }
let accountEmail = '';
let noticeTimer;

function notice(text) { $('#notice').textContent = text; clearTimeout(noticeTimer); noticeTimer = setTimeout(() => $('#notice').textContent = '', 7000); }
function formError(text) { $('#form-error').textContent = text || ''; }
function errorText(err) { return (err && err.message) || 'Something went wrong. Please try again.'; }

function step(index, focus = true) {
  forms.forEach((form, i) => form.hidden = i !== index);
  document.querySelectorAll('.steps li').forEach((li, i) => {
    li.classList.toggle('active', i === index); li.classList.toggle('done', i < index);
    if (i === index) li.setAttribute('aria-current', 'step'); else li.removeAttribute('aria-current');
  });
  $('#step-caption').textContent = `STEP 0${index + 1} / 05`;
  $('#step-title').textContent = titles[index];
  $('#step-description').textContent = descriptions[index];
  formError('');
  if (focus) $('#step-title').focus();
}

// Disable a form's buttons while a request runs, so it is never sent twice.
async function busy(form, task) {
  const buttons = [...form.querySelectorAll('button')];
  if (form.dataset.busy === 'true') return;
  form.dataset.busy = 'true'; form.setAttribute('aria-busy', 'true');
  buttons.forEach(b => b.disabled = true);
  try { await task(); } finally {
    form.dataset.busy = 'false'; form.removeAttribute('aria-busy');
    buttons.forEach(b => b.disabled = false);
  }
}

/* ------------------------------------------------------------ live state */
function pharmacyMembership(me) {
  const active = (me.memberships || []).filter(m => m.organization_type === 'pharmacy');
  // Prefer an organization the user can manage.
  return active.find(m => m.role === 'owner') || active.find(m => m.role === 'manager') || active[0] || null;
}

function profileFromLive() {
  const o = live.organization, l = live.location || {};
  return {
    name: o.name,
    license: profile.license && profile.license !== SAMPLE_PROFILE.license ? profile.license : '—',
    phone: l.phone || o.phone || '—',
    address: l.address || '—',
    latitude: l.latitude != null ? String(l.latitude) : '—',
    longitude: l.longitude != null ? String(l.longitude) : '—',
    status: o.status,
    documents: (live.documents || []).length
      ? live.documents.map(d => `${DOCUMENT_LABELS[d.document_type] || d.document_type}: ${d.verification_status}`).join(' · ')
      : 'None uploaded'
  };
}

// Load the signed-in user, their pharmacy and its main location.
async function loadLive() {
  const me = await API.auth.me();
  accountEmail = me.email;
  const membership = pharmacyMembership(me);
  live = { user: me, organization: null, location: null, role: membership ? membership.role : null };
  if (!membership) return live;
  live.organization = await API.organizations.get(membership.organization_id);
  const locations = await API.organizations.locations(membership.organization_id);
  live.location = (locations || []).find(l => l.is_active) || (locations || [])[0] || null;
  await refreshWorkspaceData();
  return live;
}

const DOCUMENT_LABELS = { business_license: 'Business license', pharmacy_license: 'Pharmacy license', owner_id: 'Owner ID' };

// Documents and supplier contacts change while the user works, so they are
// reloaded each time the workspace opens. A failed request keeps the last values.
async function refreshWorkspaceData() {
  if (!live || !live.organization) return;
  const orgId = live.organization.organization_id;
  const [documents, orders] = await Promise.allSettled([
    API.organizations.documents(orgId),
    API.purchaseOrders.list({ organization_id: orgId, limit: 100 })
  ]);
  if (documents.status === 'fulfilled') live.documents = documents.value;
  if (orders.status === 'fulfilled') live.contacts = supplierContacts(orders.value.items);
}

// One entry per supplier the pharmacy has ordered from, newest order first.
function supplierContacts(orders) {
  const bySupplier = new Map();
  (orders || []).forEach(o => {
    const entry = bySupplier.get(o.supplier.organization_id);
    if (entry) { entry.orderCount += 1; return; }
    bySupplier.set(o.supplier.organization_id, { supplier: o.supplier, latest: o, orderCount: 1 });
  });
  return [...bySupplier.values()];
}

function resetLive() {
  live = null; accountEmail = ''; profile = { ...SAMPLE_PROFILE }; currentView = 'home';
  resetPhoneVerification();
}

/* -------------------------------------------------------- step 0: account */
$('#account').addEventListener('submit', e => {
  e.preventDefault();
  const form = e.currentTarget, f = form.elements;
  if (f.password.value !== f.confirm.value) { formError('Your passwords do not match.'); f.confirm.focus(); return; }
  formError('');
  busy(form, async () => {
    const email = f.email.value.trim(), password = f.password.value;
    try {
      let signedInExisting = false;
      try {
        // The account form has no name field; the email name is used until
        // the user changes it (PATCH /auth/me).
        await API.auth.register({ name: email.split('@')[0].slice(0, 150) || email, email, password });
      } catch (err) {
        if (err.status !== 409) throw err;
        signedInExisting = true; // already registered: sign in with these details
      }
      try { await API.auth.login(email, password); } catch (err) {
        if (err.status === 401 && signedInExisting) {
          throw new Error('An account with this email already exists. Enter its password to sign in.');
        }
        throw err;
      }
      f.password.value = ''; f.confirm.value = '';
      await loadLive();
      if (live.organization) { openDashboard(); notice('Welcome back. You are signed in.'); return; }
      await continueToPhoneVerification();
    } catch (err) {
      formError(errorText(err));
    }
  });
});

/* --------------------------------------------------------- step 1: verify */
// Mobile number verification by SMS. Every decision is made by the backend;
// this only drives the form. The code is never known to the browser until
// the user types it from the SMS.
const phoneState = { status: null, sentTo: null, resendAt: 0, timer: null };

function resetPhoneVerification() {
  clearInterval(phoneState.timer);
  Object.assign(phoneState, { status: null, sentTo: null, resendAt: 0, timer: null });
  const f = $('#verify').elements;
  f.phone.value = ''; f.code.value = ''; f.code.dispatchEvent(new Event('input'));
  $('#code-area').hidden = true; $('#code-sent').textContent = '';
  renderResend();
  const phone = $('#profile').elements.phone;
  phone.readOnly = false; phone.removeAttribute('title');
}

function useVerifiedPhone(number) {
  if (!number) return;
  const phone = $('#profile').elements.phone;
  phone.value = number; phone.readOnly = true; phone.title = 'Verified by SMS';
}

// After sign-in: verify the phone unless the backend says it is not needed.
async function continueToPhoneVerification() {
  let status = null;
  try {
    const result = await API.auth.phone.status();
    // Only a well-formed answer counts; anything else is "unknown".
    if (result && typeof result.required === 'boolean' && typeof result.verified === 'boolean') status = result;
  } catch (err) {
    if (err.status === 401) throw err;
    // 404 (older backend during a deploy), network error, timeout: unknown.
  }
  phoneState.status = status;
  if (!status) {
    // Unknown is NOT verified: the backend still refuses an unverified
    // pharmacy when verification is required (403), and the profile step
    // then brings the user back here. When it is not required, they continue.
    step(2); return;
  }
  if (status.verified) { useVerifiedPhone(status.verified_phone); step(2); return; }
  if (!status.required) { step(2); return; }
  step(1);
  if (status && !status.sms_available) {
    formError('SMS verification is not available right now. Please try again later or contact ApexRX.');
  }
}

function renderResend() {
  const button = $('#resend-code');
  const left = Math.ceil((phoneState.resendAt - Date.now()) / 1000);
  if (left > 0) { button.disabled = true; button.textContent = `Resend code in ${left}s`; return; }
  button.disabled = false; button.textContent = 'Resend code';
  clearInterval(phoneState.timer); phoneState.timer = null;
}

function startResendCountdown(seconds) {
  phoneState.resendAt = Date.now() + Math.max(0, seconds) * 1000;
  clearInterval(phoneState.timer);
  phoneState.timer = setInterval(renderResend, 1000);
  renderResend();
}

function sessionExpired() { resetLive(); step(0); formError('Your session has expired. Please sign in again.'); }

async function requestCode() {
  const form = $('#verify'), f = form.elements;
  const phone = f.phone.value.trim();
  if (!phone) { formError('Enter your mobile phone number.'); f.phone.focus(); return; }
  if (phoneState.sentTo === phone && phoneState.resendAt > Date.now()) { renderResend(); return; }
  formError('');
  await busy(form, async () => {
    try {
      const sent = await API.auth.phone.sendCode(phone);
      phoneState.sentTo = sent.phone;
      f.phone.value = sent.phone; // the normalized number the SMS went to
      $('#code-area').hidden = false;
      $('#code-sent').textContent = `Code sent to ${sent.phone_masked}. It expires in ${Math.max(1, Math.round(sent.expires_in / 60))} minutes.`;
      f.code.value = ''; f.code.dispatchEvent(new Event('input'));
      startResendCountdown(sent.resend_after);
      f.code.focus();
    } catch (err) {
      if (err.status === 401) { sessionExpired(); return; }
      if (err.status === 429 && err.data && err.data.retry_after) startResendCountdown(err.data.retry_after);
      formError(errorText(err));
    }
  });
  renderResend(); // busy() re-enabled every button; keep the countdown
}

$('#send-code').addEventListener('click', requestCode);
$('#resend-code').addEventListener('click', requestCode);
$('#verify').elements.phone.addEventListener('input', e => {
  // Editing the number after a code was sent means a new code is needed.
  if (phoneState.sentTo && e.target.value.trim() !== phoneState.sentTo) {
    phoneState.sentTo = null; $('#code-area').hidden = true; $('#code-sent').textContent = '';
  }
});

$('#verify').addEventListener('submit', e => {
  e.preventDefault();
  const form = e.currentTarget, f = form.elements;
  if (!phoneState.sentTo) { requestCode(); return; } // Enter in the phone field sends the code
  const code = f.code.value.replace(/\D/g, '');
  if (code.length !== 6) { formError('Enter the 6-digit code from the SMS.'); f.code.focus(); return; }
  formError('');
  busy(form, async () => {
    try {
      const result = await API.auth.phone.verify(phoneState.sentTo, code);
      phoneState.status = { ...(phoneState.status || {}), verified: true, verified_phone: result.verified_phone };
      clearInterval(phoneState.timer);
      useVerifiedPhone(result.verified_phone);
      step(2);
      notice('Your mobile number is verified.');
    } catch (err) {
      if (err.status === 401) { sessionExpired(); return; }
      const reason = err.data && err.data.reason;
      if (['expired', 'too_many_attempts', 'no_active_code'].includes(reason)) {
        f.code.value = ''; f.code.dispatchEvent(new Event('input'));
        phoneState.resendAt = 0; // a new code can be requested now
      }
      formError(errorText(err));
      if (reason === 'incorrect' || reason === 'format') f.code.select();
    }
  }).then(renderResend);
});

/* -------------------------------------------------------- step 2: profile */
function profilePayloads(values) {
  const lat = Number(values.latitude), lng = Number(values.longitude);
  return {
    organization: { name: values.name, phone: values.phone || null, email: accountEmail || null },
    location: {
      name: values.name, address: values.address || null, city: DEFAULT_CITY, phone: values.phone || null,
      latitude: Number.isFinite(lat) ? Number(lat.toFixed(6)) : null,
      longitude: Number.isFinite(lng) ? Number(lng.toFixed(6)) : null
    }
  };
}

async function uploadSelectedDocuments(organizationId) {
  const inputs = [...document.querySelectorAll('#profile input[type=file][data-document-type]')].filter(i => i.files && i.files.length);
  for (const input of inputs) {
    await API.organizations.uploadDocument(organizationId, input.dataset.documentType, input.files[0]);
    input.value = ''; // uploaded: do not send it again if the user comes back to this step
  }
  return inputs.length;
}

async function saveProfile(values) {
  const { organization, location } = profilePayloads(values);
  if (!live.organization) {
    const created = await API.organizations.create({ ...organization, type: 'pharmacy' });
    live.organization = created; live.role = created.my_role;
  } else if (live.role === 'owner' || live.role === 'manager') {
    live.organization = await API.organizations.update(live.organization.organization_id, organization);
  }
  const orgId = live.organization.organization_id;
  if (live.role === 'owner' || live.role === 'manager') {
    live.location = live.location
      ? await API.organizations.updateLocation(orgId, live.location.location_id, location)
      : await API.organizations.createLocation(orgId, location);
    if (await uploadSelectedDocuments(orgId)) live.documents = await API.organizations.documents(orgId);
  }
}

$('#profile').addEventListener('submit', e => {
  e.preventDefault();
  const form = e.currentTarget, f = form.elements;
  const values = {};
  ['name', 'license', 'phone', 'address', 'latitude', 'longitude'].forEach(key => values[key] = f[key].value.trim());
  if (!values.name) { formError('Please enter a pharmacy name.'); return; }
  formError('');
  busy(form, async () => {
    if (live) {
      try { await saveProfile(values); } catch (err) {
        if (err.status === 401) { resetLive(); step(0); formError('Your session has expired. Please sign in again.'); return; }
        if (err.status === 403 && !live.organization && !(phoneState.status && phoneState.status.verified)) {
          // The backend requires a verified phone first: go to that step.
          step(1); formError(errorText(err)); return;
        }
        formError(errorText(err)); return;
      }
    }
    Object.assign(profile, values);
    step(3);
  });
});

document.querySelectorAll('[data-back]').forEach(b => b.addEventListener('click', () => step(Number(b.dataset.back))));
$('#location-map').addEventListener('click', e => {
  const rect = e.currentTarget.getBoundingClientRect();
  const x = e.detail === 0 ? .5 : Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
  const y = e.detail === 0 ? .5 : Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height));
  $('#location-pin').style.left = `${x * 100}%`; $('#location-pin').style.top = `${y * 100}%`;
  $('#profile').elements.latitude.value = (-1.88 - y * .13).toFixed(4);
  $('#profile').elements.longitude.value = (29.98 + x * .17).toFixed(4);
});

function fillProfileForm() {
  if (!live || !live.organization) return;
  const f = $('#profile').elements, p = profileFromLive();
  f.name.value = p.name;
  if (p.phone !== '—') f.phone.value = p.phone;
  if (p.address !== '—') f.address.value = p.address;
  if (p.latitude !== '—') { f.latitude.value = p.latitude; f.longitude.value = p.longitude; }
}

/* ------------------------------------------------------ step 3: plan/pay */
document.querySelectorAll('[name=method]').forEach(r => r.addEventListener('change', () => $('#payment-method').textContent = r.value));

/* -------------------------------------------------------------- dashboard */
// Show live text in a static element, remembering its sample text so the
// "Just exploring?" preview can restore it.
function setLiveText(el, liveText) {
  if (!el) return;
  if (el.dataset.sample === undefined) el.dataset.sample = el.textContent;
  el.textContent = liveText == null ? el.dataset.sample : liveText;
}

function paintWorkspace() {
  const isLive = !!(live && live.organization);
  const count = isLive ? (live.contacts || []).length : 0;
  const card = $('.overview-cards [data-view=chat]');
  setLiveText(card && card.querySelector('strong'), isLive ? `${count} supplier conversation${count === 1 ? '' : 's'}` : null);
  setLiveText(card && card.querySelector('small'), isLive ? 'Review your supplier orders and contacts →' : null);
  setLiveText($('.panel-heading .demo'), isLive ? 'Live data' : null);
  setLiveText($('.dash-top .avatar'), isLive ? initials(live.organization.name) : null);
  setLiveText($('.dashboard-body > .note'), isLive ? LIVE_PANEL_NOTE : null);
}

function openDashboard() {
  if (live && live.organization) profile = { ...profile, ...profileFromLive() };
  $('#onboarding').hidden = true; $('#dashboard').hidden = false;
  $('#pharmacy-name').textContent = profile.name;
  $('#today').textContent = new Date().toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
  paintWorkspace();
  view('home');
  window.scrollTo(0, 0);
}

$('#payment').addEventListener('submit', e => { e.preventDefault(); openDashboard(); notice('Demo subscription activated. No payment was taken.'); });
$('#explore').addEventListener('click', () => {
  if (live && live.organization) { openDashboard(); return; }
  resetLive(); openDashboard();
});
$('#restart').addEventListener('click', () => {
  if (live) API.auth.logout();
  resetLive();
  $('#dashboard').hidden = true; $('#onboarding').hidden = false; step(0);
});
window.addEventListener('apexrx:signed-out', () => {
  if (!live) return;
  resetLive();
  $('#dashboard').hidden = true; $('#onboarding').hidden = false; step(0);
  formError('Your session has expired. Please sign in again.');
});

/* Sample suppliers, used only when previewing without an account. */
const suppliers = [{ name: 'PharmaRwanda Wholesale', initials: 'PR', medicine: 'Amoxicillin 500mg', message: 'Sample conversation: request a price quote for Amoxicillin 500mg.' }, { name: 'Kigali Medical Wholesalers', initials: 'KM', medicine: 'Paracetamol 500mg', message: 'Sample conversation: discuss delivery options for Paracetamol 500mg.' }, { name: 'AfriPharma Supply', initials: 'AP', medicine: 'Insulin Glargine', message: 'Sample conversation: ask about Insulin Glargine availability.' }];

function initials(name) { return String(name || '?').split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join(''); }
// "Amoxil 250mg" + "250mg" -> "Amoxil 250mg" (catalogue names often include the strength).
function productLabel(o) {
  const name = o.product_name || o.drug_name || '';
  return o.strength && !name.toLowerCase().includes(String(o.strength).toLowerCase()) ? `${name} ${o.strength}` : name;
}
function formatPrice(amount, currency) {
  const n = Number(amount);
  try { return new Intl.NumberFormat('en-GB', { style: 'currency', currency: currency || 'RWF', maximumFractionDigits: 2 }).format(n); } catch (e) { return `${currency} ${n}`; }
}

function supplierRow(name, medicineText, buttonLabel, onClick, ariaLabel) {
  const row = document.createElement('div'); row.className = 'supplier-row';
  const icon = document.createElement('span'); icon.className = 'initials'; icon.textContent = initials(name);
  const details = document.createElement('div');
  const strong = document.createElement('strong'); strong.textContent = name;
  const med = document.createElement('small'); med.textContent = medicineText;
  details.append(strong, med);
  const button = document.createElement('button'); button.textContent = buttonLabel;
  if (ariaLabel) button.setAttribute('aria-label', ariaLabel);
  if (onClick) button.addEventListener('click', onClick); else button.disabled = true;
  row.append(icon, details, button);
  return row;
}

function renderSampleSuppliers() {
  const q = $('#supplier-search').value.toLowerCase().trim();
  const container = $('#suppliers'); container.replaceChildren();
  suppliers.filter(s => (s.name + ' ' + s.medicine).toLowerCase().includes(q)).forEach(s => {
    container.append(supplierRow(s.name, s.medicine + ' · Sample supplier', 'Open chat ↗', () => chat(s), `Open demo chat with ${s.name}`));
  });
  if (!container.children.length) container.textContent = 'No sample suppliers match your search.';
}

function contactSupplier(offer) {
  const medicine = productLabel(offer);
  if (offer.whatsapp_url) {
    const text = encodeURIComponent(`Hello ${offer.supplier_name}, ${profile.name} here (via ApexRX Smart). Is ${medicine} available? Listed at ${formatPrice(offer.unit_price, offer.currency)}.`);
    window.open(`${offer.whatsapp_url}${offer.whatsapp_url.includes('?') ? '&' : '?'}text=${text}`, '_blank', 'noopener');
  } else if (offer.phone) {
    location.href = `tel:${offer.phone.replace(/[^\d+]/g, '')}`;
  }
}

const ORDER_STATUS_LABELS = { draft: 'Draft', submitted: 'Awaiting supplier', countered: 'Counteroffer received', accepted: 'Accepted', rejected: 'Rejected', processing: 'Processing', dispatched: 'Dispatched', delivered: 'Delivered', cancelled: 'Cancelled' };

function whatsappLink(phone, text) {
  const digits = String(phone || '').replace(/\D/g, '');
  return digits ? `https://wa.me/${digits}?text=${encodeURIComponent(text)}` : null;
}

function contactRow(contact) {
  const { supplier, latest, orderCount } = contact;
  const total = latest.confirmed_total != null ? latest.confirmed_total : latest.requested_total;
  const parts = [
    `Order #${latest.purchase_order_id}`,
    ORDER_STATUS_LABELS[latest.status] || latest.status,
    formatPrice(total, latest.currency),
    `${latest.item_count} item${latest.item_count === 1 ? '' : 's'}`
  ];
  if (orderCount > 1) parts.push(`${orderCount} orders`);
  const message = `Hello ${supplier.name}, ${profile.name} here (via ApexRX Smart) about purchase order #${latest.purchase_order_id}.`;
  const wa = whatsappLink(supplier.whatsapp_phone, message);
  const onClick = wa ? () => window.open(wa, '_blank', 'noopener')
    : supplier.phone ? () => { location.href = `tel:${supplier.phone.replace(/[^\d+]/g, '')}`; } : null;
  return supplierRow(supplier.name, parts.join(' · '), 'Open chat ↗', onClick, `Contact ${supplier.name} about order ${latest.purchase_order_id}`);
}

let supplierRequest = null, supplierTimer = null;
// Live workspace list:
//  - Overview / Supplier chat: suppliers you have ordered from (GET /purchase-orders),
//    filtered by name as you type, followed by supplier stock matching the search.
//  - Find a source: supplier stock matching the search (GET /supplier-offers).
async function renderLiveSuppliers() {
  const container = $('#suppliers');
  const orgId = live.organization.organization_id;
  const q = $('#supplier-search').value.trim();
  if (supplierRequest) { supplierRequest.abort(); supplierRequest = null; }

  const showContacts = currentView !== 'source';
  const contacts = showContacts
    ? (live.contacts || []).filter(c => !q || c.supplier.name.toLowerCase().includes(q.toLowerCase()))
    : [];
  container.replaceChildren(...contacts.map(contactRow));

  const approved = live.organization.status === 'approved';
  // Supplier search is for approved pharmacies and searches by medicine name.
  if (q.length < 2 || !approved) {
    if (!container.children.length) {
      if (!approved) container.textContent = STATUS_NOTES[live.organization.status] || STATUS_NOTES.pending;
      else if (showContacts && !q) container.textContent = NO_CONTACTS;
      else container.textContent = q ? 'No suppliers match your search.' : SEARCH_HINT;
    }
    return;
  }

  const controller = new AbortController(); supplierRequest = controller;
  const params = { pharmacy_organization_id: orgId, q, sort: 'price', limit: 25 };
  if (live.location && live.location.latitude != null) { params.lat = live.location.latitude; params.lng = live.location.longitude; }
  container.setAttribute('aria-busy', 'true');
  try {
    const page = await API.supplierOffers.search(params, { signal: controller.signal });
    if (supplierRequest !== controller) return;
    page.items.forEach(o => {
      const parts = [productLabel(o), formatPrice(o.unit_price, o.currency), `${o.quantity.toLocaleString('en-GB')} in stock`, o.city || o.location_name];
      if (o.distance_km != null) parts.push(`${o.distance_km.toFixed(1)} km`);
      const canContact = o.whatsapp_url || o.phone;
      container.append(supplierRow(o.supplier_name, parts.filter(Boolean).join(' · '), 'Open chat ↗', canContact ? () => contactSupplier(o) : null, `Contact ${o.supplier_name} about ${o.product_name}`));
    });
    if (!container.children.length) container.textContent = 'No suppliers match your search.';
  } catch (err) {
    if (controller.signal.aborted) return;
    if (!container.children.length) container.textContent = errorText(err);
    else notice(errorText(err));
  } finally {
    if (supplierRequest === controller) { supplierRequest = null; container.removeAttribute('aria-busy'); }
  }
}

function renderSuppliers() {
  if (live && live.organization) {
    clearTimeout(supplierTimer);
    supplierTimer = setTimeout(renderLiveSuppliers, 250); // debounce typing
  } else renderSampleSuppliers();
}

function renderProfile() {
  const dl = document.createElement('dl');
  const entries = live && live.organization ? profileFromLive() : profile;
  Object.entries(entries).forEach(([key, value]) => {
    const dt = document.createElement('dt'); dt.textContent = key.charAt(0).toUpperCase() + key.slice(1);
    const dd = document.createElement('dd'); dd.textContent = value; dl.append(dt, dd);
  });
  $('#profile-summary').replaceChildren(dl);
  const note = document.createElement('p'); note.className = 'note';
  note.textContent = live && live.organization
    ? (STATUS_NOTES[live.organization.status] || STATUS_NOTES.pending)
    : 'Demo profile only. Your pharmacy has not been published on the patient map.';
  $('#profile-summary').append(note);
}

let currentView = 'home';
function view(name) {
  currentView = name;
  document.querySelectorAll('.sidebar [data-view]').forEach(b => b.classList.toggle('selected', b.dataset.view === name));
  $('#panel-title').textContent = ({ home: 'Recent supplier conversations', source: 'Find a medicine source', chat: 'Your supplier conversations', profile: 'Your pharmacy details' })[name];
  $('#suppliers').hidden = name === 'profile'; $('#search-label').hidden = name === 'profile'; $('#profile-summary').hidden = name !== 'profile';
  if (name === 'profile') renderProfile();
  else {
    $('#supplier-search').value = '';
    if (live && live.organization) $('#suppliers').replaceChildren(); // never show the previous view's rows
    renderSuppliers();
  }
  if (name !== 'home') { $('#panel-title').focus(); $('#panel-title').scrollIntoView({ block: 'center' }); }
}
document.querySelectorAll('[data-view]').forEach(b => b.addEventListener('click', () => view(b.dataset.view)));
$('#supplier-search').addEventListener('input', renderSuppliers);

/* Demo chat dialog (sample suppliers only; live suppliers open WhatsApp). */
const conversations = new Map(); let activeSupplier;
function message(text, own = false) { const p = document.createElement('p'); p.className = 'message' + (own ? ' own' : ''); p.textContent = text; $('#messages').append(p); p.scrollIntoView({ block: 'nearest' }); }
function chat(s) { activeSupplier = s.name; $('#chat-title').textContent = s.name; $('#messages').replaceChildren(); message(s.message); (conversations.get(s.name) || []).forEach(t => message(t, true)); $('#chat-message').value = ''; $('#chat-dialog').showModal(); }
$('#close-dialog').addEventListener('click', () => $('#chat-dialog').close());
$('#chat-form').addEventListener('submit', e => { e.preventDefault(); const text = $('#chat-message').value.trim(); if (!text) return; const history = conversations.get(activeSupplier) || []; history.push(text); conversations.set(activeSupplier, history); message(text, true); $('#chat-message').value = ''; });
$('#premium').addEventListener('click', () => notice('Premium preview: AI forecasting and insurance tools are planned. No upgrade or charge is made.'));

/* ---------------------------------------------------------------- startup */
(async function start() {
  step(0, false);
  if (location.hash === '#signin') $('#account').elements.email.focus();
  if (!API || !API.session.isSignedIn()) return;
  // Resume a session from this tab (for example after a page refresh).
  try {
    await loadLive();
    if (live.organization) openDashboard();
    else await continueToPhoneVerification();
    fillProfileForm();
  } catch (err) {
    resetLive();
    if (err.status !== 401) formError(errorText(err));
  }
})();
