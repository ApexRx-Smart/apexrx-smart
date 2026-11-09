'use strict';
/* Pharmacy workspace (pharmacies.html), connected to the ApexRX API (js/api.js).
 *
 * Registration (account, email verification, details, documents, review) is
 * js/registration.js, shared with suppliers.html. It opens this workspace
 * through window.ApexPharmacyWorkspace once a pharmacy is registered:
 *   overview, branches, employees, inventory and purchase orders
 *   (js/workspace.js), supplier discovery via GET /supplier-offers (approved
 *   pharmacies only), contact through WhatsApp/phone links. Users in several
 *   pharmacies choose one with the organization selector.
 *
 * "Just exploring?" opens the workspace with sample data and no account.
 * There are no subscriptions or payments.
 */
const $ = s => document.querySelector(s);
const API = window.ApexAPI;
const SAMPLE_PROFILE = { name: 'Kigali Pharmacy', phone: '+250 788 123 456', address: 'Kigali, Rwanda', latitude: '-1.9441', longitude: '30.0619' };
const STATUS_NOTES = {
  pending: 'Your pharmacy is awaiting verification by ApexRX. Supplier search opens once it is approved.',
  approved: 'Your pharmacy is verified. Listed medicines are visible to patients on ApexRX.',
  rejected: 'Your registration was not approved. Open your registration to correct it and resubmit it for review.',
  suspended: 'Your pharmacy is suspended. Contact ApexRX for help.'
};
const STATUS_LABELS_LIVE = { pending: 'Pending review', approved: 'Approved', rejected: 'Not approved', suspended: 'Suspended' };
const NO_CONTACTS = 'No supplier conversations yet. Search for a medicine to find a supplier and contact them.';
const SEARCH_HINT = 'Search for a medicine to see supplier stock, prices and contacts.';
const LIVE_PANEL_NOTE = 'Supplier stock and prices are live. Conversations happen on WhatsApp or by phone.';

let profile = { ...SAMPLE_PROFILE };
// Live account state. null while previewing with sample data.
let live = null; // { user, organization, location }
let noticeTimer;

function notice(text) { $('#notice').textContent = text; clearTimeout(noticeTimer); noticeTimer = setTimeout(() => $('#notice').textContent = '', 7000); }
function errorText(err) { return (err && err.message) || 'Something went wrong. Please try again.'; }

/* ------------------------------------------------------------ live state */
const ORG_KEY = 'apexrx_selected_pharmacy';
function pharmacyMemberships(me) {
  return (me.memberships || []).filter(m => m.organization_type === 'pharmacy');
}
// The organization chosen in the selector (kept for this tab), otherwise the
// first one; users in several pharmacies can switch at any time.
function pharmacyMembership(me) {
  const list = pharmacyMemberships(me);
  let saved = null;
  try { saved = sessionStorage.getItem(ORG_KEY); } catch (e) { /* storage unavailable */ }
  return list.find(m => String(m.organization_id) === saved) || list[0] || null;
}
function selectOrganization(organizationId) {
  try { sessionStorage.setItem(ORG_KEY, String(organizationId)); } catch (e) { /* storage unavailable */ }
}
function renderOrgSwitch() {
  const label = $('#org-switch-label'), select = $('#org-switch');
  const list = live && live.user ? pharmacyMemberships(live.user) : [];
  label.hidden = list.length < 2;
  select.replaceChildren(...list.map(m => {
    const option = document.createElement('option');
    option.value = m.organization_id;
    option.textContent = `${m.organization_name} (${m.role})`;
    option.selected = live.organization && m.organization_id === live.organization.organization_id;
    return option;
  }));
}

function profileFromLive() {
  const o = live.organization, l = live.location || {};
  const address = [l.address, l.village, l.cell, l.sector, l.city, l.region].filter(Boolean).join(', ');
  return {
    name: o.name,
    status: STATUS_LABELS_LIVE[o.status] || o.status,
    phone: o.phone || l.phone || '—',
    address: address || '—',
    latitude: l.latitude != null ? String(l.latitude) : '—',
    longitude: l.longitude != null ? String(l.longitude) : '—',
    documents: (live.documents || []).length
      ? live.documents.map(d => `${DOCUMENT_LABELS[d.document_type] || d.document_type}: ${d.verification_status}`).join(' · ')
      : 'None uploaded'
  };
}

