'use strict';
/* Pharmacy workspace sections: overview, branches, employees, inventory and
 * purchase orders. Loaded after js/pharmacies.js and uses its live state
 * (`live`: user, organization, role, locations) and helpers.
 *
 * Every action calls the real backend through js/api.js. Buttons are hidden
 * or disabled when the user's role cannot use them, but the backend is the
 * authority: its errors (403, 409, ...) are always shown as returned.
 *
 *   Branches   GET/POST/PATCH /organizations/{id}/locations
 *   Employees  GET/POST/PATCH/DELETE /organizations/{id}/members
 *   Inventory  GET /organizations/{id}/inventory?location_id=,
 *              PUT .../locations/{loc}/stock/{product}[/offer]
 *   Orders     GET/POST /purchase-orders, GET /purchase-orders/{id},
 *              PATCH/DELETE items, POST /purchase-orders/{id}/{action}
 */
(function () {
  const ROLE_LABELS = { owner: 'Owner', manager: 'Manager', staff: 'Staff' };
  const STATUS_LABELS = { pending: 'Pending verification', approved: 'Approved', rejected: 'Rejected', suspended: 'Suspended' };
  const ACTION_LABELS = { submit: 'Submit to supplier', cancel: 'Cancel order', accept_counter: 'Accept counteroffer', mark_delivered: 'Mark as delivered', delete: 'Delete draft' };
  const ACTION_PATHS = { accept_counter: 'accept-counter', mark_delivered: 'mark-delivered' };
  const state = { inventoryBranch: null, order: null, draft: null };
  let token = 0;

  const box = () => document.getElementById('workspace-section');
  const orgId = () => live.organization.organization_id;
  const canManage = () => live.role === 'owner' || live.role === 'manager';
  const isApproved = () => live.organization.status === 'approved';
  const activeBranches = () => (live.locations || []).filter(l => l.is_active);

  /* ------------------------------------------------------------ helpers */
  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => {
      if (v === undefined || v === null || v === false) return;
      if (k === 'text') node.textContent = v;
      else if (k === 'class') node.className = v;
      else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
      else if (['disabled', 'checked', 'selected', 'readOnly', 'required'].includes(k)) node[k] = true;
      else node.setAttribute(k, v === true ? '' : v);
    });
    children.flat().forEach(c => { if (c !== null && c !== undefined && c !== false) node.append(c); });
    return node;
  }
  const msg = (text, kind) => el('p', { class: `ws-msg${kind ? ' ' + kind : ''}`, role: kind === 'error' ? 'alert' : 'status', text });
  const heading = text => el('h3', { class: 'ws-heading', text });
  const date = iso => (iso ? new Date(iso).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' }) : '—');
  const button = (text, onclick, cls, extra) => el('button', { type: 'button', class: `ws-btn${cls ? ' ' + cls : ''}`, text, onclick, ...(extra || {}) });

  function table(headers, rows, empty) {
    if (!rows.length) return msg(empty || 'Nothing here yet.');
    return el('div', { class: 'ws-table-wrap' },
      el('table', { class: 'ws-table' },
        el('thead', {}, el('tr', {}, headers.map(h => el('th', { text: h })))),
        el('tbody', {}, rows)));
  }

  // Run an API action with the button disabled; show errors next to it.
  async function act(btn, statusEl, task, success) {
    if (btn) btn.disabled = true;
    if (statusEl) statusEl.replaceChildren();
    try {
      await task();
      if (success) notice(success);
      return true;
    } catch (err) {
      if (err.status === 401) return false; // the signed-out handler takes over
      if (statusEl) statusEl.replaceChildren(msg(errorText(err), 'error')); else notice(errorText(err));
      return false;
    } finally { if (btn) btn.disabled = false; }
  }

  // Reload organization, branches and role after a change, then repaint.
  async function refreshLive() {
    await loadLive();
    if (!live.organization) { location.reload(); return; }
    profile = { ...profile, ...profileFromLive() };
    $('#pharmacy-name').textContent = live.organization.name;
    paintWorkspace(); renderOrgSwitch();
  }

  function render(name) {
    const container = box();
    const my = ++token;
    const settle = () => { container.classList.remove('ws-refreshing'); container.removeAttribute('aria-busy'); };
    if (!live || !live.organization) {
      settle(); delete container.dataset.section;
      container.replaceChildren(msg('Sign in with your pharmacy account to use this section. The preview has no live data.'));
      return;
    }
    const renderers = { overview: renderOverview, branches: renderBranches, employees: renderEmployees, inventory: renderInventory, orders: renderOrders };
    // Repainting the section that is already on screen (after a save, say):
    // keep it visible, dimmed, until the new content is ready, instead of
    // flashing "Loading…". A different section starts from "Loading…".
    const refreshing = container.dataset.section === name && container.childElementCount > 0;
    container.dataset.section = name;
    if (refreshing) { container.classList.add('ws-refreshing'); container.setAttribute('aria-busy', 'true'); }
    else { settle(); container.replaceChildren(msg('Loading…')); }
    Promise.resolve(renderers[name](container, () => my === token)).catch(err => {
      if (my === token && err.status !== 401) container.replaceChildren(msg(errorText(err), 'error'));
    }).finally(() => { if (my === token) settle(); });
  }

  /* ----------------------------------------------------------- overview */
  async function renderOverview(c, current) {
    const [members, orders] = await Promise.allSettled([
      API.organizations.members(orgId()),
      API.purchaseOrders.list({ organization_id: orgId(), limit: 100 })
    ]);
    if (!current()) return;
    const branches = activeBranches();
    const dl = el('dl', { class: 'ws-facts' });
    const add = (k, v) => dl.append(el('dt', { text: k }), el('dd', { text: v }));
    add('Organization', live.organization.name);
    add('Verification status', STATUS_LABELS[live.organization.status] || live.organization.status);
    add('Your role', ROLE_LABELS[live.role] || live.role);
    add('Active branches', branches.length ? `${branches.length}: ${branches.map(b => b.name).join(', ')}` : 'None yet');
    add('Members', members.status === 'fulfilled'
      ? `${members.value.filter(m => m.is_active).length} active` : 'Could not be loaded');
    if (orders.status === 'fulfilled') {
      const counts = {};
      orders.value.items.forEach(o => { counts[o.status] = (counts[o.status] || 0) + 1; });
      const parts = Object.entries(counts).map(([s, n]) => `${n} ${(ORDER_STATUS_LABELS[s] || s).toLowerCase()}`);
      add('Purchase orders', orders.value.total ? `${orders.value.total} total${parts.length ? ' · ' + parts.join(' · ') : ''}` : 'None yet');
    } else add('Purchase orders', 'Could not be loaded');
    const links = el('div', { class: 'ws-row' },
      ['branches', 'employees', 'inventory', 'orders'].map(v => button(`Open ${WORKSPACE_VIEWS[v].toLowerCase()} →`, () => view(v))));
    c.replaceChildren(dl, links);
  }

  /* ----------------------------------------------------------- branches */
  function renderBranches(c) {
    const status = el('div');
    const branches = [...(live.locations || [])].sort((a, b) => (b.is_active - a.is_active) || a.name.localeCompare(b.name));
    const rows = branches.map(b => el('tr', { 'data-branch': b.location_id },
      el('td', {}, el('strong', { text: b.name })),
      el('td', { text: [b.address, b.city, b.region].filter(Boolean).join(', ') || '—' }),
      el('td', { text: [b.phone && `Phone ${b.phone}`, b.whatsapp_phone && `WhatsApp ${b.whatsapp_phone}`].filter(Boolean).join(' · ') || '—' }),
      el('td', { text: b.latitude != null ? `${b.latitude}, ${b.longitude}` : '—' }),
      el('td', {}, el('span', { class: `ws-badge ${b.is_active ? 'ok' : 'off'}`, text: b.is_active ? 'Active' : 'Inactive' })),
      canManage() ? el('td', { class: 'ws-cell-actions' },
        button('Edit', () => fillForm(b)),
        b.is_active
          ? button('Deactivate', e => {
            if (!confirm(`Deactivate ${b.name}? It disappears from patient search and cannot receive orders. Its records are kept.`)) return;
            act(e.target, status, async () => { await API.organizations.updateLocation(orgId(), b.location_id, { is_active: false }); await refreshLive(); render('branches'); }, `${b.name} deactivated.`);
          }, 'danger')
          : button('Reactivate', e => act(e.target, status, async () => {
            await API.organizations.updateLocation(orgId(), b.location_id, { is_active: true }); await refreshLive(); render('branches');
          }, `${b.name} reactivated.`))) : null));
    const headers = ['Branch', 'Address', 'Contact', 'Coordinates', 'Status'].concat(canManage() ? ['Actions'] : []);
    const parts = [heading(`All branches (${branches.filter(b => b.is_active).length} active)`), status, table(headers, rows, 'No branches yet.')];

    let fillForm = () => {};
    if (canManage()) {
      const f = el('form', { class: 'ws-form', id: 'branch-form', novalidate: true });
      const field = (name, label, attrs) => el('label', { text: label }, el('input', { name, ...(attrs || {}) }));
      const title = heading('Add a branch');
      const formStatus = el('div');
      const submit = el('button', { class: 'ws-btn primary-sm', text: 'Add branch' });
      const cancelEdit = button('Cancel editing', () => reset(), '', { hidden: true });
      f.append(title,
        el('div', { class: 'ws-grid' },
          field('name', 'Branch name *', { required: true, maxlength: 255 }),
          field('address', 'Address'), field('city', 'City'), field('region', 'Region / district'),
          field('latitude', 'Latitude', { type: 'number', step: 'any', min: -90, max: 90 }),
          field('longitude', 'Longitude', { type: 'number', step: 'any', min: -180, max: 180 }),
          field('phone', 'Phone', { type: 'tel' }), field('whatsapp_phone', 'WhatsApp', { type: 'tel' })),
        formStatus, el('div', { class: 'ws-row' }, submit, cancelEdit));
      let editing = null;
      const reset = () => { editing = null; f.reset(); title.textContent = 'Add a branch'; submit.textContent = 'Add branch'; cancelEdit.hidden = true; formStatus.replaceChildren(); };
      fillForm = b => {
        editing = b; title.textContent = `Edit ${b.name}`; submit.textContent = 'Save changes'; cancelEdit.hidden = false;
        ['name', 'address', 'city', 'region', 'latitude', 'longitude', 'phone', 'whatsapp_phone'].forEach(k => { f.elements[k].value = b[k] == null ? '' : b[k]; });
        f.scrollIntoView({ block: 'center' }); f.elements.name.focus();
      };
      f.addEventListener('submit', e => {
        e.preventDefault();
        const v = k => f.elements[k].value.trim();
        if (!v('name')) { formStatus.replaceChildren(msg('Enter the branch name.', 'error')); return; }
        if (!!v('latitude') !== !!v('longitude')) { formStatus.replaceChildren(msg('Enter both latitude and longitude, or neither.', 'error')); return; }
        const data = { name: v('name') };
        ['address', 'city', 'region', 'phone', 'whatsapp_phone'].forEach(k => { if (v(k) || editing) data[k] = v(k) || null; });
        if (v('latitude')) { data.latitude = Number(v('latitude')); data.longitude = Number(v('longitude')); } else if (editing) { data.latitude = null; data.longitude = null; }
        const wasEditing = editing;
        act(submit, formStatus, async () => {
          if (wasEditing) await API.organizations.updateLocation(orgId(), wasEditing.location_id, data);
          else await API.organizations.createLocation(orgId(), data);
          await refreshLive(); render('branches');
        }, wasEditing ? 'Branch updated.' : `Branch ${data.name} added.`);
      });
      parts.push(f);
    } else parts.push(msg('Only owners and managers can add or change branches.'));
    c.replaceChildren(...parts);
  }

  /* ---------------------------------------------------------- employees */
  async function renderEmployees(c, current) {
    const members = await API.organizations.members(orgId());
    if (!current()) return;
    const status = el('div');
    const me = live.user.user_id;
    const owner = live.role === 'owner';
    // Mirrors the backend: owners manage everyone; managers manage staff only.
    const canEdit = m => canManage() && (owner || m.role === 'staff') && m.user_id !== me;
    const roleChoices = owner ? ['owner', 'manager', 'staff'] : ['staff'];
    const rows = members.map(m => {
      const select = el('select', { 'aria-label': `Role for ${m.email}` },
        roleChoices.map(r => el('option', { value: r, text: ROLE_LABELS[r], selected: r === m.role })));
      return el('tr', { 'data-member': m.email },
        el('td', {}, el('strong', { text: m.name }), m.user_id === me ? el('small', { text: ' (you)' }) : null),
        el('td', { text: m.email }),
        el('td', {}, canEdit(m) && owner ? select : el('span', { text: ROLE_LABELS[m.role] || m.role })),
        el('td', {}, el('span', { class: `ws-badge ${m.is_active ? 'ok' : 'off'}`, text: m.is_active ? 'Active' : 'Deactivated' })),
        el('td', { class: 'ws-cell-actions' }, canEdit(m) ? [
          owner ? button('Save role', e => act(e.target, status, async () => {
            await API.organizations.updateMember(orgId(), m.membership_id, { role: select.value }); render('employees');
          }, `${m.email} is now ${ROLE_LABELS[select.value].toLowerCase()}.`)) : null,
          button(m.is_active ? 'Deactivate' : 'Reactivate', e => {
            if (m.is_active && !confirm(`Deactivate ${m.email}? They immediately lose access to this pharmacy.`)) return;
            act(e.target, status, async () => {
              await API.organizations.updateMember(orgId(), m.membership_id, { is_active: !m.is_active }); render('employees');
            }, `${m.email} ${m.is_active ? 'deactivated' : 'reactivated'}.`);
          }, m.is_active ? 'danger' : ''),
          button('Remove', e => {
            if (!confirm(`Remove ${m.email} from ${live.organization.name}?`)) return;
            act(e.target, status, async () => { await API.organizations.removeMember(orgId(), m.membership_id); render('employees'); }, `${m.email} removed.`);
          }, 'danger')
        ] : null));
    });
    const parts = [heading(`Members (${members.filter(m => m.is_active).length} active)`), status,
      table(['Name', 'Email', 'Role', 'Status', 'Actions'], rows, 'No members.')];
    if (canManage()) {
      const f = el('form', { class: 'ws-form', id: 'member-form', novalidate: true });
      const formStatus = el('div');
      const submit = el('button', { class: 'ws-btn primary-sm', text: 'Add employee' });
      f.append(heading('Add an employee'),
        msg('The employee needs their own ApexRX account first: they register at For Pharmacies with their own email and choose “Joining an existing pharmacy”. Accounts are never shared.'),
        el('div', { class: 'ws-grid' },
          el('label', { text: 'Their account email *' }, el('input', { name: 'email', type: 'email', required: true, autocomplete: 'off' })),
          el('label', { text: 'Role' }, el('select', { name: 'role' },
            (owner ? ['staff', 'manager', 'owner'] : ['staff']).map(r => el('option', { value: r, text: ROLE_LABELS[r] }))))),
        formStatus, submit);
      f.addEventListener('submit', e => {
        e.preventDefault();
        const email = f.elements.email.value.trim();
        if (!email) { formStatus.replaceChildren(msg('Enter the employee’s account email.', 'error')); return; }
        act(submit, formStatus, async () => {
          await API.organizations.addMember(orgId(), email, f.elements.role.value); render('employees');
        }, `${email} added as ${ROLE_LABELS[f.elements.role.value].toLowerCase()}.`);
      });
      parts.push(f);
    } else parts.push(msg('Only owners and managers can add or change employees.'));
    c.replaceChildren(...parts);
  }

  /* ---------------------------------------------------------- inventory */
  async function renderInventory(c, current) {
    const branches = activeBranches();
    if (!branches.length) { c.replaceChildren(msg('Add an active branch first: inventory is kept per branch.')); return; }
    if (!branches.some(b => b.location_id === state.inventoryBranch)) state.inventoryBranch = branches[0].location_id;
    const branch = branches.find(b => b.location_id === state.inventoryBranch);
    const page = await API.inventory.list(orgId(), { location_id: branch.location_id, limit: 100 });
    if (!current()) return;

    const picker = el('label', { class: 'ws-inline', text: 'Branch ' },
      el('select', { id: 'inventory-branch', onchange: e => { state.inventoryBranch = Number(e.target.value); render('inventory'); } },
        branches.map(b => el('option', { value: b.location_id, text: b.name, selected: b.location_id === branch.location_id }))));
    const status = el('div');
    const notes = [];
    if (!isApproved()) notes.push(msg('Stock and prices can be recorded once ApexRX approves your pharmacy.', 'warn'));
    if (!canManage()) notes.push(msg('As staff you can update quantities. Prices and listing are managed by owners and managers.'));

    const rows = page.items.map(item => {
      const qty = el('input', { type: 'number', min: 0, step: 1, value: item.quantity, 'aria-label': `Quantity of ${item.product_name} at ${branch.name}`, class: 'ws-num' });
      const price = el('input', { type: 'number', min: 0, step: 'any', value: item.offer ? item.offer.unit_price : '', placeholder: 'Price', 'aria-label': `Price of ${item.product_name} at ${branch.name}`, class: 'ws-num' });
      const listed = el('input', { type: 'checkbox', checked: item.offer ? item.offer.is_listed : true, 'aria-label': `List ${item.product_name} for patients` });
      return el('tr', { 'data-product': item.product_name },
        el('td', {}, el('strong', { text: productLabel(item) }), el('small', { class: 'ws-sub', text: item.drug_name })),
        el('td', { class: 'ws-cell-actions' }, qty, button('Save', e => {
          const n = Number(qty.value);
          if (!Number.isInteger(n) || n < 0) { status.replaceChildren(msg('Quantities are whole numbers, 0 or more.', 'error')); return; }
          act(e.target, status, async () => { await API.inventory.setQuantity(orgId(), branch.location_id, item.product_id, n); render('inventory'); },
            `${item.product_name} at ${branch.name}: ${n} in stock.`);
        }, '', { disabled: !isApproved() })),
        el('td', { class: 'ws-cell-actions' }, canManage() ? [price, el('label', { class: 'ws-check', text: ' Listed' }, listed), button('Save price', e => {
          if (price.value === '' || Number(price.value) < 0) { status.replaceChildren(msg('Enter a selling price (0 or more).', 'error')); return; }
          act(e.target, status, async () => {
            await API.inventory.setOffer(orgId(), branch.location_id, item.product_id, {
              unit_price: String(price.value), is_listed: listed.checked,
              low_stock_threshold: item.offer ? item.offer.low_stock_threshold : 5
            });
            render('inventory');
          }, `${item.product_name} at ${branch.name}: price saved.`);
        }, '', { disabled: !isApproved() })] : el('span', {
          text: item.offer ? `${formatPrice(item.offer.unit_price, item.offer.currency)}${item.offer.is_listed ? '' : ' (not listed)'}` : 'No price set'
        })),
        el('td', { text: item.availability_status ? item.availability_status.replace('_', ' ') : 'Not listed' }),
        el('td', { text: date(item.last_updated) }));
    });
    const parts = [picker, heading(`Inventory at ${branch.name}`), ...notes, status,
      table(['Medicine', 'Quantity', 'Selling price & listing', 'Patients see', 'Last updated'], rows,
        `No medicines recorded at ${branch.name} yet. Add one below.`)];
    if (page.total > page.items.length) parts.push(msg(`Showing the first ${page.items.length} of ${page.total} medicines.`));

    // Add a catalogue product to this branch.
    const f = el('form', { class: 'ws-form', id: 'stock-add-form', novalidate: true });
    const results = el('div', { class: 'ws-results' });
    const searchStatus = el('div');
    f.append(heading(`Add a medicine to ${branch.name}`),
      el('div', { class: 'ws-row' }, el('input', { name: 'q', type: 'search', placeholder: 'Search the ApexRX catalogue (e.g. paracetamol)', 'aria-label': 'Search the medicine catalogue' }),
        el('button', { class: 'ws-btn', text: 'Search' })), searchStatus, results);
    f.addEventListener('submit', e => {
      e.preventDefault();
      const q = f.elements.q.value.trim();
      if (q.length < 2) { searchStatus.replaceChildren(msg('Type at least 2 characters.', 'error')); return; }
      act(null, searchStatus, async () => {
        const products = await API.catalogue.products({ q, limit: 20 });
        const existing = new Set(page.items.map(i => i.product_id));
        results.replaceChildren(table(['Medicine', 'Initial quantity', ''], products.items.map(p => {
          const qty = el('input', { type: 'number', min: 0, step: 1, value: 0, class: 'ws-num', 'aria-label': `Initial quantity of ${p.product_name}` });
          return el('tr', {}, el('td', { text: productLabel(p) }), el('td', {}, qty),
            el('td', {}, existing.has(p.product_id) ? el('span', { text: 'Already recorded here' }) : button(`Add to ${branch.name}`, ev => {
              act(ev.target, searchStatus, async () => {
                await API.inventory.setQuantity(orgId(), branch.location_id, p.product_id, Number(qty.value) || 0); render('inventory');
              }, `${p.product_name} added to ${branch.name}.`);
            }, '', { disabled: !isApproved() })));
        }), 'No catalogue medicine matches. Ask ApexRX to add it to the catalogue.'));
      });
    });
    parts.push(f);
    c.replaceChildren(...parts);
  }

  /* ------------------------------------------------------------- orders */
  function renderOrders(c, current) {
    if (state.order === 'new') return renderNewOrder(c, current);
    if (state.order) return renderOrderDetail(c, current, state.order);
    return renderOrderList(c, current);
  }
  const openOrder = id => { state.order = id; render('orders'); };

  async function renderOrderList(c, current) {
    const page = await API.purchaseOrders.list({ organization_id: orgId(), limit: 100 });
    if (!current()) return;
    const rows = page.items.map(o => el('tr', { 'data-order': o.purchase_order_id },
      el('td', { text: `#${o.purchase_order_id}` }),
      el('td', { text: o.supplier.name }),
      el('td', { text: o.pharmacy.location_name || '—' }),
      el('td', {}, el('span', { class: 'ws-badge', text: ORDER_STATUS_LABELS[o.status] || o.status })),
      el('td', { text: formatPrice(o.confirmed_total != null ? o.confirmed_total : o.requested_total, o.currency) }),
      el('td', { text: String(o.item_count) }),
      el('td', { text: date(o.updated_at) }),
      el('td', {}, button('Open', () => openOrder(o.purchase_order_id)))));
    const top = el('div', { class: 'ws-row' },
      isApproved() ? button('New purchase order', () => { state.order = 'new'; state.draft = null; render('orders'); }, 'primary-sm')
        : msg('Purchase orders open once ApexRX approves your pharmacy.', 'warn'));
    const parts = [top, heading(`Orders (${page.total})`),
      table(['Order', 'Supplier', 'Receiving branch', 'Status', 'Total', 'Items', 'Updated', ''], rows, 'No purchase orders yet.')];
    if (!canManage()) parts.push(msg('As staff you can view orders and prepare drafts. Owners and managers submit, cancel and accept counteroffers.'));
    c.replaceChildren(...parts);
  }

  function renderNewOrder(c) {
    const branches = activeBranches();
    const draft = state.draft || (state.draft = { supplier: null, items: [], warehouses: new Map() });
    const status = el('div');
    const back = button('← Back to orders', () => { state.order = null; render('orders'); });
    if (!branches.length) { c.replaceChildren(back, msg('Add an active branch first: every order needs a receiving branch.', 'error')); return; }

    const branchSelect = el('select', { id: 'order-branch' }, branches.map(b => el('option', { value: b.location_id, text: b.name, selected: draft.branch === b.location_id })));
    branchSelect.addEventListener('change', () => { draft.branch = Number(branchSelect.value); });
    if (!draft.branch) draft.branch = branches[0].location_id;

    // Supplier stock search (exact supplier stock is pharmacy-only).
    const results = el('div', { class: 'ws-results' });
    const search = el('form', { class: 'ws-row', id: 'order-search', novalidate: true },
      el('input', { name: 'q', type: 'search', placeholder: 'Medicine to order (e.g. paracetamol)', 'aria-label': 'Search supplier stock' }),
      el('button', { class: 'ws-btn', text: 'Search suppliers' }));
    search.addEventListener('submit', e => {
      e.preventDefault();
      const q = search.elements.q.value.trim();
      if (q.length < 2) { status.replaceChildren(msg('Type at least 2 characters.', 'error')); return; }
      act(null, status, async () => {
        const params = { pharmacy_organization_id: orgId(), q, sort: 'price', limit: 25 };
        if (draft.supplier) params.supplier_organization_id = draft.supplier.id;
        const page = await API.supplierOffers.search(params);
        results.replaceChildren(table(['Supplier', 'Warehouse', 'Medicine', 'Price', 'In stock', ''], page.items.map(o => el('tr', {},
          el('td', { text: o.supplier_name }), el('td', { text: o.location_name }), el('td', { text: productLabel(o) }),
          el('td', { text: formatPrice(o.unit_price, o.currency) }), el('td', { text: o.quantity.toLocaleString('en-GB') }),
          el('td', {}, draft.items.some(i => i.product_id === o.product_id) ? el('span', { text: 'On the order' })
            : button('Add', () => {
              if (!draft.supplier) draft.supplier = { id: o.supplier_organization_id, name: o.supplier_name };
              draft.warehouses.set(o.supplier_location_id, o.location_name);
              draft.items.push({ product_id: o.product_id, name: productLabel(o), price: o.unit_price, currency: o.currency, quantity: 1 });
              renderNewOrder(c);
            })))), draft.supplier ? `${draft.supplier.name} has no listed stock matching that.` : 'No supplier stock matches that.'));
      });
    });

    const cart = draft.items.length ? table(['Medicine', 'Listed price', 'Quantity', ''], draft.items.map((it, idx) => {
      const qty = el('input', { type: 'number', min: 1, step: 1, value: it.quantity, class: 'ws-num', 'aria-label': `Quantity of ${it.name}` });
      qty.addEventListener('input', () => { it.quantity = Number(qty.value); });
      return el('tr', {}, el('td', { text: it.name }), el('td', { text: formatPrice(it.price, it.currency) }), el('td', {}, qty),
        el('td', {}, button('Remove', () => { draft.items.splice(idx, 1); if (!draft.items.length) { draft.supplier = null; draft.warehouses = new Map(); } renderNewOrder(c); }, 'danger')));
    })) : msg('Search for a medicine and add it from a supplier.');

    const warehouse = el('select', { id: 'order-warehouse' }, el('option', { value: '', text: 'Any warehouse (lowest listed price)' }),
      [...draft.warehouses].map(([id, name]) => el('option', { value: id, text: name, selected: draft.warehouse === id })));
    warehouse.addEventListener('change', () => { draft.warehouse = warehouse.value ? Number(warehouse.value) : null; });
    const notes = el('textarea', { id: 'order-notes', rows: 2, maxlength: 5000, placeholder: 'Notes for the supplier (optional)', 'aria-label': 'Notes for the supplier' });
    notes.value = draft.notes || '';
    notes.addEventListener('input', () => { draft.notes = notes.value; });

    const save = button('Save draft', e => {
      if (!draft.items.length) { status.replaceChildren(msg('Add at least one medicine.', 'error')); return; }
      if (draft.items.some(i => !Number.isInteger(i.quantity) || i.quantity < 1)) { status.replaceChildren(msg('Quantities are whole numbers of 1 or more.', 'error')); return; }
      act(e.target, status, async () => {
        const order = await API.purchaseOrders.create({
          pharmacy_organization_id: orgId(), supplier_organization_id: draft.supplier.id,
          pharmacy_location_id: draft.branch, supplier_location_id: draft.warehouse || null,
          notes: (draft.notes || '').trim() || null,
          items: draft.items.map(i => ({ product_id: i.product_id, quantity: i.quantity }))
        });
        state.draft = null; openOrder(order.purchase_order_id);
      }, 'Draft saved.');
    }, 'primary-sm');

    c.replaceChildren(back, heading('New purchase order'),
      el('label', { class: 'ws-inline', text: 'Receiving branch ' }, branchSelect),
      el('p', { class: 'ws-sub', text: draft.supplier ? `Supplier: ${draft.supplier.name} (one supplier per order)` : 'Supplier: chosen by the first medicine you add' }),
      search, results, heading('Order lines'), cart,
      draft.supplier ? el('label', { class: 'ws-inline', text: 'Supplier warehouse ' }, warehouse) : null,
      notes, status, el('div', { class: 'ws-row' }, save));
  }

  async function renderOrderDetail(c, current, id) {
    const o = await API.purchaseOrders.get(id);
    if (!current()) return;
    const status = el('div');
    const allowed = new Set(o.allowed_actions);
    const reload = () => render('orders');
    const back = button('← Back to orders', () => { state.order = null; render('orders'); });

    const dl = el('dl', { class: 'ws-facts' });
    const add = (k, v) => dl.append(el('dt', { text: k }), el('dd', { text: v }));
    add('Status', ORDER_STATUS_LABELS[o.status] || o.status);
    add('Supplier', o.supplier.name + (o.supplier.location_name ? ` · ${o.supplier.location_name}` : ''));
    add('Receiving branch', o.pharmacy.location_name || '—');
    add('Total', `${formatPrice(o.requested_total, o.currency)} requested${o.confirmed_total != null ? ` · ${formatPrice(o.confirmed_total, o.currency)} confirmed` : ''}`);
    add('Created', date(o.created_at));
    if (o.submitted_at) add('Submitted', date(o.submitted_at));
    if (o.responded_at) add('Supplier responded', date(o.responded_at));
    if (o.notes) add('Notes', o.notes);
    if (o.rejection_reason) add('Reason', o.rejection_reason);

    const editable = allowed.has('edit');
    const items = table(['Medicine', 'Requested', 'Unit price', 'Confirmed', 'Line total'].concat(editable ? [''] : []), o.items.map(i => {
      const qty = el('input', { type: 'number', min: 1, step: 1, value: i.requested_quantity, class: 'ws-num', 'aria-label': `Quantity of ${i.product_name}` });
      return el('tr', {},
        el('td', { text: productLabel(i) }),
        el('td', {}, editable ? qty : el('span', { text: String(i.requested_quantity) })),
        el('td', { text: formatPrice(i.requested_unit_price, o.currency) }),
        el('td', { text: i.confirmed_quantity != null ? `${i.confirmed_quantity} at ${formatPrice(i.confirmed_unit_price, o.currency)}` : '—' }),
        el('td', { text: formatPrice(i.confirmed_line_total != null ? i.confirmed_line_total : i.requested_line_total, o.currency) }),
        editable ? el('td', { class: 'ws-cell-actions' },
          button('Update', e => act(e.target, status, async () => { await API.purchaseOrders.updateItem(o.purchase_order_id, i.purchase_order_item_id, { quantity: Number(qty.value) }); reload(); }, 'Quantity updated.')),
          button('Remove', e => act(e.target, status, async () => { await API.purchaseOrders.removeItem(o.purchase_order_id, i.purchase_order_item_id); reload(); }, 'Line removed.'), 'danger')) : null);
    }), 'This order has no lines.');

    const actions = el('div', { class: 'ws-row', id: 'order-actions' });
    ['submit', 'accept_counter', 'mark_delivered', 'cancel', 'delete'].filter(a => allowed.has(a)).forEach(a => {
      actions.append(button(ACTION_LABELS[a], e => {
        if (a === 'delete') {
          if (!confirm(`Delete draft #${o.purchase_order_id}?`)) return;
          act(e.target, status, async () => { await API.purchaseOrders.remove(o.purchase_order_id); state.order = null; render('orders'); }, 'Draft deleted.');
          return;
        }
        let body = {};
        if (a === 'cancel') {
          const reason = (prompt(`Why are you cancelling order #${o.purchase_order_id}? (required)`) || '').trim();
          if (!reason) { status.replaceChildren(msg('A reason is required to cancel an order.', 'error')); return; }
          body = { reason };
        } else if (!confirm(`${ACTION_LABELS[a]} for order #${o.purchase_order_id}?`)) return;
        act(e.target, status, async () => {
          try { await API.purchaseOrders.transition(o.purchase_order_id, ACTION_PATHS[a] || a, body); } catch (err) {
            if (err.status === 409 && err.data && err.data.price_changes) {
              status.replaceChildren(msg('Supplier prices changed since this draft was made. Update the prices, review the order, then submit again.', 'error'),
                button('Update to current prices', ev => act(ev.target, status, async () => { await API.purchaseOrders.reprice(o.purchase_order_id); reload(); }, 'Prices updated.')));
              return;
            }
            throw err;
          }
          reload();
        }, `${ACTION_LABELS[a]}: done.`);
      }, a === 'cancel' || a === 'delete' ? 'danger' : a === 'submit' ? 'primary-sm' : ''));
    });
    if (!actions.children.length) actions.append(msg('No actions available to you at this stage.'));
    const roleNote = !canManage() && ['draft', 'submitted', 'countered', 'accepted'].includes(o.status)
      ? msg('Only owners and managers can submit, cancel or accept counteroffers on purchase orders.') : null;

    const history = el('ol', { class: 'ws-history' }, o.history.map(h => el('li', {
      text: `${date(h.changed_at)}: ${h.from_status ? (ORDER_STATUS_LABELS[h.from_status] || h.from_status) + ' → ' : ''}${ORDER_STATUS_LABELS[h.to_status] || h.to_status}${h.changed_by_name ? ' by ' + h.changed_by_name : ''}${h.note ? ' (' + h.note + ')' : ''}`
    })));
    c.replaceChildren(back, heading(`Order #${o.purchase_order_id}`), dl, heading('Lines'), items, status, actions, roleNote, heading('History'), history);
  }

  // Reset per-organization state when switching organizations.
  const switcher = document.getElementById('org-switch');
  if (switcher) switcher.addEventListener('change', () => { state.inventoryBranch = null; state.order = null; state.draft = null; });

  window.ApexWorkspace = { render };
})();
