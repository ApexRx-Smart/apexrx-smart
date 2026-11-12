'use strict';
/* reset-password.html
 *   no token  -> "Forgot password?": POST /auth/password/forgot. The answer is
 *                the same whether or not the address has an account.
 *   #token=…  -> from the reset email: POST /auth/password/reset/check, then
 *                POST /auth/password/reset. The token is removed from the
 *                address bar. Success signs out every session of the account.
 * ?next=pharmacy|supplier|admin chooses where "Back to sign in" leads.
 */
(function () {
  const $ = s => document.querySelector(s);
  const API = window.ApexAPI;
  const next = new URLSearchParams(location.search).get('next');
  const signIn = next === 'supplier' ? 'suppliers.html#signin' : next === 'admin' ? 'ops-console-7f3k9q.html' : 'pharmacies.html#signin';
  const token = new URLSearchParams(location.hash.slice(1)).get('token') || '';
  try { history.replaceState(null, '', location.pathname + location.search); } catch (e) { /* ignore */ }
  $('#back-to-signin').href = signIn;

  const PROBLEMS = {
    invalid: 'This password reset link is not valid.',
    used: 'This password reset link has already been used.',
    superseded: 'A newer password reset email was sent.',
    expired: 'This password reset link has expired.'
  };
  function error(text) { $('#form-error').textContent = text || ''; }
  function errorText(err) { return (err && err.message) || 'Something went wrong. Please try again.'; }
  function title(text, message, ok) {
    $('#reset-title').textContent = text;
    $('#reset-message').textContent = message || '';
    $('#reset-icon').textContent = ok === false ? '!' : ok ? '✓' : '✉';
    $('#reset-icon').classList.toggle('bad', ok === false);
    $('#reset-title').focus();
  }
  async function busy(form, task) {
    const buttons = [...form.querySelectorAll('button')];
    buttons.forEach(b => { b.disabled = true; });
    try { await task(); } finally { buttons.forEach(b => { b.disabled = false; }); }
  }
  function linkProblem(err) {
    const reason = err && err.data && err.data.reason;
    $('#reset-form').hidden = true;
    title(PROBLEMS[reason] || 'We could not check this link.', errorText(err), false);
    $('#forgot-form').hidden = false; // request a new link right here
  }

  $('#forgot-form').addEventListener('submit', e => {
    e.preventDefault();
    const f = e.currentTarget.elements, email = f.email.value.trim();
    if (!/^\S+@\S+\.\S+$/.test(email)) { error('Enter a valid email address.'); f.email.focus(); return; }
    error('');
    busy(e.currentTarget, async () => {
      try {
        const res = await API.auth.password.forgot(email);
        $('#forgot-form').hidden = true;
        title('Check your email', res.detail, true);
      } catch (err) { error(errorText(err)); }
    });
  });

  $('#reset-form').addEventListener('submit', e => {
    e.preventDefault();
    const f = e.currentTarget.elements;
    if (f.password.value.length < 8) { error('Use at least 8 characters for your password.'); f.password.focus(); return; }
    if (f.password.value !== f.confirm.value) { error('Your passwords do not match.'); f.confirm.focus(); return; }
    error('');
    busy(e.currentTarget, async () => {
      try {
        const res = await API.auth.password.reset(token, f.password.value);
        f.password.value = ''; f.confirm.value = '';
        API.session.clear(); // every session of the account was signed out
        $('#reset-form').hidden = true;
        title('Your password has been changed.', res.detail, true);
        $('#back-to-signin').firstChild.nodeValue = 'Sign in with your new password →';
      } catch (err) {
        if (err.data && PROBLEMS[err.data.reason]) linkProblem(err); else error(errorText(err));
      }
    });
  });

  (async function start() {
    if (!token) {
      // Email delivery is temporarily disabled: say so instead of offering a form that cannot work.
      let caps = null;
      try { caps = await API.auth.capabilities(); } catch (e) { /* unknown: show the form; the backend answers */ }
      if (caps && caps.password_reset === false) {
        title('Password reset is temporarily unavailable',
          'ApexRX cannot send emails at the moment, so passwords cannot be reset by email. If you cannot sign in, contact ApexRX support. Your account and its data are unchanged.', false);
        return;
      }
      $('#forgot-form').hidden = false;
      return;
    }
    title('Choose a new password', 'This link works once.');
    try {
      const res = await API.auth.password.check(token);
      $('#reset-email').textContent = res.email_masked;
      $('#reset-form').hidden = false;
      $('#reset-form').elements.password.focus();
    } catch (err) { linkProblem(err); }
  })();
})();
