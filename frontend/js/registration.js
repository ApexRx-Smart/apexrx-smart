'use strict';
/* Registration for pharmacies (pharmacies.html) and suppliers (suppliers.html),
 * on the ApexRX API (js/api.js). The page says which: <body data-role="pharmacy">
 * or <body data-role="supplier">. The organization type sent to the backend
 * comes only from that role.
 *
 * Steps (every decision about progress is read back from the backend, so an
 * incomplete registration resumes where it stopped, on any device):
 *   0 Account   -> "Create account": POST /auth/register, then POST /auth/login
 *                  (an email that is already registered signs in instead).
 *                  "Sign in" (the switch, or #signin): POST /auth/login only.
 *   1 Verify    -> email verification by link: POST /auth/email/send, then the
 *                  user opens the link (verify-email.html). GET /auth/email/status
 *                  says whether it is done. The backend refuses to create an
 *                  organization until the email is verified.
 *   2 Details   -> POST /organizations {type}, then the main branch / warehouse:
 *                  POST .../locations with a structured Rwandan address
 *                  (province -> region, district -> city, sector, cell, village,
 *                  street -> address), contact numbers and optional coordinates.
 *                  Saving again updates the same records (PATCH).
 *   3 Documents -> POST .../documents for each selected file.
 *   4 Review    -> the organization's real status, review notes, details and
 *                  documents; upload more, resubmit after a rejection.
 *                  Pharmacies continue to their workspace (js/pharmacies.js).
 *
 * There is no payment or subscription step. Phone numbers are contact details,
 * never used to verify anyone.
 */
