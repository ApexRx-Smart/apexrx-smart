'use strict';
/* Patient sign-in (patient-sign-in.html, data-auth="signin") and registration
 * (patient-register.html, data-auth="create"), on the ApexRX API (js/api.js).
 *
 *   Sign in:  POST /auth/login, then GET /auth/me.
 *   Register: POST /auth/register (name, email, mobile number, password), then
 *             POST /auth/login (the session is set up at once), then the patient's
 *             reservations. The mobile number is the contact number for every
 *             reservation (the backend stores it as +250...). When the server
 *             requires it (me.phone_verification_pending), the patient first
 *             verifies it with an SMS code on verify-phone.html, then continues.
 *
 * Where it goes next: ?next= when it is a patient page on this site (only
 * reservations.html with its own parameters: a reservation being made or one
 * reservation), otherwise reservations.html. Anything else (another site, another
 * page, a protocol) is ignored, so the link cannot send anyone elsewhere.
 * Reserving while signed out keeps the medicine and branch in next=, and the form
 * draft (quantity, phone, note) stays in this tab (js/reservations.js).
 *
 * Already signed in as a patient: straight on to next. Signed in with a pharmacy,
 * supplier or administrator account: that is not a patient account, so it is said
 * so (with Sign out) instead of opening the patient workspace.
 */
(function () {
  const API = window.ApexAPI;
  const $ = id => document.getElementById(id);
  const MODE = document.body.dataset.auth === 'create' ? 'create' : 'signin';
  const NEXT_PARAMS = ['location', 'product', 'ref', 'lang', 'welcome'];

  // Only reservations.html, only its known parameters.
  function safeNext(raw) {
    if (!raw) return 'reservations.html';
    let url;
    try { url = new URL(raw, location.href); } catch (e) { return 'reservations.html'; }
    if (url.origin !== location.origin || !/\/reservations\.html$/.test(url.pathname)) return 'reservations.html';
    const keep = new URLSearchParams();
    url.searchParams.forEach((v, k) => { if (NEXT_PARAMS.includes(k) && /^[\w-]{1,40}$/.test(v)) keep.set(k, v); });
    const q = keep.toString();
    return 'reservations.html' + (q ? '?' + q : '');
  }
  const params = new URLSearchParams(location.search);
  const NEXT = safeNext(params.get('next'));
  const lang = () => (document.documentElement.lang || 'en').slice(0, 2);
  const withLang = href => href + (href.includes('?') ? '&' : '?') + 'lang=' + encodeURIComponent(lang());

  // Keep next= on the link to the other page (register <-> sign in).
  const other = $('auth-other');
  if (other && params.get('next')) other.href = other.getAttribute('href').split('?')[0] + '?next=' + encodeURIComponent(NEXT);

  const form = $('patient-auth'), err = $('form-error'), panel = $('account-panel');
  function fail(text) { err.textContent = text || ''; }
  function isPatient(me) { return !me.is_platform_admin && !(me.memberships || []).length; }
  function go(welcome, me) {
    let target = NEXT;
    if (welcome && target === 'reservations.html') target += '?welcome=1';
    target = withLang(target);
    // The server refuses everything else until the number is verified.
    if (me && me.phone_verification_pending) target = 'verify-phone.html?next=' + encodeURIComponent(target);
    location.replace(target);
  }
  function notPatient(me) {
    form.hidden = true;
    panel.hidden = false;
    $('account-panel-text').textContent = 'You are signed in with a pharmacy, supplier or ApexRX account, not a patient account. Sign out to use a patient account.';
  }
  $('account-signout').addEventListener('click', () => { API.auth.logout(); location.replace('index.html'); });

  form.addEventListener('submit', async e => {
    e.preventDefault();
    const f = form.elements;
    const name = f.name ? f.name.value.trim() : '', email = f.email.value.trim(), password = f.password.value;
    const phone = f.phone ? f.phone.value.trim() : '';
    fail('');
    if (MODE === 'create' && !name) { fail('Enter your name.'); f.name.focus(); return; }
    if (!email || !/^\S+@\S+\.\S+$/.test(email)) { fail('Enter a valid email address.'); f.email.focus(); return; }
    if (MODE === 'create' && !phone) { fail('Enter your mobile number.'); f.phone.focus(); return; }
    if (MODE === 'create' && !/^\+?[0-9 ()\-./]{9,30}$/.test(phone)) { fail('Enter a valid mobile number, for example 078 812 3456.'); f.phone.focus(); return; }
    if (!password) { fail('Enter your password.'); f.password.focus(); return; }
    if (MODE === 'create' && password.length < 8) { fail('Use at least 8 characters for your password.'); f.password.focus(); return; }
    if (MODE === 'create' && f.confirm && password !== f.confirm.value) { fail('Your passwords do not match.'); f.confirm.focus(); return; }
    const button = $('auth-submit'); button.disabled = true;
    try {
      if (MODE === 'create') {
        try { await API.auth.register({ name, email, phone, password }); } catch (x) {
          if (x && x.status === 409) { fail('An account with this email already exists. Sign in instead.'); return; }
          if (x && x.status === 422 && x.data && (x.data.code === 'invalid_phone' || x.data.code === 'phone_required')) { fail(x.message); f.phone.focus(); return; }
          throw x;
        }
      }
      try { await API.auth.login(email, password); } catch (x) {
        if (x && x.status === 401) { fail('Incorrect email or password.'); return; }
        throw x;
      }
      f.password.value = ''; if (f.confirm) f.confirm.value = '';
      const me = await API.auth.me();
      if (!isPatient(me)) {
        // A business account is not taken into the patient workspace, and its session is not kept here.
        API.auth.logout();
        form.hidden = false; panel.hidden = true;
        fail('This account belongs to a pharmacy, a supplier or ApexRX. Sign in with a patient account.');
        return;
      }
      go(MODE === 'create', me);
    } catch (x) {
      fail(x && x.status === 0 ? x.message : (x && x.message) || 'Something went wrong. Please try again.');
    } finally { button.disabled = false; }
  });

  // Signed in already: a patient continues; another kind of account is told so.
  async function start() {
    const msg = params.get('signed_out');
    if (msg === 'idle') fail('You were signed out after a period of inactivity. Sign in again to continue.');
    else if (msg === 'expired' || msg === 'revoked') fail('Your session has ended. Please sign in again.');
    if (!API || !API.session.isSignedIn()) return;
    try {
      const me = await API.auth.me();
      if (isPatient(me)) go(false, me); else notPatient(me);
    } catch (x) { /* an ended session: api.js clears it; the form stays */ }
  }
  start();
})();
