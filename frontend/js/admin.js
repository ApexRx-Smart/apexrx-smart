/*
 * ApexRX admin dashboard (admin.html).
 *
 * Uses only existing endpoints, through js/api.js:
 *   POST /auth/login, GET /auth/me                    sign in, check is_platform_admin
 *   GET  /admin/organizations?type=&status=&q=        list, and the overview counts (its `total`)
 *   GET  /admin/organizations/{id}                    detail: locations, members, documents
 *   POST /admin/organizations/{id}/review             approve / reject / suspend
 *   GET  /admin/documents/{id}/download               streamed by the backend (private bucket)
 *   POST /admin/documents/{id}/review                 approve / reject a document
 *
 * Security lives in the backend: every /admin endpoint checks the token and
 * the platform-admin flag. Hiding or disabling buttons here is only for
 * usability. All values from the API are inserted as text, never as HTML.
 */
(function () {
  'use strict';

  var API = window.ApexAPI;
  var PAGE_SIZE = 20;

  // Mirrors ORG_TRANSITIONS in backend/app/api/admin.py (the backend decides).
  var TRANSITIONS = {
    pending: ['approved', 'rejected'],
    approved: ['suspended'],
    suspended: ['approved', 'rejected'],
    rejected: ['approved']
  };
  var DOCUMENT_LABELS = {
    business_license: 'Business license',
    pharmacy_license: 'Pharmacy license',
    owner_id: 'Owner ID'
  };
  var COUNTS = [
    ['total', {}],
    ['pharmacy', { type: 'pharmacy' }],
    ['supplier', { type: 'supplier' }],
    ['pending', { status: 'pending' }],
    ['approved', { status: 'approved' }],
    ['rejected', { status: 'rejected' }],
    ['suspended', { status: 'suspended' }]
  ];

  var $ = function (sel) { return document.querySelector(sel); };
  var state = { filters: { type: '', status: '', q: '' }, offset: 0, total: 0, current: null, busy: false, listSeq: 0 };

  /* ------------------------------------------------------------ helpers */
  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'text') node.textContent = attrs[k];
      else if (k === 'class') node.className = attrs[k];
      else if (k === 'on') Object.keys(attrs.on).forEach(function (ev) { node.addEventListener(ev, attrs.on[ev]); });
      else if (attrs[k] !== null && attrs[k] !== undefined && attrs[k] !== false) node.setAttribute(k, attrs[k] === true ? '' : attrs[k]);
    });
    (children || []).forEach(function (c) {
      if (c === null || c === undefined) return;
      node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    });
    return node;
  }
  function date(value, withTime) {
    if (!value) return '—';
    var d = new Date(value);
    return isNaN(d) ? '—' : d.toLocaleString(undefined, withTime
      ? { dateStyle: 'medium', timeStyle: 'short' } : { dateStyle: 'medium' });
  }
  function size(bytes) {
    if (bytes >= 1048576) return (bytes / 1048576).toFixed(1) + ' MB';
    return Math.max(1, Math.round(bytes / 1024)) + ' KB';
  }
  function badge(status) { return el('span', { class: 'badge ' + status, text: status }); }
  function cap(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : ''; }
  function errorText(err) { return (err && err.message) || 'Something went wrong.'; }

  var toastTimer;
  function toast(message) {
    var t = $('#toast');
    t.textContent = message;
    t.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.classList.remove('show'); }, 3500);
  }
  function detailMessage(message, bad) {
    var m = $('#detail-message');
    m.textContent = message || '';
    m.classList.toggle('bad', !!bad);
    m.hidden = !message;
  }

  /* ------------------------------------------------------------- session */
  function showLogin(message) {
    $('#dashboard-view').hidden = true;
    $('#who').hidden = true;
    $('#login-view').hidden = false;
    $('#login-error').textContent = message || '';
    var form = $('#login-form');
    form.password.value = '';
    (form.email.value ? form.password : form.email).focus();
  }

  function showDashboard(me) {
    $('#login-view').hidden = true;
    $('#who-email').textContent = me.email;
    $('#who').hidden = false;
    $('#dashboard-view').hidden = false;
    showList();
    refreshAll();
  }

  // Confirms the signed-in account is a platform admin (for the UI only; the
  // backend refuses every /admin call from anyone else).
  function enter() {
    return API.auth.me().then(function (me) {
      if (!me.is_platform_admin) {
        API.session.clear();
        showLogin('This account is not an ApexRX administrator.');
        return;
      }
      showDashboard(me);
    });
  }

  $('#login-form').addEventListener('submit', function (e) {
    e.preventDefault();
    var form = e.target;
    var email = form.email.value.trim();
    var password = form.password.value;
    if (!email || !password) { $('#login-error').textContent = 'Enter your email and password.'; return; }
    var button = $('#login-button');
    button.disabled = true;
    button.textContent = 'Signing in…';
    $('#login-error').textContent = '';
    API.auth.login(email, password)
      .then(enter)
      .catch(function (err) {
        API.session.clear();
        showLogin(err.status === 401 ? 'Incorrect email or password.' : errorText(err));
      })
      .then(function () { button.disabled = false; button.textContent = 'Sign in'; });
  });

  $('#sign-out').addEventListener('click', function () {
    window.removeEventListener('apexrx:signed-out', onSignedOut);
    API.auth.logout();
    window.addEventListener('apexrx:signed-out', onSignedOut);
    showLogin('You have signed out.');
  });

  // api.js fires this on any 401 (expired, invalid or revoked token).
  function onSignedOut() {
    if (!$('#dashboard-view').hidden) showLogin('Your session has expired. Please sign in again.');
  }
  window.addEventListener('apexrx:signed-out', onSignedOut);

  /* ------------------------------------------------------------ overview */
  function refreshCounts() {
    COUNTS.forEach(function (c) {
      var node = document.querySelector('[data-count="' + c[0] + '"]');
      API.admin.organizations(Object.assign({ limit: 1 }, c[1]))
        .then(function (page) { node.textContent = page.total; })
        .catch(function () { node.textContent = '?'; });
    });
  }

  function markActiveStat() {
    document.querySelectorAll('.stat').forEach(function (b) {
      b.classList.toggle('active',
        b.dataset.filterType === state.filters.type && b.dataset.filterStatus === state.filters.status && !state.filters.q);
    });
  }

  document.querySelectorAll('.stat').forEach(function (b) {
    b.addEventListener('click', function () {
      var form = $('#filters');
      form.type.value = b.dataset.filterType;
      form.status.value = b.dataset.filterStatus;
      form.q.value = '';
      applyFilters();
    });
  });

  /* ---------------------------------------------------------------- list */
  function applyFilters() {
    var form = $('#filters');
    state.filters = { type: form.type.value, status: form.status.value, q: form.q.value.trim() };
    state.offset = 0;
    showList();
    loadList();
  }
  $('#filters').addEventListener('submit', function (e) { e.preventDefault(); applyFilters(); });
  $('#filters').type.addEventListener('change', applyFilters);
  $('#filters').status.addEventListener('change', applyFilters);

  function loadList() {
    var rows = $('#org-rows');
    var message = $('#list-message');
    markActiveStat();
    message.textContent = 'Loading…';
    var params = { limit: PAGE_SIZE, offset: state.offset };
    Object.keys(state.filters).forEach(function (k) { if (state.filters[k]) params[k] = state.filters[k]; });
    var seq = ++state.listSeq; // only the latest request may update the table
    return API.admin.organizations(params).then(function (page) {
      if (seq !== state.listSeq) return;
      state.total = page.total;
      rows.replaceChildren.apply(rows, page.items.map(orgRow));
      message.textContent = page.items.length ? '' : 'No organizations match these filters.';
      var from = page.total ? state.offset + 1 : 0;
      $('#page-info').textContent = from + '–' + (state.offset + page.items.length) + ' of ' + page.total;
      $('#prev').disabled = state.offset === 0;
      $('#next').disabled = state.offset + PAGE_SIZE >= page.total;
    }).catch(function (err) {
      if (err.status === 401 || seq !== state.listSeq) return;
      rows.replaceChildren();
      message.textContent = errorText(err);
    });
  }

  function orgRow(o) {
    var contact = [o.email, o.phone].filter(Boolean);
    return el('tr', {}, [
      el('td', {}, [el('strong', { text: o.name })]),
      el('td', { text: cap(o.type) }),
      el('td', { text: date(o.created_at) }),
      el('td', {}, [badge(o.status)]),
      el('td', {}, contact.length ? contact.map(function (c, i) { return i ? el('small', { text: c }) : c; }) : ['—']),
      el('td', {}, [el('button', {
        type: 'button', class: 'secondary small', text: 'Open',
        'aria-label': 'Open ' + o.name,
        on: { click: function () { openOrganization(o.organization_id); } }
      })])
    ]);
  }

  $('#prev').addEventListener('click', function () { state.offset = Math.max(0, state.offset - PAGE_SIZE); loadList(); });
  $('#next').addEventListener('click', function () { state.offset += PAGE_SIZE; loadList(); });
  $('#refresh').addEventListener('click', refreshAll);

  function refreshAll() {
    refreshCounts();
    if (state.current) return openOrganization(state.current.organization_id, true);
    return loadList();
  }

  function showList() {
    state.current = null;
    $('#detail-view').hidden = true;
    $('#list-view').hidden = false;
  }
  $('#back').addEventListener('click', function () { showList(); loadList(); });

  /* -------------------------------------------------------------- detail */
  function openOrganization(id, keepMessage) {
    if (!keepMessage) detailMessage('');
    return API.admin.organization(id).then(function (org) {
      state.current = org;
      $('#list-view').hidden = true;
      $('#detail-view').hidden = false;
      renderDetail(org);
      if (!keepMessage) $('#detail-name').focus();
    }).catch(function (err) {
      if (err.status !== 401) toast(errorText(err));
    });
  }

  function renderDetail(org) {
    $('#detail-type').textContent = org.type;
    $('#detail-name').textContent = org.name;
    var status = $('#detail-status');
    status.className = 'badge ' + org.status;
    status.textContent = org.status;

    var facts = [
      ['Organization ID', String(org.organization_id)],
      ['Type', cap(org.type)],
      ['Email', org.email || '—'],
      ['Phone', org.phone || '—'],
      ['Registered', date(org.created_at, true)],
      ['Last updated', date(org.updated_at, true)],
      ['Last reviewed', org.reviewed_at ? date(org.reviewed_at, true) : 'Not reviewed yet'],
      ['Review notes', org.review_notes || '—']
    ];
    var dl = $('#detail-info');
    dl.replaceChildren();
    facts.forEach(function (f) { dl.appendChild(el('dt', { text: f[0] })); dl.appendChild(el('dd', { text: f[1] })); });

    renderReview(org);
    renderDocuments(org.documents);
    renderLocations(org.locations);
    renderMembers(org.members);
  }

  function renderReview(org) {
    var allowed = TRANSITIONS[org.status] || [];
    var pendingDocs = org.documents.filter(function (d) { return d.verification_status === 'pending'; }).length;
    var hints = [];
    document.querySelectorAll('#review-box [data-decision]').forEach(function (b) {
      var decision = b.dataset.decision;
      b.hidden = allowed.indexOf(decision) === -1;
      b.disabled = decision === 'approved' && pendingDocs > 0;
    });
    if (allowed.indexOf('approved') !== -1 && pendingDocs) {
      hints.push('Review the ' + pendingDocs + ' pending document' + (pendingDocs > 1 ? 's' : '') + ' below before approving.');
    }
    if (org.status === 'approved') hints.push('Approved organizations can be suspended. Reject a suspended organization to close it.');
    if (org.status === 'pending' && !org.documents.length) hints.push('This organization has not uploaded any verification documents.');
    $('#review-hint').textContent = hints.join(' ');
    $('#review-hint').hidden = !hints.length;
    $('#review-notes').value = '';
  }

  document.querySelectorAll('#review-box [data-decision]').forEach(function (b) {
    b.addEventListener('click', function () {
      var org = state.current;
      if (!org || state.busy) return;
      var decision = b.dataset.decision;
      var notes = $('#review-notes').value.trim();
      if (decision !== 'approved' && !notes) {
        detailMessage('Add review notes explaining why before you ' + (decision === 'rejected' ? 'reject' : 'suspend') + ' this organization.', true);
        $('#review-notes').focus();
        return;
      }
      var verb = { approved: 'Approve', rejected: 'Reject', suspended: 'Suspend' }[decision];
      if (!window.confirm(verb + ' ' + org.name + '?')) return;
      state.busy = true;
      API.admin.reviewOrganization(org.organization_id, decision, notes)
        .then(function (updated) {
          state.current = updated;
          renderDetail(updated);
          detailMessage(org.name + ' is now ' + updated.status + '.');
          refreshCounts();
        })
        .catch(function (err) { if (err.status !== 401) detailMessage(errorText(err), true); })
        .then(function () { state.busy = false; });
    });
  });

  function renderDocuments(documents) {
    var box = $('#documents');
    if (!documents.length) { box.replaceChildren(el('p', { class: 'empty', text: 'No documents submitted.' })); return; }
    box.replaceChildren.apply(box, documents.map(function (d) {
      var reasonInput = el('input', { type: 'text', maxlength: '2000', placeholder: 'Reason (required to reject)', 'aria-label': 'Rejection reason for ' + d.file_name });
      var review = d.verification_status === 'pending' ? el('div', { class: 'doc-review' }, [
        reasonInput,
        el('button', { type: 'button', class: 'primary small', text: 'Approve document', on: { click: function () { reviewDocument(d, 'approved'); } } }),
        el('button', { type: 'button', class: 'danger small', text: 'Reject document', on: { click: function () {
          var reason = reasonInput.value.trim();
          if (!reason) { detailMessage('Enter a reason before rejecting ' + d.file_name + '.', true); reasonInput.focus(); return; }
          reviewDocument(d, 'rejected', reason);
        } } })
      ]) : null;
      return el('div', { class: 'item' }, [
        el('div', { class: 'item-head' }, [
          el('div', {}, [
            el('strong', { text: DOCUMENT_LABELS[d.document_type] || d.document_type }), ' ',
            badge(d.verification_status)
          ]),
          el('button', { type: 'button', class: 'secondary small', text: 'Download', 'aria-label': 'Download ' + d.file_name,
            on: { click: function (e) { downloadDocument(d, e.currentTarget); } } })
        ]),
        el('div', { class: 'meta', text: d.file_name + ' · ' + size(d.file_size_bytes) + ' · ' + d.mime_type + ' · uploaded ' + date(d.uploaded_at, true) }),
        d.reviewed_at ? el('div', { class: 'meta', text: 'Reviewed ' + date(d.reviewed_at, true) + (d.rejection_reason ? ' — ' + d.rejection_reason : '') }) : null,
        review
      ]);
    }));
  }

  function downloadDocument(d, button) {
    button.disabled = true;
    button.textContent = 'Downloading…';
    API.admin.downloadDocument(d.document_id).then(function (blob) {
      var url = URL.createObjectURL(blob);
      var a = el('a', { href: url, download: d.file_name });
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(function () { URL.revokeObjectURL(url); }, 60000);
    }).catch(function (err) {
      if (err.status !== 401) detailMessage(errorText(err), true);
    }).then(function () {
      button.disabled = false;
      button.textContent = 'Download';
    });
  }

  function reviewDocument(d, decision, reason) {
    if (state.busy) return;
    state.busy = true;
    API.admin.reviewDocument(d.document_id, decision, reason)
      .then(function () {
        return openOrganization(state.current.organization_id, true);
      })
      .then(function () { detailMessage(d.file_name + ' ' + decision + '.'); })
      .catch(function (err) { if (err.status !== 401) detailMessage(errorText(err), true); })
      .then(function () { state.busy = false; });
  }

  function renderLocations(locations) {
    var box = $('#locations');
    if (!locations.length) { box.replaceChildren(el('p', { class: 'empty', text: 'No locations registered.' })); return; }
    box.replaceChildren.apply(box, locations.map(function (l) {
      var place = [l.address, l.city, l.region].filter(Boolean).join(', ') || 'No address';
      var contact = [l.phone && 'Phone ' + l.phone, l.whatsapp_phone && 'WhatsApp ' + l.whatsapp_phone].filter(Boolean).join(' · ');
      var coords = l.latitude !== null && l.longitude !== null ? l.latitude + ', ' + l.longitude : null;
      return el('div', { class: 'item' }, [
        el('div', { class: 'item-head' }, [el('strong', { text: l.name }), l.is_active ? null : badge('inactive')]),
        el('div', { class: 'meta', text: place }),
        contact ? el('div', { class: 'meta', text: contact }) : null,
        coords ? el('div', { class: 'meta', text: 'Coordinates ' + coords }) : null
      ]);
    }));
  }

  function renderMembers(members) {
    var box = $('#members');
    if (!members.length) { box.replaceChildren(el('p', { class: 'empty', text: 'No members.' })); return; }
    box.replaceChildren.apply(box, members.map(function (m) {
      return el('div', { class: 'item' }, [
        el('div', { class: 'item-head' }, [el('strong', { text: m.name }), el('span', { class: 'badge', text: m.role + (m.is_active ? '' : ' (inactive)') })]),
        el('div', { class: 'meta', text: [m.email, m.phone].filter(Boolean).join(' · ') })
      ]);
    }));
  }

  /* ---------------------------------------------------------------- start */
  if (API.session.isSignedIn()) {
    enter().catch(function (err) {
      API.session.clear();
      showLogin(err.status === 401 ? 'Your session has expired. Please sign in again.' : errorText(err));
    });
  } else {
    showLogin('');
  }
})();
