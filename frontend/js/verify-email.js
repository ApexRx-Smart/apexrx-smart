'use strict';
/* verify-email.html: the page opened from the verification email.
 *
 * The link is verify-email.html?next=pharmacy|supplier#token=<token>. The token
 * is in the fragment, so it never reaches a server in a request line or a
 * Referer header. It is read once, removed from the address bar (and history),
 * and sent to POST /auth/email/verify, which decides everything: invalid,
 * expired, already used, replaced by a newer email, or verified.
 *
 * No session is needed: the link proves access to the mailbox. On success, an
 * open registration tab in this browser is told (BroadcastChannel) so it can
 * continue by itself.
 */
(function () {
  const $ = s => document.querySelector(s);
  const API = window.ApexAPI;
  const params = new URLSearchParams(location.search);
  const next = params.get('next') === 'supplier' ? 'supplier' : 'pharmacy';
  const page = next === 'supplier' ? 'suppliers.html' : 'pharmacies.html';
  const token = new URLSearchParams(location.hash.slice(1)).get('token') || '';

  // Remove the token from the address bar and the history entry.
  try { history.replaceState(null, '', location.pathname + location.search); } catch (e) { /* ignore */ }

  const MESSAGES = {
    verified: ['Your email address is verified.', 'You can continue your registration now.'],
    already: ['Your email address is already verified.', 'This link was used before. You can continue your registration.'],
    invalid: ['This verification link is not valid.', 'It may be incomplete or no longer belong to your account.'],
    expired: ['This verification link has expired.', 'Links work for a limited time.'],
    used: ['This verification link has already been used.', 'Each link works once.'],
    superseded: ['A newer verification email was sent.', 'Only the link in the most recent email works.'],
    error: ['We could not check your link.', 'Please try again in a moment.']
  };

  function finish(kind, detail, email) {
    const [title, message] = MESSAGES[kind];
    const ok = kind === 'verified' || kind === 'already';
    $('#verify-title').textContent = title;
    $('#verify-message').textContent = detail && !ok ? detail : message;
    $('#verify-icon').textContent = ok ? '✓' : '!';
    $('#verify-icon').classList.toggle('bad', !ok);
    $('#verify-email-row').hidden = !email;
    $('#verify-email').textContent = email || '';
    const link = $('#verify-continue');
    link.href = page + (ok ? '' : '#signin');
    link.firstChild.nodeValue = (ok ? 'Continue registration' : 'Go to sign in') + ' ';
    $('#verify-actions').hidden = false;
    $('#verify-help').hidden = ok;
    document.title = (ok ? 'Email verified' : 'Verification link problem') + ' — ApexRX Smart';
    $('#verify-title').focus();
    if (ok) {
      try { const c = new BroadcastChannel('apexrx-email-verification'); c.postMessage({ type: 'verified' }); c.close(); } catch (e) { /* not supported */ }
    }
  }

  if (!token) { finish('invalid'); return; }
  API.auth.email.verify(token).then(res => {
    finish(res.already_verified ? 'already' : 'verified', '', res.email_masked);
  }).catch(err => {
    const reason = err && err.data && err.data.reason;
    if (reason && MESSAGES[reason]) finish(reason, err.message);
    else if (err && err.status === 422) finish('invalid');
    else finish('error', err && err.status === 0 ? err.message : '');
  });
})();