// Load the signed-in user, their pharmacy and its main location.
async function loadLive() {
  const me = await API.auth.me();
  const membership = pharmacyMembership(me);
  // Build the new state completely before replacing `live`, so nothing that
  // runs meanwhile (a debounced search, a section render, an organization
  // switch) ever sees a half-loaded organization.
  const next = { user: me, organization: null, location: null, locations: [], role: membership ? membership.role : null };
  if (membership) {
    // Everything the workspace needs, requested at once rather than one after
    // another. Documents and orders are optional: a failure keeps the page usable.
    const orgId = membership.organization_id;
    const [organization, locations, extras] = await Promise.all([
      API.organizations.get(orgId),
      // All branches (inactive ones too, for the Branches section).
      API.organizations.locations(orgId, { include_inactive: true }),
      fetchWorkspaceData(orgId)
    ]);
    next.organization = organization;
    next.locations = locations || [];
    next.location = next.locations.find(l => l.is_active) || next.locations[0] || null;
    applyWorkspaceData(next, extras);
  }
  live = next;
  return live;
}

const DOCUMENT_LABELS = { business_license: 'Business license', pharmacy_license: 'Pharmacy license', owner_id: 'Owner ID' };

// Documents and supplier contacts change while the user works, so they are
// reloaded with the rest of the workspace. A failed request keeps the last values.
function fetchWorkspaceData(orgId) {
  return Promise.allSettled([
    API.organizations.documents(orgId),
    API.purchaseOrders.list({ organization_id: orgId, limit: 100 })
  ]);
}
function applyWorkspaceData(target, [documents, orders]) {
  if (documents.status === 'fulfilled') target.documents = documents.value;
  if (orders.status === 'fulfilled') target.contacts = supplierContacts(orders.value.items);
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
  live = null; profile = { ...SAMPLE_PROFILE }; currentView = 'home';
}

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
  const status = $('#status-card');
  setLiveText(status && status.querySelector('small'), isLive ? (STATUS_LABELS_LIVE[live.organization.status] || live.organization.status) + ' · View details →' : null);
}

function openDashboard() {
  if (live && live.organization) profile = { ...profile, ...profileFromLive() };
  $('#onboarding').hidden = true; $('#dashboard').hidden = false;
  $('#pharmacy-name').textContent = profile.name;
  renderOrgSwitch();
  $('#today').textContent = new Date().toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
  paintWorkspace();
  view('home');
  window.scrollTo(0, 0);
}

// Opened by js/registration.js.
window.ApexPharmacyWorkspace = {
  async open() { await loadLive(); openDashboard(); },
  preview() { resetLive(); openDashboard(); }
};
$('#restart').addEventListener('click', () => {
  // Leaving the workspace signs out (or ends the preview).
  if (live) API.auth.logout();
  resetLive();
  window.ApexRegistration.reset();
});
window.addEventListener('apexrx:signed-out', () => {
  // js/registration.js shows the sign-in step (with "session expired" when it was not on purpose).
  if (live) resetLive();
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
  if (!live || !live.organization) return; // signed out while the search was debounced
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
  if (live && live.organization) {
    // Registration details, documents and resubmission live in js/registration.js.
    const open = document.createElement('button');
    open.type = 'button'; open.className = 'secondary'; open.id = 'open-registration';
    open.textContent = 'Registration and documents →';
    open.addEventListener('click', () => window.ApexRegistration.showReview());
    $('#profile-summary').append(open);
  }
}

let currentView = 'home';
// Sections rendered by js/workspace.js (they replace the supplier list).
const WORKSPACE_VIEWS = { branches: 'Branches', employees: 'Employees', inventory: 'Inventory', orders: 'Purchase orders' };
function view(name) {
  currentView = name;
  document.querySelectorAll('.sidebar [data-view]').forEach(b => b.classList.toggle('selected', b.dataset.view === name));
  $('#panel-title').textContent = WORKSPACE_VIEWS[name] || ({ home: live && live.organization ? 'Overview' : 'Recent supplier conversations', source: 'Find a medicine source', chat: 'Your supplier conversations', profile: 'Your pharmacy details' })[name];
  const section = !!WORKSPACE_VIEWS[name];
  const summary = name === 'home' && live && live.organization;
  $('#suppliers').hidden = name === 'profile' || section; $('#search-label').hidden = name === 'profile' || section;
  $('#profile-summary').hidden = name !== 'profile';
  $('#workspace-section').hidden = !(section || summary);
  if (section || summary) window.ApexWorkspace.render(section ? name : 'overview');
  if (section) { $('#panel-title').focus(); return; }
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

/* -------------------------------------------------- organization switch */
$('#org-switch').addEventListener('change', async e => {
  selectOrganization(e.target.value);
  try {
    await loadLive();
    openDashboard();
    notice(`Switched to ${live.organization.name}.`);
  } catch (err) { notice(errorText(err)); }
});
