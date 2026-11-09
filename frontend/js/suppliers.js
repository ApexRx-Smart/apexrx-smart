'use strict';
/* Supplier registration (suppliers.html), on the existing ApexRX API (js/api.js).
 *
 * Steps:
 *   0 Account  -> "Create account": POST /auth/register, then POST /auth/login
 *                 (an email that is already registered signs in instead).
 *                 "Sign in" (the switch, or suppliers.html#signin): POST /auth/login.
 *   1 Business -> POST /organizations with type "supplier" (the caller becomes
 *                 its owner and it starts as "pending"), POST .../locations for
 *                 the warehouse, POST .../documents for each selected file.
 *                 Coming back to this step updates the same records (PATCH).
 *   2 Review   -> the organization's real status, warehouses and documents
 *                 (GET /organizations/{id}, /locations, /documents); owners and
 *                 managers can add documents. ApexRX approves it in the admin
 *                 console, as for pharmacies.
 *
 * Suppliers have no SMS step: the backend only requires a verified phone for
 * pharmacies. There are no supplier workspace screens yet.
 */
const $ = s => document.querySelector(s);
const API = window.ApexAPI;
const STEPS = [$('#account'), $('#business'), $('#review')];
const TITLES = ['Create your supplier account', 'Tell us about your business.', 'Your registration'];
const DESCRIPTIONS = [
  'Join a connected network of pharmacies and suppliers in Kigali.',
  'Add your business details, your warehouse and your verification documents.',
  'ApexRX reviews every supplier before it can work with pharmacies.'
];
const STATUS_NOTES = {
  pending: 'Your business is awaiting verification by ApexRX.',
  approved: 'Your business is verified. It can publish stock and prices and receive orders from pharmacies.',
  rejected: 'Your registration was not approved. Update your details and documents, then contact ApexRX to resubmit.',
  suspended: 'Your business is suspended. Contact ApexRX for help.'
};
const DOCUMENT_LABELS = { business_license: 'Business license', owner_id: 'Owner ID', pharmacy_license: 'Pharmacy license' };
const DEFAULT_CITY = 'Kigali';
const ORG_KEY = 'apexrx_selected_supplier';

let live = null; // { user, membership, organization, locations, documents }
let authMode = location.hash === '#signin' ? 'signin' : 'create';
let noticeTimer;

function notice(text) { $('#notice').textContent = text; clearTimeout(noticeTimer); noticeTimer = setTimeout(() => { $('#notice').textContent = ''; }, 7000); }
function formError(text) { $('#form-error').textContent = text || ''; }
function errorText(err) { return (err && err.message) || 'Something went wrong. Please try again.'; }

function step(index, focus = true) {
  STEPS.forEach((el, i) => { el.hidden = i !== index; });
  document.querySelectorAll('.steps li').forEach((li, i) => {
    li.classList.toggle('active', i === index); li.classList.toggle('done', i < index);
    if (i === index) li.setAttribute('aria-current', 'step'); else li.removeAttribute('aria-current');
  });
  $('#step-caption').textContent = `STEP 0${index + 1} / 03`;
  $('#step-title').textContent = TITLES[index];
  $('#step-description').textContent = DESCRIPTIONS[index];
  formError('');
  if (focus) $('#step-title').focus();
}

// Disable a form's buttons while a request runs (no double submissions).
async function busy(form, task) {
  if (form.dataset.busy === 'true') return;
  const buttons = [...form.querySelectorAll('button')];
  form.dataset.busy = 'true'; form.setAttribute('aria-busy', 'true');
  buttons.forEach(b => { b.disabled = true; });
  try { await task(); } finally {
    form.dataset.busy = 'false'; form.removeAttribute('aria-busy');
    buttons.forEach(b => { b.disabled = false; });
  }
}

function sessionExpired() { live = null; setAuthMode('signin'); step(0); formError('Your session has expired. Please sign in again.'); }

/* ------------------------------------------------------------- live state */
function supplierMemberships(me) { return (me.memberships || []).filter(m => m.organization_type === 'supplier'); }
function chosenMembership(me) {
  const list = supplierMemberships(me);
  let saved = null;
  try { saved = sessionStorage.getItem(ORG_KEY); } catch (e) { /* storage unavailable */ }
  return list.find(m => String(m.organization_id) === saved) || list[0] || null;
}

