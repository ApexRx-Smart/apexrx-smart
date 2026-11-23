'use strict';
/* Mobile number verification (verify-phone.html), on the ApexRX API (js/api.js):
 *
 *   GET  /auth/phone          the account's number, whether it is verified or must
 *                             be, and the code already sent (its id only)
 *   PATCH /auth/me {phone}    change the number (a new number is never verified)
 *   POST /auth/phone/send     send a code by SMS to the account's number
 *   POST /auth/phone/verify   {challenge_id, code}
 *
 * The page never decides that a number is verified: the server checks the code,
 * and refuses every other call while the account must verify. Pages reach this one
 * through api.js when the server answers 403 phone_verification_required; ?next=
 * (a page of this site only) is where to go afterwards.
 */
(function () {
  window.APEXRX_NO_PHONE_REDIRECT = true; // this page handles the requirement itself
  const API = window.ApexAPI;
  const $ = id => document.getElementById(id);
  const params = new URLSearchParams(location.search);

  // Only a page of this site (file name, optional .html, its own query).
  function safeNext(raw) {
    if (!raw) return null;
    let url;
    try { url = new URL(raw, location.href); } catch (e) { return null; }
    if (url.origin !== location.origin) return null;
    const page = url.pathname.split('/').pop();
    if (!/^[a-z0-9-]+(\.html)?$/.test(page) || /^verify-phone/.test(page)) return null;
    return page + url.search;
  }
  function home(me) {
    const types = (me.memberships || []).map(m => m.organization_type);
    if (types.includes('pharmacy')) return 'pharmacy-dashboard.html';
    if (types.includes('supplier')) return 'supplier-dashboard.html';
    if (me.is_platform_admin) return 'index.html';
    return 'reservations.html';
  }

  const state = { challenge: null, resendAt: null, timer: null, next: safeNext(params.get('next')), me: null };
  const error = text => { $('vp-error').textContent = text || ''; };
  const status = text => { $('vp-status').textContent = text || ''; };
  const time = d => new Date(d).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  function show(view) {
    $('vp-send-view').hidden = view !== 'send';
    $('vp-code-form').hidden = view !== 'code';
    $('vp-number-form').hidden = view !== 'number';
    $('vp-number-view').hidden = view === 'number' || view === 'done';
    $('vp-done').hidden = view !== 'done';
  }

  function tick() {
    clearInterval(state.timer);
    const update = () => {
      const left = state.resendAt ? Math.ceil((state.resendAt - Date.now()) / 1000) : 0;
      $('vp-resend').disabled = left > 0;
      $('vp-resend-wait').textContent = left > 0 ? '(' + left + ' s)' : '';
      if (left <= 0) clearInterval(state.timer);
    };
    update();
    state.timer = setInterval(update, 1000);
  }

  function codeSent(challengeId, expiresAt, resendAt, masked) {
    state.challenge = challengeId;
    state.resendAt = resendAt ? new Date(resendAt).getTime() : null;
    $('vp-sent-text').replaceChildren('A code was sent to ', Object.assign(document.createElement('strong'), { textContent: masked }), '.');
    $('vp-expiry').textContent = expiresAt ? 'The code expires at ' + time(expiresAt) + '.' : '';
    $('vp-code').value = '';
    show('code');
    tick();
    $('vp-code').focus();
  }

  function finished() {
    show('done');
    error(''); status('');
    const target = state.next || home(state.me || {});
    $('vp-continue').href = target;
    $('vp-done-text').textContent = 'You can continue.';
    $('vp-continue').focus();
  }

  function explain(x) {
    const code = x && x.data && x.data.code;
    if (code === 'phone_missing' || code === 'invalid_phone' || code === 'sms_number_rejected') {
      error(x.message); openNumberForm(); return;
    }
    if (['code_expired', 'code_superseded', 'too_many_attempts', 'code_used', 'phone_changed', 'invalid_challenge'].includes(code)) {
      error(x.message); state.challenge = null; state.resendAt = null; tick(); return;
    }
    if (code === 'already_verified') { load(); return; }
    error(x && x.status === 0 ? x.message : (x && x.message) || 'Something went wrong. Please try again.');
  }

  async function send() {
    error(''); status('Sending the code…');
    const button = $('vp-code-form').hidden ? $('vp-send') : $('vp-resend');
    button.disabled = true;
    try {
      const sent = await API.auth.phone.send();
      status('');
      $('vp-sandbox').hidden = !sent.sandbox;
      codeSent(sent.challenge_id, sent.expires_at, sent.resend_available_at, sent.phone_masked);
    } catch (x) {
      status('');
      if (x && x.status === 429 && x.data && x.data.retry_after) {
        state.resendAt = Date.now() + x.data.retry_after * 1000; tick();
      }
      explain(x);
    } finally { if (button === $('vp-send')) button.disabled = false; }
  }

  async function verify(e) {
    e.preventDefault();
    const code = $('vp-code').value.replace(/\s/g, '');
    error('');
    if (!/^\d{6}$/.test(code)) { error('Enter the 6-digit code from the SMS.'); $('vp-code').focus(); return; }
    if (!state.challenge) { error('Request a new code first.'); return; }
    $('vp-verify').disabled = true;
    try {
      await API.auth.phone.verify(state.challenge, code);
      finished();
    } catch (x) {
      explain(x);
      $('vp-code').select();
    } finally { $('vp-verify').disabled = false; }
  }

  function openNumberForm() {
    const input = $('vp-number-form').elements.phone;
    input.value = state.me && state.me.phone ? state.me.phone : '';
    show('number');
    input.focus();
  }

  async function saveNumber(e) {
    e.preventDefault();
    const phone = $('vp-number-form').elements.phone.value.trim();
    error('');
    if (!/^\+?[0-9 ()\-./]{9,30}$/.test(phone)) { error('Enter a valid mobile number, for example 078 812 3456.'); return; }
    $('vp-number-save').disabled = true;
    try {
      state.me = await API.auth.updateMe({ phone });
      state.challenge = null; state.resendAt = null;
      await load();
    } catch (x) { explain(x); }
    finally { $('vp-number-save').disabled = false; }
  }

  async function load() {
    error('');
    const s = await API.auth.phone.status();
    $('vp-loading').hidden = true;
    $('vp-main').hidden = false;
    $('vp-sandbox').hidden = !s.sandbox;
    $('vp-number').textContent = s.phone_masked || 'No number yet';
    if (s.verified) { finished(); return; }
    if (!s.phone) { openNumberForm(); return; }
    if (!s.sms_available) {
      show('send');
      $('vp-send').disabled = true;
      error('SMS codes cannot be sent right now. Please try again later.');
      return;
    }
    if (s.challenge_id) codeSent(s.challenge_id, s.expires_at, s.resend_available_at, s.phone_masked);
    else show('send');
  }

  async function start() {
    if (!API || !API.session.isSignedIn()) { location.replace('index.html'); return; }
    $('vp-send').addEventListener('click', send);
    $('vp-resend').addEventListener('click', send);
    $('vp-code-form').addEventListener('submit', verify);
    $('vp-change').addEventListener('click', openNumberForm);
    $('vp-number-form').addEventListener('submit', saveNumber);
    $('vp-number-cancel').addEventListener('click', () => { error(''); load(); });
    $('vp-signout').addEventListener('click', () => { API.auth.logout(); location.replace('index.html'); });
    window.addEventListener('apexrx:signed-out', () => location.replace('index.html'));
    try {
      state.me = await API.auth.me();
      await load();
    } catch (x) {
      $('vp-loading').textContent = (x && x.message) || 'Something went wrong. Please reload the page.';
    }
  }
  start();
})();
