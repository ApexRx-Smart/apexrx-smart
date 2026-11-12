/*
 * ApexRX admin console sections (ops-console-7f3k9q.html), next to js/admin.js which owns
 * sign-in, the section tabs and the Organizations section.
 *
 * Every number and row comes from the existing backend, through js/api.js:
 *   Overview         GET /admin/organizations, /admin/documents, /admin/users,
 *                    /catalogue/drugs, /catalogue/products (each with limit=1,
 *                    reading `total`) and GET /admin/insights/searches
 *   Documents        GET /admin/documents?status=, GET /admin/documents/{id}/download,
 *                    POST /admin/documents/{id}/review
 *   Users            GET /admin/users?q=&is_platform_admin=, PATCH /admin/users/{id}
 *                    (is_active, is_platform_admin)
 *   Catalogue        GET/POST /catalogue/drugs, PATCH /catalogue/drugs/{id},
 *                    GET/POST /catalogue/products, PATCH /catalogue/products/{id}
 *                    (edit, retire and reactivate with is_active)
 *   Search insights  GET /admin/insights/searches?days=&limit=&only_unmet=
 *   Organization     GET /organizations/{id}/inventory, GET .../stock/{product}/adjustments,
 *   detail (read)    GET /purchase-orders?organization_id= (admins may read these, not change them)
 *
 * The backend checks the platform-admin flag on every one of these calls and
 * validates every change; hiding buttons here is only for usability. Values
 * from the API are always inserted as text, never as HTML.
 */