async function loadLive() {
  const me = await API.auth.me();
  const membership = chosenMembership(me);
  const next = { user: me, membership, organization: null, locations: [], documents: [] };
  if (membership) {
    const id = membership.organization_id;
    const [organization, locations, documents] = await Promise.all([
      API.organizations.get(id),
      API.organizations.locations(id, { include_inactive: true }),
      API.organizations.documents(id)
    ]);
    Object.assign(next, { organization, locations: locations || [], documents: documents || [] });
  }
  live = next;
  return live;
}

/* -------------------------------------------------------- step 0: account */
const AUTH_TEXT = {
  create: {
    title: TITLES[0], description: DESCRIPTIONS[0], submit: 'Create account', note: 'Your account is created on ApexRX Smart.',
    switchText: 'Already have an account?', switchButton: 'Sign in'
  },
  signin: {
    title: 'Sign in to ApexRX', description: 'Welcome back. Use the email and password of your ApexRX account.', submit: 'Sign in',
    note: 'Signing in shows your supplier registration.', switchText: 'New to ApexRX?', switchButton: 'Create a supplier account'
  }
};
function setAuthMode(mode, focus) {
  authMode = mode;
  const text = AUTH_TEXT[mode], f = $('#account').elements, signin = mode === 'signin';
  TITLES[0] = text.title; DESCRIPTIONS[0] = text.description;
  $('#confirm-field').hidden = signin;
  $('#confirm-field').parentElement.classList.toggle('single', signin); // password uses the full width
  f.confirm.required = !signin;
  f.confirm.value = '';
  f.password.setAttribute('autocomplete', signin ? 'current-password' : 'new-password');
  if (signin) f.password.removeAttribute('minlength'); else f.password.setAttribute('minlength', '8');
  f.password.placeholder = signin ? 'Your password' : 'At least 8 characters';
  $('#account-submit').firstChild.nodeValue = text.submit + ' ';
  $('#account-note').textContent = text.note;
  $('#auth-switch-text').textContent = text.switchText;
  $('#auth-switch').textContent = text.switchButton;
  if (!STEPS[0].hidden) { $('#step-title').textContent = text.title; $('#step-description').textContent = text.description; formError(''); }
  try { history.replaceState(null, '', location.pathname + location.search + (signin ? '#signin' : '')); } catch (e) { /* ignore */ }
  if (focus) (f.email.value ? f.password : f.email).focus();
}
$('#auth-switch').addEventListener('click', () => setAuthMode(authMode === 'signin' ? 'create' : 'signin', true));

async function afterSignIn() {
  await loadLive();
  if (live.organization) { showReview(); notice('Welcome back. You are signed in.'); return; }
  fillBusinessForm();
  step(1);
}

$('#account').addEventListener('submit', e => {
  e.preventDefault();
  const form = e.currentTarget, f = form.elements;
  const email = f.email.value.trim(), password = f.password.value;
  if (!email || !password) { formError('Enter your email and password.'); return; }
  if (authMode === 'create') {
    if (password.length < 8) { formError('Use at least 8 characters for your password.'); f.password.focus(); return; }
    if (password !== f.confirm.value) { formError('Your passwords do not match.'); f.confirm.focus(); return; }
  }
  formError('');
  busy(form, async () => {
    try {
      if (authMode === 'signin') {
        try { await API.auth.login(email, password); } catch (err) {
          if (err.status === 401) throw new Error('Incorrect email or password.');
          throw err;
        }
      } else {
        let existing = false;
        try {
          // The account form has no name field; the email name is used until
          // the user changes it (PATCH /auth/me), as on the pharmacy page.
          await API.auth.register({ name: email.split('@')[0].slice(0, 150) || email, email, password });
        } catch (err) {
          if (err.status !== 409) throw err;
          existing = true; // already registered: sign in with these details
        }
        try { await API.auth.login(email, password); } catch (err) {
          if (err.status === 401 && existing) throw new Error('An account with this email already exists. Enter its password to sign in.');
          throw err;
        }
      }
      f.password.value = ''; f.confirm.value = '';
      await afterSignIn();
    } catch (err) {
      formError(errorText(err));
    }
  });
});

