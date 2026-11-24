'use strict';
/* Application status (business-status.html) for a pharmacy or supplier that
 * is not approved yet, or no longer is:
 *
 *   in progress       registration not finished: documents still to upload and submit
 *   awaiting review   received; ApexRX reviews the documents; no workspace yet
 *   rejected          the outcome, ApexRX's notes and each document's reason;
 *                     correct and resubmit from the registration page
 *   suspended         blocked; ApexRX's notes; contact ApexRX
 *   approved          the workspace is open
 *
 * Everything comes from GET /organizations/{id}/application. The server
 * refuses the operational features (stock, orders, messages, reservations)
 * until the business is approved; this page only explains it.
 */
(function () {
  const API = window.ApexAPI;
  const $ = id => document.getElementById(id);
  const ORG_KEYS = { pharmacy: 'apexrx_selected_pharmacy', supplier: 'apexrx_selected_supplier' };
  const REGISTRATION = { pharmacy: 'pharmacy-sign-in.html', supplier: 'suppliers.html' };
  const SIGN_IN = { pharmacy: 'pharmacy-sign-in.html', supplier: 'suppliers.html#signin' };
  const BADGES = {
    in_progress: 'Registration not finished', awaiting_review: 'Awaiting review', approved: 'Approved',
    rejected: 'Not approved', suspended: 'Suspended'
  };
  const DOC_STATUS = { missing: 'Not uploaded', pending: 'Awaiting review', approved: 'Approved', rejected: 'Rejected' };

  function el(tag, attrs, children) {
    const e = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => { if (k === 'text') e.textContent = v; else e.setAttribute(k, v); });
    (children || []).forEach(c => e.append(c));
    return e;
  }
  function savedOrg(type) { try { return sessionStorage.getItem(ORG_KEYS[type]); } catch (e) { return null; } }
  function fmtDate(iso) {
    if (!iso) return '';
    try { return new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'long', year: 'numeric' }); } catch (e) { return ''; }
  }

  // Fixed sentences (translated by js/pharmacies-i18n.js, which matches whole texts).
  const CLOSED = { pharmacy: 'Your pharmacy workspace stays closed until your application is approved.', supplier: 'Your supplier workspace stays closed until your application is approved.' };
  function points(app, type) {
    switch (app.stage) {
      case 'awaiting_review':
        return { lead: 'We have received your application.', list: [
          'Your documents are waiting for review by the ApexRX team.', CLOSED[type],
          'Come back after approval: signing in will then open your workspace.'] };
      case 'in_progress':
        return { lead: 'Your registration is not finished yet.', list: [
          'Upload every required document, then submit your application for review.', CLOSED[type]] };
      case 'rejected':
        return { lead: 'Your application was not approved.', list: [
          'Read the note from ApexRX and the reason given for each document.',
          'Correct your details or replace the documents, then submit your application again.', CLOSED[type]] };
      case 'suspended':
        return { lead: 'Your account is suspended.', list: [
          'Your workspace is closed while the account is suspended.',
          'Your records are kept. Contact ApexRX to resolve the suspension.'] };
      default:
        return { lead: 'Your application is approved.', list: ['Your workspace is open.'] };
    }
  }

  function action(app, type) {
    const a = $('bs-action');
    a.hidden = false;
    if (app.stage === 'approved') { a.textContent = 'Open your workspace →'; a.href = API.workspaceFor(type); return; }
    if (app.stage === 'in_progress') { a.textContent = 'Continue registration →'; a.href = REGISTRATION[type]; return; }
    if (app.stage === 'rejected') { a.textContent = 'Correct and resubmit →'; a.href = REGISTRATION[type] + '#review'; return; }
    a.hidden = true;
  }

  function contact(caps) {
    const c = (caps && caps.support_contact) || {};
    const parts = [c.email, c.phone].filter(Boolean);
    $('bs-contact').replaceChildren(...(parts.length
      ? [el('span', { text: 'Questions about your application? Contact ApexRX:' }), document.createTextNode(' '),
         el('strong', { class: 'bs-contact-value', text: parts.join(' · ') })]
      : [el('span', { text: 'Questions about your application? Contact the ApexRX team.' })]));
  }

  function render(app, type) {
    $('bs-org').textContent = app.name;
    $('bs-title').textContent = { approved: 'Your application is approved', suspended: 'Your account is suspended' }[app.stage] || 'Your application';
    const badge = $('bs-badge');
    badge.textContent = BADGES[app.stage] || app.stage;
    badge.className = 'ws-badge status-' + ({ in_progress: 'pending', awaiting_review: 'pending' }[app.stage] || app.stage);
    const p = points(app, type);
    $('bs-lead').textContent = p.lead;
    $('bs-points').replaceChildren(...p.list.map(t => el('li', { text: t })));
    $('bs-submitted').hidden = !app.submitted_at || app.stage === 'in_progress';
    $('bs-submitted-date').textContent = fmtDate(app.submitted_at);
    $('bs-notes-row').hidden = !app.review_notes || app.stage === 'approved';
    $('bs-notes').textContent = app.review_notes || '';
    $('bs-docs').replaceChildren(...app.required_documents.map(d => {
      const li = el('li', {}, [
        el('span', { text: d.label + (d.file_name ? ': ' + d.file_name : '') }),
        el('span', { class: 'ws-badge status-' + (d.status === 'missing' ? 'rejected' : d.status), text: DOC_STATUS[d.status] || d.status })
      ]);
      if (d.status === 'rejected' && d.rejection_reason) li.append(el('small', { text: d.rejection_reason }));
      return li;
    }));
    action(app, type);
    $('bs-loading').hidden = true;
    $('bs-main').hidden = false;
  }

  async function load(focus) {
    $('bs-error').textContent = '';
    if (!API || !API.session.isSignedIn()) { location.replace('index.html'); return; }
    let me;
    try { me = await API.auth.me(); } catch (err) { if (err.status !== 401) $('bs-error').textContent = err.message; return; }
    const type = me.account_type;
    if (type !== 'pharmacy' && type !== 'supplier') { location.replace(API.workspaceFor(type) || 'index.html'); return; }
    const mine = (me.memberships || []).filter(m => m.organization_type === type);
    const m = mine.find(x => String(x.organization_id) === savedOrg(type)) || mine.find(x => x.role === 'owner') || mine[0];
    if (!m) { location.replace(REGISTRATION[type]); return; } // no business registered yet
    try {
      const [app, caps] = await Promise.all([API.organizations.application(m.organization_id), API.auth.capabilities().catch(() => null)]);
      render(app, type);
      contact(caps);
      if (focus) $('bs-title').focus();
    } catch (err) {
      if (err.status !== 401) $('bs-error').textContent = err.message || 'Something went wrong. Please try again.';
    }
  }

  $('bs-refresh').addEventListener('click', async () => {
    $('bs-refresh').disabled = true;
    try { await load(false); $('bs-status').textContent = 'Status updated.'; } finally { $('bs-refresh').disabled = false; }
  });
  $('bs-signout').addEventListener('click', () => {
    const type = API.session.accountType();
    API.auth.logout();
    location.replace(SIGN_IN[type] || 'index.html');
  });
  window.addEventListener('apexrx:signed-out', () => location.replace('index.html'));
  load(true);
})();