(function () {
  'use strict';

  var API = window.ApexAPI;
  var K = window.ApexAdmin;
  var el = K.el, date = K.date, badge = K.badge, errorText = K.errorText, toast = K.toast;
  var PAGE_SIZE = 20;
  var $ = function (sel) { return document.querySelector(sel); };

  /* ------------------------------------------------------------ helpers */
  // A 401 means the session ended: admin.js returns to the sign-in screen.
  function signedOut(err) { return err && err.status === 401; }

  function notice(selector, text, bad) {
    var m = $(selector);
    m.textContent = text || '';
    m.classList.toggle('bad', !!bad);
    m.hidden = !text;
  }

  // Disable a button and show what it is doing; returns a function restoring it.
  function working(button, label) {
    var original = button.textContent;
    button.disabled = true;
    button.textContent = label;
    return function () { button.disabled = false; button.textContent = original; };
  }

  function emptyRow(tbody, columns, text) {
    tbody.replaceChildren(el('tr', { class: 'empty-row' }, [el('td', { colspan: String(columns), text: text })]));
  }

  // Shared list loading: a sequence number so only the latest request may
  // repaint, "Loading…" while waiting, and the pager afterwards.
  function list(opts) {
    // opts: state, rows, message, pageInfo, columns, fetch(params) -> Promise<Page>, row(item), empty
    var st = opts.state;
    var seq = ++st.seq;
    var message = $(opts.message);
    message.textContent = 'Loading…';
    $(opts.rows).classList.add('loading');
    return opts.fetch({ limit: PAGE_SIZE, offset: st.offset }).then(function (page) {
      if (seq !== st.seq) return;
      // Stepped past the end (e.g. the last item on a page was reviewed): go back one page.
      if (!page.items.length && st.offset > 0 && page.total > 0) {
        st.offset = Math.max(0, st.offset - PAGE_SIZE);
        return list(opts);
      }
      st.total = page.total;
      var tbody = $(opts.rows);
      if (page.items.length) tbody.replaceChildren.apply(tbody, page.items.map(opts.row));
      else emptyRow(tbody, opts.columns, opts.empty);
      message.textContent = '';
      var from = page.total ? st.offset + 1 : 0;
      $(opts.pageInfo).textContent = from + '–' + (st.offset + page.items.length) + ' of ' + page.total;
      setPager(opts.key, st);
    }).catch(function (err) {
      if (seq !== st.seq || signedOut(err)) return;
      message.textContent = errorText(err);
    }).then(function () {
      if (seq === st.seq) $(opts.rows).classList.remove('loading');
    });
  }
  function setPager(key, st) {
    var prev = document.querySelector('[data-page="' + key + ':prev"]');
    var next = document.querySelector('[data-page="' + key + ':next"]');
    if (prev) prev.disabled = st.offset === 0;
    if (next) next.disabled = st.offset + PAGE_SIZE >= st.total;
  }

  var pagers = {}; // key -> { state, load }
  document.querySelectorAll('[data-page]').forEach(function (b) {
    var parts = b.dataset.page.split(':');
    b.addEventListener('click', function () {
      var p = pagers[parts[0]];
      if (!p) return;
      p.state.offset = parts[1] === 'next' ? p.state.offset + PAGE_SIZE : Math.max(0, p.state.offset - PAGE_SIZE);
      p.load();
    });
  });

  function trimmed(value) { var v = String(value == null ? '' : value).trim(); return v || null; }

  /* ----------------------------------------------------------- overview */
  var overviewSeq = 0;
  function loadOverview() {
    var seq = ++overviewSeq;
    notice('#overview-message', '');
    var total = function (page) { return page.total; };
    var jobs = [
      ['orgs_total', API.admin.organizations({ limit: 1 }).then(total)],
      ['orgs_pending', API.admin.organizations({ limit: 1, status: 'pending' }).then(total)],
      ['docs_pending', API.admin.documents({ limit: 1, status: 'pending' }).then(total)],
      ['users_total', API.admin.users({ limit: 1 }).then(total)],
      ['users_admins', API.admin.users({ limit: 1, is_platform_admin: true }).then(total)],
      ['drugs_total', API.catalogue.drugs({ limit: 1 }).then(total)],
      ['products_active', API.catalogue.products({ limit: 1 }).then(total)],
      ['products_all', API.catalogue.products({ limit: 1, include_inactive: true }).then(total)]
    ];
    document.querySelectorAll('[data-overview]').forEach(function (n) { n.textContent = '…'; });
    Promise.all(jobs.map(function (j) {
      return j[1].then(function (v) { return v; }, function (err) { return { error: err }; });
    })).then(function (values) {
      if (seq !== overviewSeq) return;
      var result = {}, failure = null;
      jobs.forEach(function (j, i) {
        if (values[i] && values[i].error) { failure = failure || values[i].error; result[j[0]] = null; }
        else result[j[0]] = values[i];
      });
      result.products_retired = result.products_all !== null && result.products_active !== null
        ? result.products_all - result.products_active : null;
      document.querySelectorAll('[data-overview]').forEach(function (n) {
        var v = result[n.dataset.overview];
        n.textContent = v === null || v === undefined ? '?' : String(v);
      });
      if (failure && !signedOut(failure)) notice('#overview-message', 'Some numbers could not be loaded: ' + errorText(failure), true);
    });

    renderDemand('#overview-top', API.admin.searchInsights({ days: 30, limit: 5 }), seq, 'No patient searches in the last 30 days.');
    renderDemand('#overview-unmet', API.admin.searchInsights({ days: 30, limit: 5, only_unmet: true }), seq, 'Every search in the last 30 days found something.');
  }

  function renderDemand(selector, request, seq, empty) {
    var box = $(selector);
    box.replaceChildren(el('p', { class: 'empty', text: 'Loading…' }));
    request.then(function (rows) {
      if (seq !== overviewSeq) return;
      if (!rows.length) { box.replaceChildren(el('p', { class: 'empty', text: empty })); return; }
      box.replaceChildren(el('ol', { class: 'demand' }, rows.map(function (r) {
        return el('li', {}, [
          el('strong', { text: r.query }),
          el('span', { class: 'muted', text: ' ' + r.searches + ' search' + (r.searches === 1 ? '' : 'es') +
            (r.zero_result_searches ? ' · ' + r.zero_result_searches + ' with no results' : '') })
        ]);
      })));
    }).catch(function (err) {
      if (seq !== overviewSeq || signedOut(err)) return;
      box.replaceChildren(el('p', { class: 'error', text: errorText(err) }));
    });
  }

  document.querySelectorAll('[data-goto-orgs]').forEach(function (a) {
    a.addEventListener('click', function (e) { e.preventDefault(); K.showOrganizations(a.dataset.gotoOrgs); });
  });
  document.querySelectorAll('[data-goto-users]').forEach(function (a) {
    a.addEventListener('click', function (e) {
      e.preventDefault();
      var form = $('#user-filters');
      form.role.value = a.dataset.gotoUsers;
      form.q.value = '';
      users.offset = 0;
      K.goTo('users');
    });
  });
  document.querySelectorAll('[data-goto-catalogue]').forEach(function (a) {
    a.addEventListener('click', function (e) {
      e.preventDefault();
      var target = a.dataset.gotoCatalogue;
      if (target === 'drugs') { catalogueView = 'drugs'; }
      else {
        catalogueView = 'products';
        var form = $('#product-filters');
        form.q.value = '';
        form.include_inactive.checked = target === 'retired';
        products.drug = null;
        products.offset = 0;
      }
      K.goTo('catalogue');
    });
  });

  /* ---------------------------------------------------------- documents */
  var documents = { offset: 0, total: 0, seq: 0, busy: false };
  pagers.documents = { state: documents, load: loadDocuments };

  function loadDocuments() {
    var status = $('#doc-filters').status.value;
    return list({
      key: 'documents', state: documents, rows: '#doc-rows', message: '#doc-list-message', pageInfo: '#doc-page-info', columns: 5,
      empty: status === 'pending' ? 'No documents are waiting for review.' : 'No ' + status + ' documents.',
      fetch: function (params) { params.status = status; return API.admin.documents(params); },
      row: documentRow
    });
  }
  $('#doc-filters').status.addEventListener('change', function () { documents.offset = 0; notice('#doc-message', ''); loadDocuments(); });
  $('#doc-filters').addEventListener('submit', function (e) { e.preventDefault(); });

  function documentRow(d) {
    var actions = [el('button', { type: 'button', class: 'secondary small', text: 'Download', 'aria-label': 'Download ' + d.file_name,
      on: { click: function (e) { downloadDocument(d, e.currentTarget); } } })];
    if (d.verification_status === 'pending') {
      var reason = el('input', { type: 'text', maxlength: '2000', placeholder: 'Reason (required to reject)', 'aria-label': 'Rejection reason for ' + d.file_name });
      actions.push(el('div', { class: 'doc-review' }, [
        reason,
        el('button', { type: 'button', class: 'primary small', text: 'Approve', 'aria-label': 'Approve ' + d.file_name,
          on: { click: function (e) { reviewDocument(d, 'approved', null, e.currentTarget); } } }),
        el('button', { type: 'button', class: 'danger small', text: 'Reject', 'aria-label': 'Reject ' + d.file_name,
          on: { click: function (e) {
            var why = reason.value.trim();
            if (!why) { notice('#doc-message', 'Enter a reason before rejecting ' + d.file_name + '.', true); reason.focus(); return; }
            reviewDocument(d, 'rejected', why, e.currentTarget);
          } } })
      ]));
    }
    return el('tr', { 'data-document': String(d.document_id) }, [
      el('td', {}, [
        el('strong', { text: d.organization_name }),
        el('small', { text: K.cap(d.organization_type) }),
        el('button', { type: 'button', class: 'text-button', text: 'Open organization',
          on: { click: function () { K.openOrganization(d.organization_id); } } })
      ]),
      el('td', {}, [el('strong', { text: K.DOCUMENT_LABELS[d.document_type] || d.document_type }),
        el('small', { text: d.file_name + ' · ' + K.size(d.file_size_bytes) })]),
      el('td', { text: date(d.uploaded_at, true) }),
      el('td', {}, [badge(d.verification_status),
        d.rejection_reason ? el('small', { text: d.rejection_reason }) : null,
        d.reviewed_at ? el('small', { text: 'Reviewed ' + date(d.reviewed_at, true) }) : null]),
      el('td', { class: 'cell-actions' }, actions)
    ]);
  }

  function downloadDocument(d, button) {
    var restore = working(button, 'Downloading…');
    API.admin.downloadDocument(d.document_id).then(function (blob) {
      var url = URL.createObjectURL(blob);
      var a = el('a', { href: url, download: d.file_name });
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(function () { URL.revokeObjectURL(url); }, 60000);
    }).catch(function (err) {
      if (!signedOut(err)) notice('#doc-message', errorText(err), true);
    }).then(restore);
  }

  function reviewDocument(d, decision, reason, button) {
    if (documents.busy) return;
    documents.busy = true;
    var row = button.closest('tr');
    var buttons = Array.prototype.slice.call(row.querySelectorAll('button'));
    buttons.forEach(function (b) { b.disabled = true; });
    button.textContent = decision === 'approved' ? 'Approving…' : 'Rejecting…';
    API.admin.reviewDocument(d.document_id, decision, reason).then(function () {
      notice('#doc-message', d.file_name + ' (' + d.organization_name + ') ' + decision + '.');
      return loadDocuments();
    }).catch(function (err) {
      buttons.forEach(function (b) { b.disabled = false; });
      button.textContent = decision === 'approved' ? 'Approve' : 'Reject';
      if (!signedOut(err)) notice('#doc-message', errorText(err), true);
    }).then(function () { documents.busy = false; });
  }

  /* -------------------------------------------------------------- users */
  var users = { offset: 0, total: 0, seq: 0, busy: false };
  pagers.users = { state: users, load: loadUsers };

  function userFilters() {
    var form = $('#user-filters');
    var params = {};
    if (form.q.value.trim()) params.q = form.q.value.trim();
    if (form.role.value === 'admins') params.is_platform_admin = true;
    if (form.role.value === 'others') params.is_platform_admin = false;
    return params;
  }
  function loadUsers() {
    var filters = userFilters();
    return list({
      key: 'users', state: users, rows: '#user-rows', message: '#user-list-message', pageInfo: '#user-page-info', columns: 6,
      empty: filters.q || filters.is_platform_admin !== undefined ? 'No accounts match these filters.' : 'No user accounts yet.',
      fetch: function (params) { return API.admin.users(Object.assign(params, filters)); },
      row: userRow
    });
  }
  $('#user-filters').addEventListener('submit', function (e) { e.preventDefault(); users.offset = 0; notice('#user-message', ''); loadUsers(); });
  $('#user-filters').role.addEventListener('change', function () { users.offset = 0; notice('#user-message', ''); loadUsers(); });

  function userRow(u) {
    var self = K.me && K.me.user_id === u.user_id;
    var phone = u.verified_phone
      ? [u.verified_phone, el('small', { text: 'Verified by SMS' })]
      : [u.phone || '—', u.phone ? el('small', { text: 'Not verified' }) : null];
    var actions = self
      ? [el('span', { class: 'muted', text: 'Your account' })]
      : [
        el('button', { type: 'button', class: (u.is_active ? 'danger' : 'primary') + ' small',
          text: u.is_active ? 'Deactivate' : 'Reactivate', 'aria-label': (u.is_active ? 'Deactivate ' : 'Reactivate ') + u.email,
          on: { click: function (e) { updateUser(u, { is_active: !u.is_active }, e.currentTarget); } } }),
        el('button', { type: 'button', class: 'secondary small',
          text: u.is_platform_admin ? 'Remove admin' : 'Make admin', 'aria-label': (u.is_platform_admin ? 'Remove admin access from ' : 'Make admin: ') + u.email,
          on: { click: function (e) { updateUser(u, { is_platform_admin: !u.is_platform_admin }, e.currentTarget); } } })
      ];
    return el('tr', { 'data-user': u.email }, [
      el('td', {}, [el('strong', { text: u.name }), self ? el('small', { text: 'You' }) : null]),
      el('td', { text: u.email }),
      el('td', {}, phone),
      el('td', { text: date(u.created_at) }),
      el('td', {}, [
        el('span', { class: 'badge ' + (u.is_active ? 'active' : 'inactive'), text: u.is_active ? 'active' : 'inactive' }),
        u.is_platform_admin ? el('span', { class: 'badge admin', text: 'admin' }) : null
      ]),
      el('td', { class: 'cell-actions' }, actions)
    ]);
  }

  var USER_CONFIRM = {
    deactivate: function (u) { return 'Deactivate ' + u.name + ' (' + u.email + ')?\n\nThey lose access straight away and cannot sign in until an administrator reactivates the account.'; },
    reactivate: function (u) { return 'Reactivate ' + u.name + ' (' + u.email + ')? They will be able to sign in again.'; },
    grant: function (u) { return 'Make ' + u.name + ' (' + u.email + ') a platform administrator?\n\nThey will be able to approve or suspend organizations, review documents, manage user accounts and edit the catalogue.'; },
    revoke: function (u) { return 'Remove platform administrator access from ' + u.name + ' (' + u.email + ')?'; }
  };

  function updateUser(u, change, button) {
    if (users.busy) return;
    var kind = 'is_active' in change ? (change.is_active ? 'reactivate' : 'deactivate') : (change.is_platform_admin ? 'grant' : 'revoke');
    if (!window.confirm(USER_CONFIRM[kind](u))) return;
    users.busy = true;
    var row = button.closest('tr');
    var buttons = Array.prototype.slice.call(row.querySelectorAll('button'));
    buttons.forEach(function (b) { b.disabled = true; });
    button.textContent = 'Saving…';
    API.admin.updateUser(u.user_id, change).then(function (updated) {
      var done = {
        deactivate: updated.email + ' has been deactivated.',
        reactivate: updated.email + ' has been reactivated.',
        grant: updated.email + ' is now a platform administrator.',
        revoke: updated.email + ' is no longer a platform administrator.'
      }[kind];
      notice('#user-message', done);
      var filters = userFilters();
      if (filters.is_platform_admin !== undefined && filters.is_platform_admin !== updated.is_platform_admin) {
        return loadUsers(); // no longer matches the role filter
      }
      row.replaceWith(userRow(updated));
    }).catch(function (err) {
      buttons.forEach(function (b) { b.disabled = false; });
      button.textContent = { deactivate: 'Deactivate', reactivate: 'Reactivate', grant: 'Make admin', revoke: 'Remove admin' }[kind];
      if (!signedOut(err)) notice('#user-message', errorText(err), true);
    }).then(function () { users.busy = false; });
  }

  /* ---------------------------------------------------------- catalogue */
  var catalogueView = 'products';
  var products = { offset: 0, total: 0, seq: 0, drug: null, editing: null, saving: false, busy: false };
  var drugs = { offset: 0, total: 0, seq: 0, editing: null, saving: false };
  pagers.products = { state: products, load: loadProducts };
  pagers.drugs = { state: drugs, load: loadDrugs };

  function showCatalogue() {
    document.querySelectorAll('[data-catalogue-view]').forEach(function (b) {
      b.setAttribute('aria-selected', String(b.dataset.catalogueView === catalogueView));
    });
    $('#products-view').hidden = catalogueView !== 'products';
    $('#drugs-view').hidden = catalogueView !== 'drugs';
    return catalogueView === 'products' ? loadProducts() : loadDrugs();
  }
  document.querySelectorAll('[data-catalogue-view]').forEach(function (b) {
    b.addEventListener('click', function () { catalogueView = b.dataset.catalogueView; showCatalogue(); });
  });

  // Products ----------------------------------------------------------------
  var PRODUCT_FIELDS = ['product_name', 'brand', 'strength', 'dosage_form', 'pack_size', 'barcode', 'manufacturer'];

  function loadProducts() {
    var form = $('#product-filters');
    var filters = { include_inactive: form.include_inactive.checked || undefined };
    if (form.q.value.trim()) filters.q = form.q.value.trim();
    if (products.drug) filters.drug_id = products.drug.drug_id;
    var chip = $('#product-drug-filter');
    if (products.drug) {
      chip.replaceChildren('Showing products of ', el('strong', { text: products.drug.name }), ' ',
        el('button', { type: 'button', class: 'text-button', text: 'Show all products',
          on: { click: function () { products.drug = null; products.offset = 0; loadProducts(); } } }));
      chip.hidden = false;
    } else {
      chip.hidden = true;
    }
    return list({
      key: 'products', state: products, rows: '#product-rows', message: '#product-list-message', pageInfo: '#product-page-info', columns: 7,
      empty: filters.q || filters.drug_id ? 'No products match these filters.' : 'The catalogue has no products yet.',
      fetch: function (params) { return API.catalogue.products(Object.assign(params, filters)); },
      row: productRow
    });
  }
  $('#product-filters').addEventListener('submit', function (e) { e.preventDefault(); products.offset = 0; notice('#product-message', ''); loadProducts(); });
  $('#product-filters').include_inactive.addEventListener('change', function () { products.offset = 0; loadProducts(); });

  function productRow(p) {
    var details = [p.strength, p.dosage_form, p.pack_size].filter(Boolean).join(' · ') || '—';
    return el('tr', { 'data-product': p.product_name, class: p.is_active ? '' : 'retired' }, [
      el('td', {}, [el('strong', { text: p.product_name }), p.brand ? el('small', { text: 'Brand: ' + p.brand }) : null]),
      el('td', {}, [el('button', { type: 'button', class: 'text-button', text: p.drug_name, title: 'Show all products of ' + p.drug_name,
        on: { click: function () { products.drug = { drug_id: p.drug_id, name: p.drug_name }; products.offset = 0; loadProducts(); } } })]),
      el('td', { text: details }),
      el('td', { text: p.barcode || '—' }),
      el('td', { text: p.manufacturer || '—' }),
      el('td', {}, [el('span', { class: 'badge ' + (p.is_active ? 'active' : 'retired'), text: p.is_active ? 'active' : 'retired' })]),
      el('td', { class: 'cell-actions' }, [
        el('button', { type: 'button', class: 'secondary small', text: 'Edit', 'aria-label': 'Edit ' + p.product_name,
          on: { click: function () { openProductForm(p); } } }),
        el('button', { type: 'button', class: (p.is_active ? 'warning' : 'primary') + ' small', text: p.is_active ? 'Retire' : 'Reactivate',
          'aria-label': (p.is_active ? 'Retire ' : 'Reactivate ') + p.product_name,
          on: { click: function (e) { setProductActive(p, !p.is_active, e.currentTarget); } } })
      ])
    ]);
  }

  function setProductActive(p, active, button) {
    if (products.busy) return;
    var question = active
      ? 'Reactivate ' + p.product_name + '? It will appear in patient and supplier search again where pharmacies list it.'
      : 'Retire ' + p.product_name + '?\n\nRetired products no longer appear in patient or supplier search. You can reactivate it later.';
    if (!window.confirm(question)) return;
    products.busy = true;
    var restore = working(button, active ? 'Reactivating…' : 'Retiring…');
    API.catalogue.updateProduct(p.product_id, { is_active: active }).then(function (updated) {
      return loadProducts().then(function () {
        notice('#product-message', updated.product_name + (active ? ' is active again.' : ' has been retired.'));
      });
    }).catch(function (err) {
      restore();
      if (!signedOut(err)) notice('#product-message', errorText(err), true);
    }).then(function () { products.busy = false; });
  }

  var drugSearchTimer = null, drugSearchSeq = 0;
  function fillDrugOptions(q, selected) {
    var seq = ++drugSearchSeq;
    var select = $('#product-drug');
    return API.catalogue.drugs({ q: q || undefined, limit: 50 }).then(function (page) {
      if (seq !== drugSearchSeq) return;
      // Once the admin has picked (or cleared) a drug, a late response must not undo it.
      var picked = select.value ? { drug_id: Number(select.value), name: select.selectedOptions[0].textContent } : null;
      var current = select.dataset.touched ? picked : (selected || picked);
      var items = page.items.slice();
      if (current && !items.some(function (d) { return d.drug_id === current.drug_id; })) items.unshift(current);
      var options = [el('option', { value: '', text: items.length ? 'Choose a drug' : 'No drugs match. Add the drug first.' })]
        .concat(items.map(function (d) { return el('option', { value: String(d.drug_id), text: d.name }); }));
      select.replaceChildren.apply(select, options);
      if (current) select.value = String(current.drug_id);
      else if (items.length === 1 && !select.dataset.touched) select.value = String(items[0].drug_id);
    }).catch(function (err) {
      if (seq === drugSearchSeq && !signedOut(err)) $('#product-form-error').textContent = 'Could not load drugs: ' + errorText(err);
    });
  }
  $('#product-drug').addEventListener('change', function (e) { e.target.dataset.touched = '1'; });
  $('#product-drug-search').addEventListener('input', function (e) {
    clearTimeout(drugSearchTimer);
    var q = e.target.value.trim();
    drugSearchTimer = setTimeout(function () { fillDrugOptions(q); }, 250);
  });

  function openProductForm(p) {
    var form = $('#product-form');
    products.editing = p || null;
    $('#product-form-title').textContent = p ? 'Edit ' + p.product_name : 'Add product';
    $('#product-form-error').textContent = '';
    PRODUCT_FIELDS.forEach(function (f) { form.elements[f].value = p && p[f] ? p[f] : ''; });
    $('#product-drug-search').value = '';
    var select = $('#product-drug');
    delete select.dataset.touched;
    select.replaceChildren(el('option', { value: '', text: 'Choose a drug' }));
    var initial = p ? { drug_id: p.drug_id, name: p.drug_name } : products.drug;
    if (initial) {
      select.appendChild(el('option', { value: String(initial.drug_id), text: initial.name }));
      select.value = String(initial.drug_id);
    }
    fillDrugOptions('', initial);
    form.hidden = false;
    form.elements.product_name.focus();
  }
  $('#product-new').addEventListener('click', function () { openProductForm(null); });
  $('#product-cancel').addEventListener('click', function () { $('#product-form').hidden = true; products.editing = null; });

  $('#product-form').addEventListener('submit', function (e) {
    e.preventDefault();
    if (products.saving) return; // no duplicate submissions
    var form = e.currentTarget;
    var error = $('#product-form-error');
    error.textContent = '';
    var drugId = Number($('#product-drug').value);
    if (!drugId) { error.textContent = 'Choose the drug (active ingredient) this product contains.'; $('#product-drug').focus(); return; }
    if (!trimmed(form.elements.product_name.value)) { error.textContent = 'Enter the product name.'; form.elements.product_name.focus(); return; }

    var editing = products.editing;
    var payload = {};
    if (editing) {
      // Only what changed; a cleared field is sent as null to remove it.
      if (drugId !== editing.drug_id) payload.drug_id = drugId;
      PRODUCT_FIELDS.forEach(function (f) {
        var value = trimmed(form.elements[f].value);
        if (value !== (editing[f] || null)) payload[f] = value;
      });
      if (!Object.keys(payload).length) { error.textContent = 'Nothing has changed.'; return; }
    } else {
      payload.drug_id = drugId;
      PRODUCT_FIELDS.forEach(function (f) { var v = trimmed(form.elements[f].value); if (v) payload[f] = v; });
    }

    products.saving = true;
    var restore = working($('#product-save'), 'Saving…');
    var request = editing ? API.catalogue.updateProduct(editing.product_id, payload) : API.catalogue.createProduct(payload);
    request.then(function (saved) {
      form.hidden = true;
      products.editing = null;
      if (!editing) products.offset = 0;
      // Confirm once the list shows the change, not before.
      return loadProducts().then(function () {
        notice('#product-message', saved.product_name + (editing ? ' updated.' : ' added to the catalogue.'));
        toast(editing ? 'Product updated.' : 'Product added.');
      });
    }).catch(function (err) {
      if (signedOut(err)) return;
      error.textContent = err.status === 409 ? errorText(err) + ' Search for it before adding it again.' : errorText(err);
    }).then(function () { products.saving = false; restore(); });
  });

  // Drugs -------------------------------------------------------------------
  function loadDrugs() {
    var q = $('#drug-filters').q.value.trim();
    return list({
      key: 'drugs', state: drugs, rows: '#drug-rows', message: '#drug-list-message', pageInfo: '#drug-page-info', columns: 4,
      empty: q ? 'No drugs match this search.' : 'The catalogue has no drugs yet.',
      fetch: function (params) { if (q) params.q = q; return API.catalogue.drugs(params); },
      row: drugRow
    });
  }
  $('#drug-filters').addEventListener('submit', function (e) { e.preventDefault(); drugs.offset = 0; notice('#drug-message', ''); loadDrugs(); });

  function drugRow(d) {
    return el('tr', { 'data-drug': d.name }, [
      el('td', {}, [el('strong', { text: d.name })]),
      el('td', { text: d.therapeutic_class || '—' }),
      el('td', { text: date(d.created_at) }),
      el('td', { class: 'cell-actions' }, [
        el('button', { type: 'button', class: 'secondary small', text: 'Edit', 'aria-label': 'Edit ' + d.name,
          on: { click: function () { openDrugForm(d); } } }),
        el('button', { type: 'button', class: 'secondary small', text: 'View products', 'aria-label': 'View products of ' + d.name,
          on: { click: function () {
            products.drug = { drug_id: d.drug_id, name: d.name };
            products.offset = 0;
            $('#product-filters').q.value = '';
            catalogueView = 'products';
            showCatalogue();
          } } })
      ])
    ]);
  }

  function openDrugForm(d) {
    var form = $('#drug-form');
    drugs.editing = d || null;
    $('#drug-form-title').textContent = d ? 'Edit ' + d.name : 'Add drug';
    $('#drug-form-error').textContent = '';
    form.elements.name.value = d ? d.name : '';
    form.elements.therapeutic_class.value = d && d.therapeutic_class ? d.therapeutic_class : '';
    form.hidden = false;
    form.elements.name.focus();
  }
  $('#drug-new').addEventListener('click', function () { openDrugForm(null); });
  $('#drug-cancel').addEventListener('click', function () { $('#drug-form').hidden = true; drugs.editing = null; });

  $('#drug-form').addEventListener('submit', function (e) {
    e.preventDefault();
    if (drugs.saving) return; // no duplicate submissions
    var form = e.currentTarget;
    var error = $('#drug-form-error');
    error.textContent = '';
    var name = trimmed(form.elements.name.value);
    var cls = trimmed(form.elements.therapeutic_class.value);
    if (!name) { error.textContent = 'Enter the drug name.'; form.elements.name.focus(); return; }
    var editing = drugs.editing;
    var payload = {};
    if (editing) {
      if (name !== editing.name) payload.name = name;
      if (cls !== (editing.therapeutic_class || null)) payload.therapeutic_class = cls;
      if (!Object.keys(payload).length) { error.textContent = 'Nothing has changed.'; return; }
    } else {
      payload.name = name;
      if (cls) payload.therapeutic_class = cls;
    }
    drugs.saving = true;
    var restore = working($('#drug-save'), 'Saving…');
    var request = editing ? API.catalogue.updateDrug(editing.drug_id, payload) : API.catalogue.createDrug(payload);
    request.then(function (saved) {
      form.hidden = true;
      drugs.editing = null;
      // Confirm once the list shows the change, not before.
      return loadDrugs().then(function () {
        notice('#drug-message', saved.name + (editing ? ' updated.' : ' added to the catalogue.'));
        toast(editing ? 'Drug updated.' : 'Drug added.');
      });
    }).catch(function (err) {
      if (signedOut(err)) return;
      error.textContent = err.status === 409 ? errorText(err) + ' Search the list to find the existing drug.' : errorText(err);
    }).then(function () { drugs.saving = false; restore(); });
  });

  /* --------------------------------------------------- search insights */
  var insightSeq = 0;
  function loadInsights() {
    var form = $('#insight-filters');
    var params = { days: Number(form.days.value), limit: Number(form.limit.value) };
    if (form.only_unmet.checked) params.only_unmet = true;
    var seq = ++insightSeq;
    var tbody = $('#insight-rows');
    var message = $('#insight-list-message');
    message.textContent = 'Loading…';
    tbody.classList.add('loading');
    return API.admin.searchInsights(params).then(function (rows) {
      if (seq !== insightSeq) return;
      message.textContent = '';
      var period = form.days.selectedOptions[0].textContent.toLowerCase();
      if (!rows.length) {
        emptyRow(tbody, 5, params.only_unmet ? 'No searches without results in the ' + period + '.' : 'No patient searches in the ' + period + '.');
        $('#insight-summary').textContent = '';
        return;
      }
      var searches = 0, unmet = 0;
      rows.forEach(function (r) { searches += r.searches; unmet += r.zero_result_searches; });
      $('#insight-summary').textContent = rows.length + ' search term' + (rows.length === 1 ? '' : 's') + ' shown (' + period +
        '): ' + searches + ' searches, ' + unmet + ' of them with no results.';
      tbody.replaceChildren.apply(tbody, rows.map(insightRow));
    }).catch(function (err) {
      if (seq !== insightSeq || signedOut(err)) return;
      message.textContent = errorText(err);
    }).then(function () { if (seq === insightSeq) tbody.classList.remove('loading'); });
  }
  ['days', 'limit', 'only_unmet'].forEach(function (name) {
    $('#insight-filters').elements[name].addEventListener('change', loadInsights);
  });
  $('#insight-filters').addEventListener('submit', function (e) { e.preventDefault(); loadInsights(); });

  function insightRow(r) {
    var share = r.searches ? Math.round((r.zero_result_searches / r.searches) * 100) : 0;
    return el('tr', { 'data-query': r.query, class: r.zero_result_searches ? 'unmet' : '' }, [
      el('td', {}, [el('strong', { text: r.query })]),
      el('td', { text: String(r.searches) }),
      el('td', {}, [
        String(r.zero_result_searches) + (r.zero_result_searches ? ' (' + share + '%)' : ''),
        el('span', { class: 'meter', 'aria-hidden': 'true' }, [el('span', { style: 'width:' + share + '%' })])
      ]),
      el('td', { text: date(r.last_searched_at, true) }),
      el('td', { class: 'cell-actions' }, [el('button', { type: 'button', class: 'secondary small', text: 'Check catalogue',
        'aria-label': 'Look up ' + r.query + ' in the catalogue',
        on: { click: function () {
          catalogueView = 'products';
          products.drug = null;
          products.offset = 0;
          var f = $('#product-filters');
          f.q.value = r.query;
          f.include_inactive.checked = true;
          K.goTo('catalogue');
        } } })])
    ]);
  }

  /* ------------------------- organization activity (read only, in detail) */
  // Platform admins may read an organization's stock, offers, stock history
  // and order list (allow_admin_read in the backend), but not change them.
  var activity = { orgId: null, seq: 0 };
  var ORDER_LIMIT = 20, STOCK_LIMIT = 100;

  function money(value, currency) {
    if (value === null || value === undefined) return '—';
    var n = Number(value);
    return (isNaN(n) ? value : n.toLocaleString(undefined, { maximumFractionDigits: 2 })) + ' ' + (currency || '');
  }

  function organizationActivity(org, force) {
    if (!force && activity.orgId === org.organization_id) return;
    activity.orgId = org.organization_id;
    var seq = ++activity.seq;
    var stockBox = $('#org-inventory'), orderBox = $('#org-orders');
    stockBox.replaceChildren(el('p', { class: 'empty', text: 'Loading…' }));
    orderBox.replaceChildren(el('p', { class: 'empty', text: 'Loading…' }));

    API.inventory.list(org.organization_id, { limit: STOCK_LIMIT }).then(function (page) {
      if (seq !== activity.seq) return;
      if (!page.items.length) { stockBox.replaceChildren(el('p', { class: 'empty', text: 'No stock recorded yet.' })); return; }
      var tbody = el('tbody', {}, page.items.map(function (item) { return stockRow(org, item); }));
      stockBox.replaceChildren(
        el('div', { class: 'table-wrap' }, [el('table', {}, [
          el('thead', {}, [el('tr', {}, ['Branch', 'Product', 'Quantity', 'Price', 'Shown as', 'Updated', ''].map(function (h) {
            return el('th', {}, [h ? h : el('span', { class: 'sr-only', text: 'History' })]);
          }))]),
          tbody
        ])]),
        page.total > page.items.length ? el('p', { class: 'muted', text: 'Showing the first ' + page.items.length + ' of ' + page.total + ' stock records.' }) : null
      );
    }).catch(function (err) {
      if (seq === activity.seq && !signedOut(err)) stockBox.replaceChildren(el('p', { class: 'error', text: errorText(err) }));
    });

    API.purchaseOrders.list({ organization_id: org.organization_id, limit: ORDER_LIMIT }).then(function (page) {
      if (seq !== activity.seq) return;
      if (!page.items.length) {
        orderBox.replaceChildren(el('p', { class: 'empty', text: org.type === 'supplier' ? 'No orders received yet.' : 'No purchase orders yet.' }));
        return;
      }
      var other = org.type === 'supplier' ? 'pharmacy' : 'supplier';
      orderBox.replaceChildren(
        el('div', { class: 'table-wrap' }, [el('table', {}, [
          el('thead', {}, [el('tr', {}, ['Order', 'Status', other === 'supplier' ? 'Supplier' : 'Pharmacy', 'Lines', 'Total', 'Created', 'Submitted']
            .map(function (h) { return el('th', { text: h }); }))]),
          el('tbody', {}, page.items.map(function (o) {
            var party = o[other];
            return el('tr', {}, [
              el('td', { text: '#' + o.purchase_order_id }),
              el('td', {}, [badge(o.status)]),
              el('td', {}, [el('strong', { text: party.name }), party.location_name ? el('small', { text: party.location_name }) : null]),
              el('td', { text: String(o.item_count) }),
              el('td', {}, [money(o.confirmed_total !== null ? o.confirmed_total : o.requested_total, o.currency),
                o.confirmed_total !== null ? el('small', { text: 'Confirmed' }) : el('small', { text: 'Requested' })]),
              el('td', { text: date(o.created_at) }),
              el('td', { text: o.submitted_at ? date(o.submitted_at) : '—' })
            ]);
          }))
        ])]),
        el('p', { class: 'muted', text: (page.total > page.items.length ? 'The ' + page.items.length + ' most recent of ' + page.total + ' orders. ' : '') +
          'Admins can see this list but not open an order: the backend gives order details only to the organizations involved.' })
      );
    }).catch(function (err) {
      if (seq === activity.seq && !signedOut(err)) orderBox.replaceChildren(el('p', { class: 'error', text: errorText(err) }));
    });
  }

  function stockRow(org, item) {
    var offer = item.offer;
    var details = [item.strength, item.dosage_form, item.pack_size].filter(Boolean).join(' · ');
    var history = el('button', { type: 'button', class: 'secondary small', text: 'History',
      'aria-label': 'Stock history of ' + item.product_name + ' at ' + item.location_name });
    var row = el('tr', {}, [
      el('td', { text: item.location_name }),
      el('td', {}, [el('strong', { text: item.product_name }), el('small', { text: item.drug_name + (details ? ' · ' + details : '') })]),
      el('td', { text: String(item.quantity) }),
      el('td', {}, offer ? [money(offer.unit_price, offer.currency), el('small', { text: offer.is_listed ? 'Listed' : 'Not listed' })] : ['No price']),
      el('td', { text: item.availability_status ? item.availability_status.replace(/_/g, ' ') : 'Not listed' }),
      el('td', { text: date(item.last_updated, true) }),
      el('td', {}, [history])
    ]);
    var open = null;
    history.addEventListener('click', function () {
      if (open) { open.remove(); open = null; history.textContent = 'History'; return; }
      var restore = working(history, 'Loading…');
      API.inventory.adjustments(org.organization_id, item.location_id, item.product_id, { limit: 20 }).then(function (page) {
        var items = page.items || page;
        open = el('tr', { class: 'history-row' }, [el('td', { colspan: '7' }, [
          items.length ? el('ul', { class: 'history' }, items.map(function (a) {
            return el('li', { text: date(a.changed_at, true) + ': ' + (a.old_quantity === null ? 'set to ' : a.old_quantity + ' → ') + a.new_quantity +
              ' (' + String(a.change_type).replace(/_/g, ' ') + (a.changed_by_name ? ', by ' + a.changed_by_name : '') + ')' });
          })) : el('p', { class: 'empty', text: 'No changes recorded.' })
        ])]);
        row.after(open);
        restore();
        history.textContent = 'Hide history';
      }).catch(function (err) {
        restore();
        if (!signedOut(err)) toast(errorText(err));
      });
    });
    return row;
  }

  /* ------------------------------------------------------------ routing */
  var loaders = {
    overview: loadOverview,
    documents: loadDocuments,
    users: loadUsers,
    catalogue: showCatalogue,
    insights: loadInsights
  };
  document.querySelectorAll('[data-refresh]').forEach(function (b) {
    b.addEventListener('click', function () { var load = loaders[b.dataset.refresh]; if (load) load(); });
  });

  window.ApexAdminConsole = {
    show: function (name) { var load = loaders[name]; if (load) load(); },
    organizationActivity: organizationActivity
  };
})();