/* ------------------------------------------------------- step 1: business */
function fillBusinessForm() {
  const f = $('#business').elements;
  if (!live || !live.organization) return;
  const o = live.organization, l = live.locations.find(x => x.is_active) || live.locations[0];
  f.name.value = o.name || '';
  f.phone.value = o.phone || '';
  if (l) {
    f.warehouse.value = l.name || '';
    f.address.value = l.address || '';
    if (l.latitude != null && l.longitude != null) { f.latitude.value = l.latitude; f.longitude.value = l.longitude; }
  }
}

$('#location-map').addEventListener('click', e => {
  const rect = e.currentTarget.getBoundingClientRect();
  const x = e.detail === 0 ? 0.5 : Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
  const y = e.detail === 0 ? 0.5 : Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height));
  $('#location-pin').style.left = `${x * 100}%`; $('#location-pin').style.top = `${y * 100}%`;
  $('#business').elements.latitude.value = (-1.88 - y * 0.13).toFixed(4);
  $('#business').elements.longitude.value = (29.98 + x * 0.17).toFixed(4);
});

function canManage() { return live && live.membership && ['owner', 'manager'].includes(live.membership.role); }

async function uploadSelectedDocuments(organizationId) {
  const inputs = [...document.querySelectorAll('#business input[type=file][data-document-type]')].filter(i => i.files && i.files.length);
  for (const input of inputs) {
    await API.organizations.uploadDocument(organizationId, input.dataset.documentType, input.files[0]);
    input.value = ''; // uploaded: not sent again if the user comes back to this step
  }
}

$('#business').addEventListener('submit', e => {
  e.preventDefault();
  const form = e.currentTarget, f = form.elements;
  const values = {
    name: f.name.value.trim(), phone: f.phone.value.trim(), warehouse: f.warehouse.value.trim(),
    address: f.address.value.trim(), latitude: Number(f.latitude.value), longitude: Number(f.longitude.value)
  };
  if (!values.name) { formError('Enter your business name.'); f.name.focus(); return; }
  if (!values.warehouse) { formError('Enter a name for your warehouse.'); f.warehouse.focus(); return; }
  if (!values.address) { formError('Enter the warehouse address.'); f.address.focus(); return; }
  if (!Number.isFinite(values.latitude) || !Number.isFinite(values.longitude) || f.latitude.value === '' || f.longitude.value === '') {
    formError('Pin the warehouse on the map or enter its coordinates.'); f.latitude.focus(); return;
  }
  formError('');
  busy(form, async () => {
    try {
      const organization = { name: values.name, phone: values.phone || null };
      if (!live.organization) {
        // The organization type decides everything: this is a supplier.
        live.organization = await API.organizations.create({ ...organization, type: 'supplier', email: live.user.email || null });
        live.membership = { organization_id: live.organization.organization_id, role: live.organization.my_role || 'owner' };
        try { sessionStorage.setItem(ORG_KEY, String(live.organization.organization_id)); } catch (err) { /* storage unavailable */ }
      } else if (canManage()) {
        live.organization = await API.organizations.update(live.organization.organization_id, organization);
      }
      const id = live.organization.organization_id;
      if (canManage()) {
        const location = {
          name: values.warehouse, address: values.address, city: DEFAULT_CITY, phone: values.phone || null,
          latitude: Number(values.latitude.toFixed(6)), longitude: Number(values.longitude.toFixed(6))
        };
        const current = live.locations.find(x => x.is_active) || live.locations[0];
        if (current) await API.organizations.updateLocation(id, current.location_id, location);
        else await API.organizations.createLocation(id, location);
        await uploadSelectedDocuments(id);
      }
      await loadLive();
      showReview();
      notice('Your supplier registration has been submitted to ApexRX for review.');
    } catch (err) {
      if (err.status === 401) { sessionExpired(); return; }
      formError(errorText(err));
    }
  });
});
$('#business-back').addEventListener('click', () => {
  if (live && live.organization) { showReview(); return; }
  live = null; API.auth.logout(); step(0);
});

