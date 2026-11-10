'use strict';
/* accept-invitation.html: the page opened from a staff invitation email.
 *
 * The link is accept-invitation.html#token=<token>. The token is read once,
 * removed from the address bar, and kept only in this page's memory. The
 * backend decides everything (POST /invitations/inspect, /accept-new, /accept):
 *   - no ApexRX account for the invited address: the invitee sets up their own
 *     name and password, which creates the account, joins and signs them in;
 *   - an account exists: they sign in with it (or are already signed in with
 *     it) and accept; no second account is ever created;
 *   - signed in with a different address: refused; they can sign out first.
 * The membership exists only after acceptance, with the role from the invitation.
 */
(function () {
  const $ = s => document.querySelector(s);
  const API = window.ApexAPI;
  const token = new URLSearchParams(location.hash.slice(1)).get('token') || '';
  try { history.replaceState(null, '', location.pathname + location.search); } catch (e) { /* ignore */ }

  const ROLES = { owner: 'Owner', manager: 'Manager', staff: 'Staff' };
  const PROBLEMS = {
    invalid: 'This invitation link is not valid.',
    used: 'This invitation has already been accepted.',
    revoked: 'This invitation was withdrawn.',
    expired: 'This invitation has expired.'
  };
  let invite = null;

  function error(text) { $('#form-error').textContent = text || ''; }
  function errorText(err) { return (err && err.message) || 'Something went wrong. Please try again.'; }
  function only(id) { ['#new-account', '#sign-in', '#signed-in', '#invite-actions'].forEach(s => { $(s).hidden = s !== id; }); }
  async function busy(el, task) {
    const buttons = [...el.querySelectorAll('button')];
    buttons.forEach(b => { b.disabled = true; });
    try { await task(); } finally { buttons.forEach(b => { b.disabled = false; }); }
  }

  function title(text, message, ok) {
    $('#invite-title').textContent = text;
    $('#invite-message').textContent = message || '';
    $('#invite-icon').textContent = ok === false ? '!' : ok ? '✓' : '✉';
    $('#invite-icon').classList.toggle('bad', ok === false);
    $('#invite-title').focus();
  }

  function problem(err) {
    const reason = err && err.data && err.data.reason;
    title(PROBLEMS[reason] || 'We could not open this invitation.', errorText(err), false);
    only(null);
    $('#invite-facts').hidden = true;
    $('#invite-actions').hidden = false;
    const link = $('#invite-continue');
    link.href = 'pharmacies.html#signin';
    link.firstChild.nodeValue = 'Go to sign in ';
  }

  function joined(result) {
    // Open the workspace on this organization (the backend still checks membership).
    try { sessionStorage.setItem(result.organization_type === 'supplier' ? 'apexrx_selected_supplier' : 'apexrx_selected_pharmacy', String(result.organization_id)); } catch (e) { /* ignore */ }
    title(`You have joined ${result.organization_name}.`, `Your role: ${ROLES[result.role] || result.role}. From now on, sign in with your own email and password.`, true);
    only('#invite-actions');
    const link = $('#invite-continue');
    link.href = result.organization_type === 'supplier' ? 'suppliers.html' : 'pharmacies.html';
    link.firstChild.nodeValue = (result.organization_type === 'supplier' ? 'Open your supplier registration' : 'Open your pharmacy workspace') + ' ';
  }

  async function accept() {
    try { joined(await API.invitations.accept(token)); } catch (err) {
      const reason = err.data && err.data.reason;
      if (reason === 'email_mismatch') { error(errorText(err)); showSignedIn(); return; }
      if (err.status === 401) { showForInvite(); error('Please sign in again.'); return; }
      if (PROBLEMS[reason]) { problem(err); return; }
      error(errorText(err));
    }
  }

  async function signedInEmail() {
    const known = API.session.email();
    if (known) return known;
    try { return (await API.auth.me()).email.toLowerCase(); } catch (e) { return null; }
  }

  async function showSignedIn() {
    const email = await signedInEmail();
    if (!email) { showForInvite(); return; }
    only('#signed-in');
    $('#signed-in-email').textContent = email;
    const same = email === invite.email;
    $('#accept-button').hidden = !same;
    if (!same) error(`This invitation is for ${invite.email}. Sign out, then sign in with that address (or set it up) to accept.`);
  }

  function showForInvite() {
    if (invite.account_exists) {
      only('#sign-in');
      $('#sign-in').elements.email.value = invite.email;
      $('#sign-in').elements.password.focus();
    } else {
      only('#new-account');
      $('#new-account').elements.name.focus();
    }
  }

  $('#new-account').addEventListener('submit', e => {
    e.preventDefault();
    const f = e.currentTarget.elements, name = f.name.value.trim(), password = f.password.value;
    if (!name) { error('Enter your name.'); f.name.focus(); return; }
    if (password.length < 8) { error('Use at least 8 characters for your password.'); f.password.focus(); return; }
    if (password !== f.confirm.value) { error('Your passwords do not match.'); f.confirm.focus(); return; }
    error('');
    busy(e.currentTarget, async () => {
      try {
        const result = await API.invitations.acceptNew(token, name, password);
        API.auth.useToken(result, invite.email);
        f.password.value = ''; f.confirm.value = '';
        joined(result);
      } catch (err) {
        const reason = err.data && err.data.reason;
        if (reason === 'account_exists') { invite.account_exists = true; showForInvite(); error(errorText(err)); return; }
        if (PROBLEMS[reason]) { problem(err); return; }
        error(errorText(err));
      }
    });
  });

  $('#sign-in').addEventListener('submit', e => {
    e.preventDefault();
    const f = e.currentTarget.elements;
    if (!f.password.value) { error('Enter your password.'); return; }
    error('');
    busy(e.currentTarget, async () => {
      try { await API.auth.login(invite.email, f.password.value); } catch (err) {
        error(err.status === 401 ? 'Incorrect password.' : errorText(err)); return;
      }
      f.password.value = '';
      await accept();
    });
  });

  $('#accept-button').addEventListener('click', () => { error(''); busy($('#signed-in'), accept); });
  $('#switch-account').addEventListener('click', () => { API.auth.logout(); error(''); showForInvite(); });

  (async function start() {
    if (!token) { problem({ data: { reason: 'invalid' }, message: 'Open the link from your invitation email.' }); return; }
    try { invite = await API.invitations.inspect(token); } catch (err) { problem(err); return; }
    title(`Join ${invite.organization_name} on ApexRX`, invite.account_exists
      ? 'Sign in with your ApexRX account to accept.'
      : 'Set up your own account to accept.');
    $('#invite-facts').hidden = false;
    $('#invite-org').textContent = invite.organization_name;
    $('#invite-role').textContent = ROLES[invite.role] || invite.role;
    $('#invite-email').textContent = invite.email;
    $('#invite-by').textContent = invite.invited_by_name || '—';
    if (API.session.isSignedIn()) await showSignedIn(); else showForInvite();
  })();
})();