(function () {
  const $ = s => document.querySelector(s);
  const API = window.ApexAPI;
  const ROLE = document.body.dataset.role === 'supplier' ? 'supplier' : 'pharmacy';
  const ORG_KEY = ROLE === 'pharmacy' ? 'apexrx_selected_pharmacy' : 'apexrx_selected_supplier';
  const MAX_FILE = 10 * 1024 * 1024;
  const FILE_TYPES = /\.(pdf|png|jpe?g)$/i;
  // Keys of data/rwanda-locations.json, and the names stored in location.region.
  const PROVINCES = [['Kigali', 'Kigali City'], ['East', 'Eastern Province'], ['West', 'Western Province'], ['North', 'Northern Province'], ['South', 'Southern Province']];
  const RWANDA = { latMin: -2.9, latMax: -1.0, lngMin: 28.8, lngMax: 31.0 };
  const STEP_NAMES = ['Account', 'Verify email', 'Details', 'Documents', 'Review'];

  const T = {
    pharmacy: {
      createTitle: 'Create your pharmacy account', createDesc: 'Join a connected community of pharmacies and suppliers in Kigali.',
      signinNote: 'Signing in opens your pharmacy workspace.', toCreate: 'Create a pharmacy account', emailPh: 'pharmacy@example.com',
      otherHint: 'Registering a medicine supplier?', otherLink: 'Register as a supplier →', otherHref: 'suppliers.html',
      otherAccount: 'This account belongs to a supplier, not a pharmacy.', otherContinue: 'Continue on the supplier page →',
      detailsTitle: 'Make your pharmacy easy to find.', detailsDesc: 'Add your pharmacy’s contact details and the address of its main branch.',
      name: 'Pharmacy name', namePh: 'Kigali Central Pharmacy', place: 'Branch name', placeDefault: 'Main branch',
      address: 'Main branch address', docsTitle: 'Licensing documents', docsDesc: 'Upload the documents ApexRX uses to verify your pharmacy.',
      docs: [['pharmacy_license', 'Pharmacy license'], ['business_license', 'Business license'], ['owner_id', 'Owner ID']],
      reviewDesc: 'ApexRX reviews every pharmacy before it is listed for patients.', type: 'Pharmacy', places: 'Branches',
      geoNote: 'Use your device’s location while you are at the pharmacy, or enter the coordinates. You can leave them empty and add them later.',
      status: {
        pending: 'Your pharmacy is awaiting verification by ApexRX. Supplier search opens once it is approved.',
        approved: 'Your pharmacy is verified. Listed medicines are visible to patients on ApexRX.',
        rejected: 'Your registration was not approved. Correct your details or documents, then resubmit it for review.',
        suspended: 'Your pharmacy is suspended. Contact ApexRX for help.'
      }
    },
    supplier: {
      createTitle: 'Create your supplier account', createDesc: 'Join a connected network of pharmacies and suppliers in Kigali.',
      signinNote: 'Signing in shows your supplier registration.', toCreate: 'Create a supplier account', emailPh: 'depot@example.com',
      otherHint: 'Registering a pharmacy?', otherLink: 'Register as a pharmacy →', otherHref: 'pharmacies.html',
      otherAccount: 'This account belongs to a pharmacy, not a supplier.', otherContinue: 'Continue on the pharmacy page →',
      detailsTitle: 'Tell us about your business.', detailsDesc: 'Add your business contact details and the address of your main warehouse.',
      name: 'Business name', namePh: 'Kigali Medical Supplies Ltd', place: 'Warehouse name', placeDefault: 'Main warehouse',
      address: 'Main warehouse address', docsTitle: 'Verification documents', docsDesc: 'Upload the documents ApexRX uses to verify your business.',
      docs: [['business_license', 'Business license'], ['owner_id', 'Owner ID']],
      reviewDesc: 'ApexRX reviews every supplier before it can work with pharmacies.', type: 'Supplier', places: 'Warehouses',
      geoNote: 'Use your device’s location while you are at the warehouse, or enter the coordinates. You can leave them empty and add them later.',
      status: {
        pending: 'Your business is awaiting verification by ApexRX.',
        approved: 'Your business is verified. It can publish stock and prices and receive orders from pharmacies.',
        rejected: 'Your registration was not approved. Correct your details or documents, then resubmit it for review.',
        suspended: 'Your business is suspended. Contact ApexRX for help.'
      }
    }
  }[ROLE];
  const DOC_LABELS = { pharmacy_license: 'Pharmacy license', business_license: 'Business license', owner_id: 'Owner ID' };
  const STATUS_LABELS = { pending: 'Pending review', approved: 'Approved', rejected: 'Not approved', suspended: 'Suspended' };
  const ROLE_LABELS = { owner: 'Owner', manager: 'Manager', staff: 'Staff' };
  const DOC_STATUS = { pending: 'Awaiting review', approved: 'Approved', rejected: 'Rejected' };

  /* ---------------------------------------------------------------- markup */
  const STEPS_HTML = STEP_NAMES.map(n => `<li>${n}</li>`).join('');
  const FORMS_HTML = `
<form id="account" class="step-form" novalidate>
  ${ROLE === 'pharmacy' ? `<div class="auth-tabs" role="tablist" aria-label="Pharmacy access">
    <button type="button" role="tab" id="tab-create" data-auth-tab="create">Register a pharmacy</button>
    <button type="button" role="tab" id="tab-signin" data-auth-tab="signin">Staff sign-in</button>
  </div>` : ''}
  <label>Email address<input name="email" type="email" autocomplete="email" placeholder="${T.emailPh}" required></label>
  <div class="fields"><label>Password<input name="password" type="password" autocomplete="new-password" minlength="8" placeholder="At least 8 characters" required></label><label id="confirm-field">Confirm password<input name="confirm" type="password" autocomplete="new-password" minlength="8" placeholder="Re-enter your password" required></label></div>
  <p class="note" id="account-note">Your account is created on ApexRX Smart.</p>
  <p class="forgot-row" id="forgot-row" hidden><a href="reset-password.html?next=${ROLE}" id="forgot-link">Forgot password?</a></p>
  <button class="primary" id="account-submit">Create account <span>→</span></button>
  <p class="auth-switch"><span id="auth-switch-text">Already have an account?</span> <button type="button" class="text-button" id="auth-switch">Sign in</button></p>
  <p class="role-hint" id="other-hint">${T.otherHint} <a href="${T.otherHref}">${T.otherLink}</a></p>
  ${ROLE === 'pharmacy' ? '<button type="button" class="text-button" id="explore">Just exploring? Preview the workspace ↗</button>' : ''}
</form>

<form id="verify-email" class="step-form" hidden novalidate>
  <div class="mail-icon" aria-hidden="true">✉</div>
  <p class="verify-to"><span>Verification link for</span> <strong id="verify-address"></strong></p>
  <p id="verify-state" class="note" role="status"></p>
  <p id="verify-expiry-row" class="note" hidden><span>The link is valid until</span> <strong id="verify-expiry"></strong></p>
  <div class="actions">
    <button type="button" class="secondary" id="resend-email">Send verification email</button>
    <button class="primary" id="check-email">I’ve verified my email <span>→</span></button>
  </div>
  <p class="note">Open the link from the email on any device. It works once. If it does not arrive within a few minutes, check your spam folder or send a new one.</p>
</form>

<form id="details" class="step-form" hidden novalidate>
  <div class="fields">
    <label>${T.name}<input name="name" maxlength="255" placeholder="${T.namePh}" autocomplete="organization" required></label>
    <label>Business phone<input name="phone" type="tel" inputmode="tel" autocomplete="tel" maxlength="30" placeholder="078 812 3456" required></label>
    <label>${T.place}<input name="place" maxlength="255" placeholder="${T.placeDefault}" required></label>
    <label>WhatsApp number (optional)<input name="whatsapp" type="tel" inputmode="tel" maxlength="30" placeholder="078 812 3456"></label>
  </div>
  <p class="note">Phone numbers are for contacting your business, and later for Mobile Money payments. They are not used to verify your account.</p>
  <strong class="document-heading">${T.address} <small>Rwanda</small></strong>
  <div class="fields address-fields" id="address-fields"></div>
  <label>Street or landmark (optional)<input name="street" maxlength="500" placeholder="KG 11 Ave, near the market"></label>
  <p class="note address-summary" id="address-summary" hidden><span>Address</span>: <span id="address-text"></span></p>
  <strong class="document-heading">Map location <small>Optional</small></strong>
  <div class="geo-row"><button type="button" class="secondary" id="use-location">Use my current location</button><a id="map-check" href="#" target="_blank" rel="noopener" hidden>Check on OpenStreetMap ↗</a></div>
  <div class="fields coordinates"><label>Latitude<input name="latitude" type="number" step="any" min="-90" max="90" inputmode="decimal" placeholder="-1.9441"></label><label>Longitude<input name="longitude" type="number" step="any" min="-180" max="180" inputmode="decimal" placeholder="30.0619"></label></div>
  <p class="note">${T.geoNote}</p>
  <div class="actions"><button type="button" class="secondary" id="details-back">← Back</button><button class="primary" id="details-submit">Save and continue →</button></div>
</form>

<form id="documents" class="step-form" hidden novalidate>
  <ul class="doc-list" id="doc-list"></ul>
  <p class="note">PDF, PNG or JPG, up to 10 MB each. Only ApexRX reviewers and members of your organization can open them.</p>
  <div class="actions"><button type="button" class="secondary" id="documents-back">← Back</button><button class="primary" id="documents-submit">Continue to review →</button></div>
</form>

<div id="review" class="step-form" hidden>
  <div class="supplier-status">
    <div class="status-head"><strong id="review-name"></strong><span class="ws-badge" id="review-status"></span></div>
    <p id="review-note" class="note"></p>
    <p id="review-notes-row" class="review-notes" hidden><span>Note from ApexRX</span>: <span id="review-notes"></span></p>
    <dl class="supplier-facts" id="review-facts"></dl>
    <strong class="document-heading">Verification documents</strong>
    <ul id="review-documents" class="supplier-docs"></ul>
    <div id="review-upload" class="uploads review-upload" hidden>
      <label>Add a document<select id="upload-type" aria-label="Document type">${T.docs.map(([k, l]) => `<option value="${k}">${l}</option>`).join('')}</select></label>
      <label>File<input type="file" id="upload-file" accept=".pdf,.png,.jpg,.jpeg"></label>
      <button type="button" class="secondary" id="upload-button">Upload document</button>
    </div>
    ${ROLE === 'supplier' ? '<p class="note">Supplier screens for stock, prices and incoming orders are not on the website yet.</p>' : ''}
  </div>
  <label id="org-pick-label" class="org-pick" hidden>${T.type}<select id="org-pick"></select></label>
  <div class="actions">
    <button type="button" class="secondary" id="review-edit">Edit details</button>
    <button type="button" class="secondary" id="review-refresh">Check status</button>
    <button type="button" class="secondary" id="review-resubmit" hidden>Resubmit for review</button>
    ${ROLE === 'pharmacy' ? '<button type="button" class="primary" id="open-workspace">Open your workspace →</button>' : ''}
  </div>
</div>

<div id="org-choice" class="step-form" hidden>
  <ul class="org-choice-list" id="org-choice-list"></ul>
  <p class="note">You can switch pharmacy at any time from your workspace.</p>
</div>

<div id="account-panel" class="step-form" hidden>
  <p id="account-panel-text"></p>
  <p><a id="account-panel-link" class="panel-link" href="#"></a></p>
</div>

${ROLE === 'pharmacy' ? `<div id="join-wait" class="step-form" hidden>
  <p>Your ApexRX account <strong id="join-email"></strong> is ready.</p>
  <p class="note">To work in an existing pharmacy, ask its owner or a manager to invite this email address (Employees → Invite an employee). You will receive an email with a link to join; open it, then choose “Check again”. You do not need to register a pharmacy yourself.</p>
  <p id="join-status" role="status" class="note"></p>
  <div class="actions"><button type="button" class="primary" id="join-check">Check again</button><button type="button" class="secondary" id="join-register">Register a new pharmacy instead</button></div>
</div>
<button type="button" class="text-button" id="join-existing" hidden>Joining an existing pharmacy instead? →</button>` : ''}`;

  $('.steps').innerHTML = STEPS_HTML;
  $('#registration').innerHTML = FORMS_HTML;
  const PANELS = ['#account', '#verify-email', '#details', '#documents', '#review'].map(s => $(s));
  const EXTRA_PANELS = ['#account-panel', '#join-wait', '#org-choice'].map(s => $(s)).filter(Boolean);

  /* ------------------------------------------------------------ utilities */
  let noticeTimer;
  function notice(text) { const n = $('#notice'); n.textContent = text; clearTimeout(noticeTimer); noticeTimer = setTimeout(() => { n.textContent = ''; }, 7000); }
  function formError(text) { $('#form-error').textContent = text || ''; }
  function errorText(err) { return (err && err.message) || 'Something went wrong. Please try again.'; }
  function el(tag, props, children) {
    const node = document.createElement(tag);
    Object.entries(props || {}).forEach(([k, v]) => { if (k === 'text') node.textContent = v; else if (k === 'class') node.className = v; else node.setAttribute(k, v); });
    (children || []).forEach(c => node.append(c));
    return node;
  }
  function fmtDate(iso) {
    try { return new Date(iso).toLocaleString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }); } catch (e) { return iso; }
  }
  function fmtSize(bytes) { return bytes >= 1048576 ? (bytes / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(bytes / 1024)) + ' KB'; }

  let titles = [T.createTitle, 'Verify your email address.', T.detailsTitle, T.docsTitle, 'Your registration'];
  let descriptions = [T.createDesc, 'We email you a link to confirm that this address is yours.', T.detailsDesc, T.docsDesc, T.reviewDesc];
  let current = 0;

  function show(index, focus = true) {
    current = index;
    PANELS.forEach((p, i) => { p.hidden = i !== index; });
    EXTRA_PANELS.forEach(p => { p.hidden = true; });
    document.querySelectorAll('.steps li').forEach((li, i) => {
      li.classList.toggle('active', i === index); li.classList.toggle('done', i < index);
      if (i === index) li.setAttribute('aria-current', 'step'); else li.removeAttribute('aria-current');
    });
    $('#step-caption').textContent = `STEP 0${index + 1} / 0${STEP_NAMES.length}`;
    $('#step-title').textContent = titles[index];
    $('#step-description').textContent = descriptions[index];
    formError('');
    const join = $('#join-existing');
    if (join) join.hidden = !(reg && !reg.membership && (index === 1 || index === 2));
    if (index !== 1) stopEmailWatch();
    if (focus) $('#step-title').focus();
  }
  function showPanel(panel, title, description) {
    PANELS.forEach(p => { p.hidden = true; });
    EXTRA_PANELS.forEach(p => { p.hidden = p !== panel; });
    const join = $('#join-existing'); if (join) join.hidden = true;
    $('#step-caption').textContent = '';
    $('#step-title').textContent = title;
    $('#step-description').textContent = description;
    formError('');
    stopEmailWatch();
    $('#step-title').focus();
  }

  // Disable a form's buttons while a request runs, so it is never sent twice.
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

  /* --------------------------------------------------------- live state */
  let reg = null; // { me, membership, org, locations, location, documents }
  const canManage = () => !!(reg && reg.membership && (reg.membership.role === 'owner' || reg.membership.role === 'manager'));

  function myMemberships(me) { return (me.memberships || []).filter(m => m.organization_type === ROLE); }
  function chosenMembership(me) {
    const list = myMemberships(me);
    let saved = null;
    try { saved = sessionStorage.getItem(ORG_KEY); } catch (e) { /* storage unavailable */ }
    return list.find(m => String(m.organization_id) === saved) || list.find(m => m.role === 'owner') || list[0] || null;
  }
  function remember(orgId) { try { sessionStorage.setItem(ORG_KEY, String(orgId)); } catch (e) { /* storage unavailable */ } }

  async function load() {
    const me = await API.auth.me();
    const membership = chosenMembership(me);
    const next = { me, membership, org: null, locations: [], location: null, documents: [] };
    if (membership) {
      const id = membership.organization_id;
      const [org, locations, documents] = await Promise.all([
        API.organizations.get(id),
        API.organizations.locations(id, { include_inactive: true }),
        API.organizations.documents(id).catch(() => [])
      ]);
      Object.assign(next, { org, locations: locations || [], documents: documents || [] });
      next.location = next.locations.find(l => l.is_active) || next.locations[0] || null;
    }
    reg = next;
    paintSignedIn();
    return reg;
  }

  function paintSignedIn() {
    const box = $('#signed-in-as');
    box.hidden = !reg;
    $('#signed-in-email').textContent = reg ? reg.me.email : '';
  }

  let signingOut = false;
  function signOut() {
    signingOut = true;
    reg = null; resetEmailState();
    API.auth.logout();
    signingOut = false;
    reset();
  }

  function reset(message) {
    reg = null; resetEmailState(); paintSignedIn();
    $('#onboarding').hidden = false;
    const dash = $('#dashboard'); if (dash) dash.hidden = true;
    setAuthMode('signin', false);
    show(0, false);
    if (message) formError(message);
  }
  function sessionExpired() { reset('Your session has expired. Please sign in again.'); }
  function signedOutText(detail) {
    const reason = detail && detail.reason;
    if (reason === 'idle') return `You were signed out after ${(detail && detail.idleMinutes) || 30} minutes of inactivity. Sign in again to continue.`;
    if (reason === 'other_tab') return 'You signed out in another tab.';
    if (reason === 'signed_out') return '';
    if (reason === 'revoked') return 'Your session has ended. Please sign in again.';
    return 'Your session has expired. Please sign in again.';
  }

  // Decide where the signed-in user continues, from the backend's state.
  async function route(opts = {}) {
    await load();
    if (!reg.membership) {
      const other = (reg.me.memberships || []).find(m => m.organization_type !== ROLE);
      if (other) return accountPanel(T.otherAccount, T.otherContinue, T.otherHref);
      if (reg.me.is_platform_admin) {
        return accountPanel('You are signed in as an ApexRX administrator. Administrators do not register here. Sign out to use another account.', 'Open the admin console →', 'admin.html');
      }
      const status = await emailStatus();
      if (status && status.required && !status.verified) return showVerify();
      return showDetails();
    }
    // Several pharmacies: the user chooses (after signing in, or when this tab
    // has no choice yet). Only memberships the backend returned are offered.
    const mine = myMemberships(reg.me);
    if (ROLE === 'pharmacy' && mine.length > 1 && !opts.review && (opts.choose || !savedChoice())) return showOrgChoice(mine);
    if (canManage() && !reg.location) return showDetails();
    if (ROLE === 'pharmacy' && !opts.review) {
      const needsDocuments = canManage() && !reg.documents.length && ['pending', 'rejected'].includes(reg.org.status);
      if (!needsDocuments) return openWorkspace();
    }
    return showReview();
  }

  function savedChoice() {
    try { return sessionStorage.getItem(ORG_KEY); } catch (e) { return null; }
  }
  function showOrgChoice(list) {
    showPanel($('#org-choice'), 'Choose a pharmacy', 'Your account belongs to several pharmacies. Which one do you want to work in?');
    $('#org-choice-list').replaceChildren(...list.map(m => {
      const button = el('button', { type: 'button', class: 'org-choice', 'data-org': String(m.organization_id) }, [
        el('strong', { text: m.organization_name }),
        el('span', { class: 'org-choice-meta' }, [
          el('span', { text: ROLE_LABELS[m.role] || m.role }), document.createTextNode(' · '),
          el('span', { text: STATUS_LABELS[m.organization_status] || m.organization_status })
        ])
      ]);
      button.addEventListener('click', reviewAction(button, async () => {
        remember(m.organization_id);
        await route();
      }));
      return el('li', {}, [button]);
    }));
  }

  function accountPanel(text, linkText, href) {
    showPanel($('#account-panel'), 'Signed in to ApexRX', '');
    $('#account-panel-text').textContent = text;
    const link = $('#account-panel-link'); link.textContent = linkText; link.href = href;
  }

  async function openWorkspace() {
    if (!window.ApexPharmacyWorkspace) return showReview();
    await window.ApexPharmacyWorkspace.open();
  }

  /* -------------------------------------------------------- step 0: account */
  let authMode = (location.hash === '#signin' || location.hash === '#staff') ? 'signin' : 'create';
  const AUTH_TEXT = {
    create: { title: T.createTitle, description: T.createDesc, submit: 'Create account', note: 'Your account is created on ApexRX Smart.', switchText: 'Already have an account?', switchButton: 'Sign in' },
    signin: ROLE === 'pharmacy'
      ? { title: 'Staff sign-in', description: 'Already working at a pharmacy registered on ApexRX? Sign in with your personal account to open your pharmacy workspace.', submit: 'Sign in', note: 'Owners, managers and staff each sign in with their own account. Never share passwords.', switchText: 'New to ApexRX?', switchButton: T.toCreate }
      : { title: 'Sign in to ApexRX', description: 'Welcome back. Use the email and password of your ApexRX account.', submit: 'Sign in', note: T.signinNote, switchText: 'New to ApexRX?', switchButton: T.toCreate }
  };
  function setAuthMode(mode, focus) {
    authMode = mode;
    const text = AUTH_TEXT[mode], f = $('#account').elements, signin = mode === 'signin';
    titles[0] = text.title; descriptions[0] = text.description;
    $('#confirm-field').hidden = signin;
    $('#confirm-field').parentElement.classList.toggle('single', signin);
    f.confirm.required = !signin; f.confirm.value = '';
    f.password.setAttribute('autocomplete', signin ? 'current-password' : 'new-password');
    if (signin) f.password.removeAttribute('minlength'); else f.password.setAttribute('minlength', '8');
    f.password.placeholder = signin ? 'Your password' : 'At least 8 characters';
    $('#account-submit').firstChild.nodeValue = text.submit + ' ';
    $('#account-note').textContent = text.note;
    $('#auth-switch-text').textContent = text.switchText;
    $('#auth-switch').textContent = text.switchButton;
    $('#forgot-row').hidden = !signin;
    // A link to #signin / #staff on this page switches to sign-in (no reload).
  window.addEventListener('hashchange', () => {
    const wanted = (location.hash === '#signin' || location.hash === '#staff') ? 'signin' : null;
    if (wanted && authMode !== wanted && !$('#account').hidden) setAuthMode(wanted, true);
  });
  document.querySelectorAll('[data-auth-tab]').forEach(tab => {
      const on = tab.dataset.authTab === mode;
      tab.classList.toggle('active', on); tab.setAttribute('aria-selected', String(on)); tab.tabIndex = on ? 0 : -1;
    });
    if (!$('#account').hidden) { $('#step-title').textContent = text.title; $('#step-description').textContent = text.description; formError(''); }
    try { history.replaceState(null, '', location.pathname + location.search + (signin ? '#signin' : '')); } catch (e) { /* ignore */ }
    if (focus) (f.email.value ? f.password : f.email).focus();
  }
  $('#auth-switch').addEventListener('click', () => setAuthMode(authMode === 'signin' ? 'create' : 'signin', true));
  document.querySelectorAll('[data-auth-tab]').forEach(tab => {
    tab.addEventListener('click', () => { if (authMode !== tab.dataset.authTab) setAuthMode(tab.dataset.authTab, true); });
    tab.addEventListener('keydown', e => {
      if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
      const other = document.querySelector(`[data-auth-tab="${tab.dataset.authTab === 'create' ? 'signin' : 'create'}"]`);
      other.click(); other.focus();
    });
  });

  $('#account').addEventListener('submit', e => {
    e.preventDefault();
    const form = e.currentTarget, f = form.elements;
    const email = f.email.value.trim(), password = f.password.value;
    if (!email || !password) { formError('Enter your email and password.'); return; }
    if (!/^\S+@\S+\.\S+$/.test(email)) { formError('Enter a valid email address.'); f.email.focus(); return; }
    if (authMode === 'create') {
      if (password.length < 8) { formError('Use at least 8 characters for your password.'); f.password.focus(); return; }
      if (password !== f.confirm.value) { formError('Your passwords do not match.'); f.confirm.focus(); return; }
    }
    formError('');
    busy(form, async () => {
      try {
        let existing = false;
        if (authMode === 'signin') {
          try { await API.auth.login(email, password); } catch (err) {
            if (err.status === 401) throw new Error('Incorrect email or password.');
            throw err;
          }
        } else {
          try {
            // No name field here: the email name is used until the user changes it.
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
        await route({ choose: authMode === 'signin' });
        if (existing) notice('You already had an ApexRX account with this email. You are signed in.');
        else if (authMode === 'signin') notice('Welcome back. You are signed in.');
      } catch (err) {
        if (err.status === 401) { sessionExpired(); return; }
        formError(errorText(err));
      }
    });
  });

  const explore = $('#explore');
  if (explore) explore.addEventListener('click', () => { if (window.ApexPharmacyWorkspace) window.ApexPharmacyWorkspace.preview(); });

  /* --------------------------------------------- step 1: verify the email */
  const emailState = { status: null, resendAt: 0, timer: null, autoSent: false, lastCheck: 0 };
  function resetEmailState() {
    clearInterval(emailState.timer);
    Object.assign(emailState, { status: null, resendAt: 0, timer: null, autoSent: false, lastCheck: 0 });
  }

  async function emailStatus() {
    try {
      const s = await API.auth.email.status();
      emailState.status = (s && typeof s.verified === 'boolean') ? s : null;
    } catch (err) {
      if (err.status === 401) throw err;
      emailState.status = null; // unknown: the backend still refuses an unverified organization (403)
    }
    return emailState.status;
  }

  function setVerifyState(text, expiresAt) {
    $('#verify-state').textContent = text || '';
    $('#verify-expiry-row').hidden = !expiresAt;
    $('#verify-expiry').textContent = expiresAt ? fmtDate(expiresAt) : '';
  }
  function renderResend() {
    const b = $('#resend-email');
    const left = Math.ceil((emailState.resendAt - Date.now()) / 1000);
    if (left > 0) { b.disabled = true; b.textContent = `Resend email in ${left}s`; return; }
    clearInterval(emailState.timer); emailState.timer = null;
    b.disabled = !!(emailState.status && emailState.status.delivery_available === false);
    b.textContent = emailState.status && (emailState.status.pending || emailState.autoSent) ? 'Resend verification email' : 'Send verification email';
  }
  function startCountdown(seconds) {
    emailState.resendAt = Date.now() + Math.max(0, seconds || 0) * 1000;
    clearInterval(emailState.timer);
    emailState.timer = setInterval(renderResend, 1000);
    renderResend();
  }

  async function showVerify() {
    show(1);
    $('#verify-address').textContent = reg.me.email;
    const s = emailState.status || await emailStatus();
    watchEmail();
    if (!s) { setVerifyState('Send a verification email to continue.'); renderResend(); return; }
    if (!s.delivery_available) {
      setVerifyState('');
      renderResend();
      formError('Email verification is not available right now. Please try again later or contact ApexRX.');
      return;
    }
    if (s.pending) {
      setVerifyState('We sent you a verification email. Open the link in it to continue.', s.expires_at);
      startCountdown(s.resend_after);
      return;
    }
    if (!emailState.autoSent && s.resend_after === 0) { await sendEmail(true); return; }
    setVerifyState('Send a verification email to continue.');
    startCountdown(s.resend_after);
  }

  async function sendEmail(automatic) {
    const form = $('#verify-email');
    emailState.autoSent = true;
    await busy(form, async () => {
      try {
        const sent = await API.auth.email.send(ROLE);
        setVerifyState('We sent you a verification email. Open the link in it to continue.', new Date(Date.now() + sent.expires_in * 1000).toISOString());
        emailState.status = Object.assign({}, emailState.status, { pending: true });
        startCountdown(sent.resend_after);
        if (!automatic) notice('A new verification email is on its way.');
      } catch (err) {
        if (err.status === 401) { sessionExpired(); return; }
        if (err.status === 409) { await checkVerified(true); return; }
        if (err.status === 429 && err.data && err.data.retry_after) startCountdown(err.data.retry_after);
        formError(errorText(err));
      }
    });
    renderResend(); // busy() re-enabled every button: keep the countdown
  }

  async function checkVerified(silent) {
    emailState.lastCheck = Date.now();
    try {
      const s = await emailStatus();
      if (s && s.verified) {
        stopEmailWatch();
        notice('Your email address is verified.');
        await route();
        return true;
      }
      if (!silent) formError('Your email is not verified yet. Open the link in the email we sent, then try again.');
    } catch (err) {
      if (err.status === 401) { sessionExpired(); return false; }
      if (!silent) formError(errorText(err));
    }
    return false;
  }

  // The link is usually opened in another tab (or on a phone): notice it.
  let channel = null;
  try { channel = new BroadcastChannel('apexrx-email-verification'); } catch (e) { /* not supported */ }
  if (channel) channel.onmessage = ev => { if (current === 1 && !$('#verify-email').hidden && ev.data && ev.data.type === 'verified') checkVerified(true); };
  function onReturn() {
    if (document.visibilityState !== 'visible' || current !== 1 || $('#verify-email').hidden) return;
    if (Date.now() - emailState.lastCheck < 3000) return;
    checkVerified(true);
  }
  let watching = false;
  function watchEmail() {
    if (watching) return;
    watching = true;
    document.addEventListener('visibilitychange', onReturn);
    window.addEventListener('focus', onReturn);
  }
  function stopEmailWatch() {
    if (!watching) return;
    watching = false;
    document.removeEventListener('visibilitychange', onReturn);
    window.removeEventListener('focus', onReturn);
  }

  $('#resend-email').addEventListener('click', () => { formError(''); sendEmail(false); });
  $('#verify-email').addEventListener('submit', e => {
    e.preventDefault();
    formError('');
    busy(e.currentTarget, () => checkVerified(false)).then(renderResend);
  });

  /* ------------------------------------------------------ step 2: details */
  let places = null; // data/rwanda-locations.json; false when it could not load
  let placesLoading = null;
  function loadPlaces() {
    if (places !== null) return Promise.resolve(places);
    if (!placesLoading) {
      placesLoading = fetch('data/rwanda-locations.json')
        .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(j => { places = j; return j; })
        .catch(() => { places = false; return false; });
    }
    return placesLoading;
  }
  const addr = { province: '', district: '', sector: '', cell: '', village: '' };
  const LEVELS = [['province', 'Province'], ['district', 'District'], ['sector', 'Sector'], ['cell', 'Cell'], ['village', 'Village']];
  const sorted = o => Object.keys(o || {}).sort((a, b) => a.localeCompare(b));

  function optionsFor(level) {
    if (level === 'province') return PROVINCES.map(([key, name]) => [key, name]);
    const p = places && places[addr.province], d = p && p[addr.district], s = d && d[addr.sector], c = s && s[addr.cell];
    if (level === 'district') return sorted(p).map(x => [x, x]);
    if (level === 'sector') return sorted(d).map(x => [x, x]);
    if (level === 'cell') return sorted(s).map(x => [x, x]);
    return (c || []).slice().sort((a, b) => a.localeCompare(b)).map(x => [x, x]);
  }

  function renderAddress() {
    const box = $('#address-fields');
    box.replaceChildren(...LEVELS.map(([level, label]) => {
      let control;
      if (level !== 'province' && places === false) {
        control = el('input', { name: level, maxlength: '100', required: '' });
        control.value = addr[level];
      } else {
        control = el('select', { name: level, required: '' });
        const opts = optionsFor(level);
        // A stored name that is not in the list (entered by hand earlier) is kept, not dropped.
        if (addr[level] && !opts.some(([value]) => value === addr[level])) opts.unshift([addr[level], addr[level]]);
        control.append(el('option', { value: '', text: '—' }));
        opts.forEach(([value, text]) => {
          const o = el('option', { value, text });
          if (value === addr[level]) o.selected = true;
          control.append(o);
        });
        if (level !== 'province' && !opts.length) control.disabled = true;
      }
      return el('label', {}, [document.createTextNode(label), control]);
    }));
    if (places === false) box.append(el('p', { class: 'note address-wide', text: 'The list of Rwandan places could not load. Type the names instead.' }));
    paintAddressSummary();
  }
  function provinceName(key) { const p = PROVINCES.find(([k]) => k === key); return p ? p[1] : key; }
  function provinceKey(stored) {
    if (!stored) return '';
    const p = PROVINCES.find(([k, n]) => n.toLowerCase() === String(stored).toLowerCase() || k.toLowerCase() === String(stored).toLowerCase());
    return p ? p[0] : '';
  }
  function addressLine(a, street) {
    return [street, a.village, a.cell, a.sector, a.district, a.province ? provinceName(a.province) : ''].filter(Boolean).join(', ');
  }
  function paintAddressSummary() {
    const text = addressLine(addr, $('#details').elements.street.value.trim());
    $('#address-summary').hidden = !text;
    $('#address-text').textContent = text;
  }

  $('#address-fields').addEventListener('change', e => {
    const level = e.target.name;
    if (!level || !(level in addr)) return;
    addr[level] = e.target.value.trim();
    const below = LEVELS.map(l => l[0]).slice(LEVELS.findIndex(l => l[0] === level) + 1);
    if (e.target.tagName === 'SELECT') below.forEach(l => { addr[l] = ''; });
    if (e.target.tagName === 'SELECT') {
      renderAddress();
      const next = $(`#address-fields [name=${below[0]}]`);
      if (next && !next.disabled) next.focus();
    } else paintAddressSummary();
  });
  $('#address-fields').addEventListener('input', e => {
    if (e.target.tagName === 'INPUT' && e.target.name in addr) { addr[e.target.name] = e.target.value.trim(); paintAddressSummary(); }
  });
  $('#details').elements.street.addEventListener('input', paintAddressSummary);

  function paintMapLink() {
    const f = $('#details').elements, lat = Number(f.latitude.value), lng = Number(f.longitude.value);
    const ok = f.latitude.value !== '' && f.longitude.value !== '' && Number.isFinite(lat) && Number.isFinite(lng);
    const link = $('#map-check');
    link.hidden = !ok;
    if (ok) link.href = `https://www.openstreetmap.org/?mlat=${lat}&mlon=${lng}#map=17/${lat}/${lng}`;
  }
  ['latitude', 'longitude'].forEach(n => $('#details').elements[n].addEventListener('input', paintMapLink));
  $('#use-location').addEventListener('click', () => {
    const button = $('#use-location');
    if (!navigator.geolocation) { formError('This browser cannot share its location. Enter the coordinates instead.'); return; }
    button.disabled = true; formError('');
    navigator.geolocation.getCurrentPosition(pos => {
      const f = $('#details').elements;
      f.latitude.value = pos.coords.latitude.toFixed(6);
      f.longitude.value = pos.coords.longitude.toFixed(6);
      button.disabled = false; paintMapLink();
      notice('Location added. Check it on the map before saving.');
    }, () => {
      button.disabled = false;
      formError('Your location could not be read. Allow location access, or enter the coordinates instead.');
    }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 });
  });

  async function showDetails() {
    show(2);
    const f = $('#details').elements, o = reg && reg.org, l = reg && reg.location;
    f.name.value = o ? o.name : (f.name.value || '');
    f.phone.value = (o && o.phone) || (l && l.phone) || f.phone.value || '';
    f.place.value = (l && l.name) || f.place.value || T.placeDefault;
    f.whatsapp.value = (l && l.whatsapp_phone) || f.whatsapp.value || '';
    if (l) {
      Object.assign(addr, { province: provinceKey(l.region), district: l.city || '', sector: l.sector || '', cell: l.cell || '', village: l.village || '' });
      f.street.value = l.address || '';
      f.latitude.value = l.latitude != null ? l.latitude : '';
      f.longitude.value = l.longitude != null ? l.longitude : '';
    }
    const managed = !o || canManage();
    [...$('#details').elements].forEach(x => { if (x.tagName !== 'BUTTON' || x.id === 'details-submit' || x.id === 'use-location') x.disabled = !managed; });
    $('#address-fields').replaceChildren(el('p', { class: 'note', text: 'Loading Rwandan places…' }));
    await loadPlaces();
    renderAddress();
    paintMapLink();
    if (!managed) formError('Only the owner or a manager can change these details.');
  }

  function readDetails() {
    const f = $('#details').elements;
    const v = {
      name: f.name.value.trim(), phone: f.phone.value.trim(), place: f.place.value.trim(), whatsapp: f.whatsapp.value.trim(),
      street: f.street.value.trim(), lat: f.latitude.value.trim(), lng: f.longitude.value.trim()
    };
    LEVELS.forEach(([level]) => { const c = $(`#address-fields [name=${level}]`); addr[level] = c ? c.value.trim() : addr[level]; });
    return v;
  }
  function invalid(name, message) {
    formError(message);
    const field = $('#details').elements[name] || $(`#address-fields [name=${name}]`);
    if (field) field.focus();
  }
  const PHONE = /^\+?[0-9 ()./-]{6,30}$/;

  $('#details').addEventListener('submit', e => {
    e.preventDefault();
    const form = e.currentTarget, v = readDetails();
    if (!v.name) return invalid('name', `Enter the ${T.name.toLowerCase()}.`);
    if (!v.phone) return invalid('phone', 'Enter a business phone number.');
    if (!PHONE.test(v.phone)) return invalid('phone', 'Enter the phone number with digits only, for example 078 812 3456.');
    if (v.whatsapp && !PHONE.test(v.whatsapp)) return invalid('whatsapp', 'Enter the WhatsApp number with digits only, or leave it empty.');
    if (!v.place) return invalid('place', `Enter a ${T.place.toLowerCase()}.`);
    const missing = LEVELS.find(([level]) => !addr[level]);
    if (missing) return invalid(missing[0], 'Choose the province, district, sector, cell and village.');
    let latitude = null, longitude = null;
    if (v.lat || v.lng) {
      latitude = Number(v.lat); longitude = Number(v.lng);
      if (!v.lat || !v.lng || !Number.isFinite(latitude) || !Number.isFinite(longitude)) return invalid(v.lat ? 'longitude' : 'latitude', 'Enter both latitude and longitude, or leave both empty.');
      if (latitude < RWANDA.latMin || latitude > RWANDA.latMax || longitude < RWANDA.lngMin || longitude > RWANDA.lngMax) return invalid('latitude', 'These coordinates are outside Rwanda. Check them on the map.');
      latitude = Number(latitude.toFixed(6)); longitude = Number(longitude.toFixed(6));
    }
    formError('');
    busy(form, async () => {
      try {
        const organization = { name: v.name, phone: v.phone, email: reg.me.email };
        if (!reg.org) {
          // The organization type comes from this page only.
          const created = await API.organizations.create(Object.assign({}, organization, { type: ROLE }));
          reg.org = created;
          reg.membership = { organization_id: created.organization_id, role: created.my_role || 'owner', organization_type: ROLE };
          remember(created.organization_id);
        } else if (canManage()) {
          reg.org = await API.organizations.update(reg.org.organization_id, organization);
        }
        if (canManage()) {
          const place = {
            name: v.place, address: v.street || null, region: provinceName(addr.province), city: addr.district,
            sector: addr.sector, cell: addr.cell, village: addr.village,
            phone: v.phone, whatsapp_phone: v.whatsapp || null, latitude, longitude
          };
          const id = reg.org.organization_id;
          reg.location = reg.location
            ? await API.organizations.updateLocation(id, reg.location.location_id, place)
            : await API.organizations.createLocation(id, place);
        }
        await load();
        showDocuments();
      } catch (err) {
        if (err.status === 401) { sessionExpired(); return; }
        if (err.status === 403 && !reg.org && err.data && err.data.reason === 'email_unverified') {
          emailState.status = null;
          await showVerify();
          formError(errorText(err));
          return;
        }
        formError(errorText(err));
      }
    });
  });
  $('#details-back').addEventListener('click', () => {
    if (reg && reg.org) { showReview(); return; }
    if (emailState.status && emailState.status.required && !emailState.status.verified) { showVerify(); return; }
    signOut();
  });

  /* ---------------------------------------------------- step 3: documents */
  function latestDocument(type) {
    return (reg.documents || []).filter(d => d.document_type === type)
      .sort((a, b) => String(b.uploaded_at).localeCompare(String(a.uploaded_at)))[0] || null;
  }
  function docState(d) {
    if (!d) return el('small', { class: 'doc-state', text: 'Not uploaded yet' });
    const s = el('small', { class: 'doc-state' }, [
      el('span', { class: 'ws-badge status-' + d.verification_status, text: DOC_STATUS[d.verification_status] || d.verification_status }),
      document.createTextNode(' '), el('span', { class: 'doc-file', text: `${d.file_name} · ${fmtSize(d.file_size_bytes)}` })
    ]);
    return s;
  }
  function showDocuments() {
    show(3);
    const list = $('#doc-list');
    list.replaceChildren(...T.docs.map(([type, label]) => {
      const d = latestDocument(type);
      const input = el('input', { type: 'file', accept: '.pdf,.png,.jpg,.jpeg', 'data-document-type': type, 'aria-label': `${label}: choose a file` });
      const chosen = el('small', { class: 'doc-chosen' });
      input.addEventListener('change', () => {
        const file = input.files[0];
        if (file && (file.size > MAX_FILE || !FILE_TYPES.test(file.name))) {
          input.value = ''; chosen.textContent = '';
          formError('Choose a PDF, PNG or JPG file of up to 10 MB.');
          return;
        }
        formError('');
        chosen.textContent = file ? `Selected: ${file.name}` : '';
      });
      return el('li', {}, [
        el('div', { class: 'doc-text' }, [el('strong', { text: label }), docState(d), chosen]),
        el('label', { class: 'file-pick' }, [document.createTextNode(d ? 'Replace file' : 'Choose file'), input])
      ]);
    }));
    $('#documents-submit').hidden = !canManage();
    if (!canManage()) formError('Only the owner or a manager can upload documents.');
  }
  $('#documents').addEventListener('submit', e => {
    e.preventDefault();
    const form = e.currentTarget;
    const inputs = [...form.querySelectorAll('input[type=file][data-document-type]')].filter(i => i.files && i.files.length);
    formError('');
    busy(form, async () => {
      try {
        if (inputs.length) {
          const id = reg.org.organization_id;
          // Side by side; each successful one is cleared so it is not sent twice.
          const results = await Promise.allSettled(inputs.map(input =>
            API.organizations.uploadDocument(id, input.dataset.documentType, input.files[0]).then(() => { input.value = ''; })));
          const failed = results.find(r => r.status === 'rejected');
          if (failed) throw failed.reason;
          notice(inputs.length === 1 ? 'Document uploaded for review.' : 'Documents uploaded for review.');
        }
        await load();
        showReview();
      } catch (err) {
        if (err.status === 401) { sessionExpired(); return; }
        formError(errorText(err));
      }
    });
  });
  $('#documents-back').addEventListener('click', () => showDetails());

  /* ------------------------------------------------------- step 4: review */
  function fact(label, value) { return [el('dt', { text: label }), el('dd', { text: value == null || value === '' ? '—' : String(value) })]; }
  function showReview() {
    show(4, false);
    const o = reg.org, l = reg.location;
    $('#review-name').textContent = o.name;
    const badge = $('#review-status');
    badge.textContent = STATUS_LABELS[o.status] || o.status;
    badge.className = 'ws-badge status-' + o.status;
    $('#review-note').textContent = T.status[o.status] || '';
    $('#review-notes-row').hidden = !o.review_notes;
    $('#review-notes').textContent = o.review_notes || '';

    const lAddress = l ? addressLine({ province: provinceKey(l.region) || '', district: l.city, sector: l.sector, cell: l.cell, village: l.village }, l.address) || (l.region || '') : '';
    const coords = l && l.latitude != null ? `${l.latitude}, ${l.longitude}` : 'Not added';
    $('#review-facts').replaceChildren(
      ...fact('Organization type', T.type),
      ...fact('Account email', reg.me.email_verified ? `${reg.me.email} (verified)` : reg.me.email),
      ...fact('Your role', ROLE_LABELS[reg.membership.role] || reg.membership.role),
      ...fact('Business phone', o.phone),
      ...fact(T.place, l ? l.name : 'Not added yet'),
      ...fact('Address', lAddress),
      ...fact('WhatsApp', l && l.whatsapp_phone),
      ...fact('Coordinates', coords),
      ...fact(T.places, String(reg.locations.filter(x => x.is_active).length)),
      ...fact('Registered', fmtDate(o.created_at))
    );

    const list = $('#review-documents');
    if (!reg.documents.length) {
      list.replaceChildren(el('li', { class: 'empty', text: 'No documents uploaded yet. ApexRX needs them to verify your registration.' }));
    } else {
      list.replaceChildren(...reg.documents.map(d => {
        const li = el('li', {}, [
          el('span', { text: `${DOC_LABELS[d.document_type] || d.document_type}: ${d.file_name}` }),
          el('span', { class: 'ws-badge status-' + d.verification_status, text: DOC_STATUS[d.verification_status] || d.verification_status })
        ]);
        if (d.rejection_reason) li.append(el('small', { text: d.rejection_reason }));
        return li;
      }));
    }
    const manage = canManage();
    $('#review-upload').hidden = !manage;
    $('#review-edit').hidden = !manage;
    $('#review-resubmit').hidden = !(o.status === 'rejected' && reg.membership.role === 'owner');
    renderOrgPick();
    $('#step-title').focus();
  }
  function renderOrgPick() {
    const list = reg ? myMemberships(reg.me) : [];
    $('#org-pick-label').hidden = list.length < 2;
    $('#org-pick').replaceChildren(...list.map(m => {
      const o = el('option', { value: String(m.organization_id), text: `${m.organization_name} (${ROLE_LABELS[m.role] || m.role})` });
      o.selected = reg.org && m.organization_id === reg.org.organization_id;
      return o;
    }));
  }
  async function refreshReview(message) {
    await load();
    if (!reg.membership) { await route(); return; }
    showReview();
    if (message) notice(message);
  }
  function reviewAction(button, task) {
    return async () => {
      button.disabled = true; formError('');
      try { await task(); } catch (err) {
        if (err.status === 401) { sessionExpired(); return; }
        formError(errorText(err));
      } finally { button.disabled = false; }
    };
  }
  $('#review-edit').addEventListener('click', () => showDetails());
  $('#review-refresh').addEventListener('click', reviewAction($('#review-refresh'), () => refreshReview('Status updated.')));
  $('#review-resubmit').addEventListener('click', reviewAction($('#review-resubmit'), async () => {
    await API.organizations.resubmit(reg.org.organization_id);
    await refreshReview('Your registration is back in the ApexRX review queue.');
  }));
  $('#upload-button').addEventListener('click', reviewAction($('#upload-button'), async () => {
    const file = $('#upload-file').files[0];
    if (!file) { formError('Choose a file to upload.'); return; }
    if (file.size > MAX_FILE || !FILE_TYPES.test(file.name)) { formError('Choose a PDF, PNG or JPG file of up to 10 MB.'); return; }
    await API.organizations.uploadDocument(reg.org.organization_id, $('#upload-type').value, file);
    $('#upload-file').value = '';
    await refreshReview('Document uploaded for review.');
  }));
  $('#org-pick').addEventListener('change', reviewAction($('#org-pick'), async e => {
    remember(e && e.target ? e.target.value : $('#org-pick').value);
    await refreshReview();
  }));
  const openButton = $('#open-workspace');
  if (openButton) openButton.addEventListener('click', reviewAction(openButton, () => openWorkspace()));

  /* ------------------------------------------- joining an existing pharmacy */
  if ($('#join-existing')) {
    $('#join-existing').addEventListener('click', () => {
      showPanel($('#join-wait'), 'Join an existing pharmacy', 'Your pharmacy adds your account; you do not register a new one.');
      $('#join-email').textContent = reg ? reg.me.email : '';
      $('#join-status').textContent = '';
    });
    $('#join-check').addEventListener('click', reviewAction($('#join-check'), async () => {
      $('#join-status').textContent = 'Checking…';
      await load();
      if (reg.membership) { $('#join-status').textContent = ''; await route(); notice(`Welcome to ${reg.org.name}.`); return; }
      $('#join-status').textContent = 'You have not joined a pharmacy yet. Ask the owner or a manager to invite ' + reg.me.email + ', then open the link in their email.';
    }));
    $('#join-register').addEventListener('click', reviewAction($('#join-register'), () => route()));
  }

  /* ---------------------------------------------------------------- shared */
  $('#sign-out').addEventListener('click', signOut);
  window.addEventListener('apexrx:signed-out', e => {
    // Sign-out from this page (handled by signOut), another tab, inactivity,
    // or any 401 from the API (an ended session).
    if (signingOut) return;
    const detail = e.detail || {};
    if (!reg && !['idle', 'other_tab'].includes(detail.reason)) return;
    reset(signedOutText(detail));
  });

  window.ApexRegistration = {
    reset,
    // Shown from the pharmacy workspace (Pharmacy profile -> registration).
    async showReview() {
      $('#dashboard') && ($('#dashboard').hidden = true);
      $('#onboarding').hidden = false;
      try { await load(); if (reg.membership) showReview(); else await route(); } catch (err) {
        if (err.status === 401) sessionExpired(); else formError(errorText(err));
      }
    }
  };

  /* --------------------------------------------------------------- startup */
  async function start() {
    setAuthMode(authMode, false);
    show(0, false);
    if (authMode === 'signin') $('#account').elements.email.focus();
    loadPlaces(); // in the background, for the details step
    if (!API || !API.session.isSignedIn()) return;
    // A session from this tab (a refresh, or another ApexRX page): continue it,
    // and show which account it is ("Signed in as … · Sign out").
    try { await route(); } catch (err) {
      reg = null; paintSignedIn(); show(0, false);
      if (err.status !== 401) formError(errorText(err));
    }
  }
  // After the page's other scripts (js/pharmacies.js registers the workspace).
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else setTimeout(start);
})();