/* --------------------------------------------------------- step 2: review */
function renderSupplierSwitch() {
  const list = live && live.user ? supplierMemberships(live.user) : [];
  $('#supplier-switch-label').hidden = list.length < 2;
  $('#supplier-switch').replaceChildren(...list.map(m => {
    const option = document.createElement('option');
    option.value = m.organization_id;
    option.textContent = `${m.organization_name} (${m.role})`;
    option.selected = live.organization && m.organization_id === live.organization.organization_id;
    return option;
  }));
}

function showReview() {
  const o = live.organization;
  step(2, false);
  $('#review-name').textContent = o.name;
  const badge = $('#review-status');
  badge.textContent = o.status;
  badge.className = 'ws-badge status-' + o.status;
  $('#review-note').textContent = STATUS_NOTES[o.status] || '';
  $('#review-role').textContent = live.membership ? live.membership.role : '—';
  $('#review-phone').textContent = o.phone || '—';
  $('#review-locations').textContent = live.locations.length
    ? live.locations.map(l => l.name + (l.address ? ` · ${l.address}` : '') + (l.is_active ? '' : ' (inactive)')).join('\n')
    : 'No warehouse yet';
  const list = $('#review-documents');
  if (!live.documents.length) {
    const li = document.createElement('li'); li.className = 'empty';
    li.textContent = 'No documents uploaded yet. ApexRX needs them to verify your business.';
    list.replaceChildren(li);
  } else {
    list.replaceChildren(...live.documents.map(d => {
      const li = document.createElement('li');
      const name = document.createElement('span');
      name.textContent = `${DOCUMENT_LABELS[d.document_type] || d.document_type}: ${d.file_name}`;
      const status = document.createElement('span');
      status.className = 'ws-badge status-' + d.verification_status;
      status.textContent = d.verification_status;
      li.append(name, status);
      if (d.rejection_reason) {
        const why = document.createElement('small'); why.textContent = d.rejection_reason; li.append(why);
      }
      return li;
    }));
  }
  const manage = canManage();
  $('#review-upload').hidden = !manage;
  $('#review-edit').hidden = !manage;
  renderSupplierSwitch();
  $('#step-title').focus();
}

$('#review-edit').addEventListener('click', () => { fillBusinessForm(); step(1); });
$('#review-refresh').addEventListener('click', async () => {
  const button = $('#review-refresh'); button.disabled = true;
  try { await loadLive(); showReview(); notice('Status updated.'); } catch (err) {
    if (err.status === 401) { sessionExpired(); return; }
    formError(errorText(err));
  } finally { button.disabled = false; }
});
$('#upload-button').addEventListener('click', async () => {
  const file = $('#upload-file').files[0];
  if (!file) { formError('Choose a file to upload.'); return; }
  const button = $('#upload-button'); button.disabled = true; formError('');
  try {
    await API.organizations.uploadDocument(live.organization.organization_id, $('#upload-type').value, file);
    $('#upload-file').value = '';
    await loadLive(); showReview(); notice('Document uploaded for review.');
  } catch (err) {
    if (err.status === 401) { sessionExpired(); return; }
    formError(errorText(err));
  } finally { button.disabled = false; }
});
$('#supplier-switch').addEventListener('change', async e => {
  try { sessionStorage.setItem(ORG_KEY, e.target.value); } catch (err) { /* storage unavailable */ }
  try { await loadLive(); showReview(); } catch (err) { formError(errorText(err)); }
});
$('#review-signout').addEventListener('click', () => { live = null; API.auth.logout(); setAuthMode('signin'); step(0); });

window.addEventListener('apexrx:signed-out', () => {
  if (!live) return;
  sessionExpired();
});

/* ---------------------------------------------------------------- startup */
(async function start() {
  step(0, false);
  setAuthMode(authMode, false);
  if (authMode === 'signin') $('#account').elements.email.focus();
  if (!API || !API.session.isSignedIn()) return;
  // Resume a session from this tab (for example after a refresh, or arriving
  // from the pharmacy page with a supplier account).
  try {
    await loadLive();
    if (live.organization) showReview();
    else { fillBusinessForm(); step(1, false); }
  } catch (err) {
    live = null;
    if (err.status !== 401) formError(errorText(err));
  }
})();
